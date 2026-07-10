"""Verify GPU visibility and measure model-load VRAM for 2B-4.

This script is a preparation aid only. It can load selected faster-whisper models
when the user explicitly runs it, but it never calls ``model.transcribe(...)`` and
therefore never measures inference peak VRAM.

Terminology used here:
- total_vram_mib: GPU total memory reported by nvidia-smi.
- baseline_used_mib: device-total used VRAM before model construction.
- after_load_used_mib: device-total used VRAM after WhisperModel(...) returns.
- load_delta_mib: after_load_used_mib - baseline_used_mib.
- inference_peak_used_mib: not measured by this script; future benchmark runner
  sampling only, during real transcribe calls.
- after_unload_used_mib: device-total used VRAM after model deletion and GC.

The device-total nvidia-smi values are not process-exclusive. Do not present
these observations as peak inference VRAM or as production model selection data.
"""

from __future__ import annotations

import argparse
import gc
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Iterable

from ctranslate2 import get_cuda_device_count


@dataclass(frozen=True)
class VramSnapshot:
    used_mib: int
    free_mib: int
    total_mib: int


@dataclass(frozen=True)
class ModelLoadObservation:
    model_name: str
    device: str
    compute_type: str
    load_time_ms: float
    total_vram_mib: int
    baseline_used_mib: int
    after_load_used_mib: int
    load_delta_mib: int
    after_unload_used_mib: int
    unload_delta_mib: int
    inference_peak_used_mib: None = None


class VramPeakSampler:
    """Future-use device-total VRAM sampler for benchmark inference windows.

    The sampler is safe to stop in success, exception, and Ctrl+C paths. It uses
    nvidia-smi only and does not provide process-exclusive memory accounting.
    """

    def __init__(self, interval_sec: float = 0.2) -> None:
        self.interval_sec = interval_sec
        self.samples: list[VramSnapshot] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                snap = query_vram()
            except Exception:
                self._stop_event.wait(self.interval_sec)
                continue
            with self._lock:
                self.samples.append(snap)
            self._stop_event.wait(self.interval_sec)

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> dict[str, int | str | None]:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        with self._lock:
            samples = list(self.samples)
        if not samples:
            return {
                "sampling_scope": "device-total",
                "gpu_peak_used_mib": None,
                "sample_count": 0,
            }
        return {
            "sampling_scope": "device-total",
            "gpu_peak_used_mib": max(s.used_mib for s in samples),
            "gpu_min_free_mib": min(s.free_mib for s in samples),
            "sample_count": len(samples),
        }


def query_vram(timeout_sec: int = 10) -> VramSnapshot:
    output = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=memory.used,memory.free,memory.total",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        timeout=timeout_sec,
    )
    first = output.strip().splitlines()[0]
    used, free, total = [int(part.strip()) for part in first.split(",")[:3]]
    return VramSnapshot(used_mib=used, free_mib=free, total_mib=total)


def query_gpu_identity(timeout_sec: int = 10) -> str:
    output = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,compute_cap,driver_version",
            "--format=csv,noheader",
        ],
        text=True,
        timeout=timeout_sec,
    )
    return output.strip().splitlines()[0].strip()


def measure_model_load(model_name: str, compute_type: str) -> ModelLoadObservation:
    from faster_whisper import WhisperModel

    baseline = query_vram()
    start = time.perf_counter()
    model = WhisperModel(model_name, device="cuda", compute_type=compute_type)
    end = time.perf_counter()
    after_load = query_vram()

    del model
    gc.collect()
    time.sleep(2.0)
    after_unload = query_vram()

    return ModelLoadObservation(
        model_name=model_name,
        device="cuda",
        compute_type=compute_type,
        load_time_ms=(end - start) * 1000,
        total_vram_mib=baseline.total_mib,
        baseline_used_mib=baseline.used_mib,
        after_load_used_mib=after_load.used_mib,
        load_delta_mib=after_load.used_mib - baseline.used_mib,
        after_unload_used_mib=after_unload.used_mib,
        unload_delta_mib=after_unload.used_mib - baseline.used_mib,
    )


def print_observation(obs: ModelLoadObservation) -> None:
    print(f"model_name: {obs.model_name}")
    print(f"device: {obs.device}")
    print(f"compute_type: {obs.compute_type}")
    print(f"load_time_ms: {obs.load_time_ms:.1f}")
    print(f"total_vram_mib: {obs.total_vram_mib}")
    print(f"baseline_used_mib: {obs.baseline_used_mib}")
    print(f"after_load_used_mib: {obs.after_load_used_mib}")
    print(f"load_delta_mib: {obs.load_delta_mib}")
    print("inference_peak_used_mib: NOT_MEASURED_BY_THIS_SCRIPT")
    print(f"after_unload_used_mib: {obs.after_unload_used_mib}")
    print(f"unload_delta_mib: {obs.unload_delta_mib}")
    print("label: model-load VRAM observation, not peak inference VRAM")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure model-load VRAM observations only")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only print GPU identity and baseline VRAM; do not load any model",
    )
    parser.add_argument(
        "--case",
        choices=["small-float16", "medium-int8-float16", "medium-float16"],
        action="append",
        help="Model-load case to measure. May be repeated. Default measures the three known cases.",
    )
    return parser.parse_args(list(argv))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    print("2B-4 GPU VRAM check")
    print("CUDA devices:", get_cuda_device_count())
    if get_cuda_device_count() == 0:
        print("ERROR: no CUDA device detected")
        return 1
    print("GPU:", query_gpu_identity())
    baseline = query_vram()
    print("baseline_total_vram_mib:", baseline.total_mib)
    print("baseline_used_mib:", baseline.used_mib)
    print("baseline_free_mib:", baseline.free_mib)
    print("sampling_scope: device-total")

    if args.check_only:
        print("No model loaded. No inference run.")
        return 0

    cases = args.case or ["small-float16", "medium-int8-float16", "medium-float16"]
    mapping = {
        "small-float16": ("small", "float16"),
        "medium-int8-float16": ("medium", "int8_float16"),
        "medium-float16": ("medium", "float16"),
    }
    for case in cases:
        print("\n" + "=" * 60)
        print(f"MODEL-LOAD OBSERVATION: {case}")
        print("=" * 60)
        model_name, compute_type = mapping[case]
        obs = measure_model_load(model_name, compute_type)
        print_observation(obs)

    print("\nNo real transcription was run. Inference peak VRAM remains unmeasured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
