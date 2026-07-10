"""CLI for the independent 2B-4 local ASR benchmark runner.

Default behavior is offline and local-path only. ``--dry-run`` validates the
configuration and manifest and prints the planned number of attempts without
loading faster-whisper or running transcription.
"""

from __future__ import annotations

import argparse
import os
import site
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from asr_benchmark_core import (
    BenchmarkConfig,
    ResourceSampler,
    Segment,
    TranscriptionInfo,
    dry_run_plan,
    run_benchmark,
    validate_benchmark_config,
    validate_manifest,
    write_all_outputs,
)


_DLL_DIRECTORY_HANDLES: list[Any] = []


def discover_windows_cuda_dll_dirs() -> list[Path]:
    """Find CUDA runtime DLL directories installed as Python wheels.

    CTranslate2's Windows wheels can use DLLs supplied by packages such as
    ``nvidia-cublas-cu12``. Those packages place DLLs under
    ``site-packages/nvidia/<component>/bin`` but do not always put that location
    on PATH for child Python processes. This function is local to the benchmark
    runner and does not modify application ASR code.
    """

    if os.name != "nt":
        return []

    roots: list[Path] = []
    for candidate in site.getsitepackages() + [site.getusersitepackages()]:
        if candidate:
            roots.append(Path(candidate))
    dirs: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        nvidia_root = root / "nvidia"
        if not nvidia_root.is_dir():
            continue
        for bin_dir in nvidia_root.glob("*/bin"):
            resolved = bin_dir.resolve()
            if resolved in seen:
                continue
            if any(resolved.glob("*.dll")):
                seen.add(resolved)
                dirs.append(resolved)
    return dirs


def add_windows_cuda_dll_dirs() -> list[Path]:
    """Add discovered CUDA DLL directories to PATH and DLL search path."""

    dirs = discover_windows_cuda_dll_dirs()
    if not dirs:
        return []
    existing_path = os.environ.get("PATH", "")
    existing_parts = existing_path.split(os.pathsep) if existing_path else []
    added: list[Path] = []
    for directory in dirs:
        directory_text = str(directory)
        if directory_text not in existing_parts:
            existing_parts.insert(0, directory_text)
            added.append(directory)
        if hasattr(os, "add_dll_directory"):
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(directory_text))
    os.environ["PATH"] = os.pathsep.join(existing_parts)
    return added


class FasterWhisperTranscriber:
    """Thin adapter loaded only for non-dry-run benchmark execution."""

    def __init__(self, model_path: Path, *, device: str, compute_type: str) -> None:
        from faster_whisper import WhisperModel

        self.model = WhisperModel(str(model_path), device=device, compute_type=compute_type, local_files_only=True)

    def transcribe(self, audio_path: Path, *, language: str, beam_size: int) -> tuple[Any, Any]:
        segments, info = self.model.transcribe(str(audio_path), language=language, beam_size=beam_size)
        return segments, info


class NoModelTranscriber:
    """Optional no-model adapter for CLI smoke checks only."""

    def transcribe(self, audio_path: Path, *, language: str, beam_size: int) -> tuple[list[Segment], TranscriptionInfo]:
        return [Segment(text="", start=0.0, end=0.0)], TranscriptionInfo(language=language, language_probability=0.0, duration=0.0)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a reproducible local faster-whisper ASR benchmark")
    parser.add_argument("--manifest", required=True, type=Path, help="UTF-8 JSONL corpus manifest")
    parser.add_argument("--corpus-root", required=True, type=Path, help="Root directory for manifest-relative audio paths")
    parser.add_argument("--model-path", required=True, type=Path, help="Local faster-whisper model snapshot path")
    parser.add_argument("--model-name", required=True, help="Human-readable model name, e.g. small or medium")
    parser.add_argument("--model-revision", required=True, help="Full model commit hash revision")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"], help="Execution device")
    parser.add_argument("--compute-type", default="float16", help="CTranslate2 compute type")
    parser.add_argument("--language", default="zh", help="Language hint passed to transcribe")
    parser.add_argument("--beam-size", default=1, type=int, help="Beam size for transcribe")
    parser.add_argument("--warmup-runs", default=2, type=int, help="Warmup repetitions excluded from hot stats")
    parser.add_argument("--repeats", default=3, type=int, help="Measured repetitions")
    parser.add_argument("--output-dir", default=Path("asr-benchmark-output"), type=Path, help="Output directory for benchmark artifacts")
    parser.add_argument("--max-items", type=int, help="Limit manifest entries for smoke checks")
    parser.add_argument("--seed", default=0, type=int, help="Recorded seed for reproducible ordering; no random shuffle is used")
    parser.add_argument("--offline", action="store_true", default=True, help="Force offline/local-only behavior (default)")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and manifest only; do not load model or transcribe")
    parser.add_argument("--no-model-smoke", action="store_true", help="Internal smoke mode that writes outputs using an injected no-model transcriber")
    parser.add_argument("--include-full-text-output", action="store_true", help="Explicitly include full references/hypotheses in local ignored output files")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> BenchmarkConfig:
    return BenchmarkConfig(
        manifest=args.manifest,
        corpus_root=args.corpus_root,
        model_path=args.model_path,
        model_name=args.model_name,
        model_revision=args.model_revision,
        device=args.device,
        compute_type=args.compute_type,
        language=args.language,
        beam_size=args.beam_size,
        warmup_runs=args.warmup_runs,
        repeats=args.repeats,
        output_dir=args.output_dir,
        max_items=args.max_items,
        seed=args.seed,
        offline=True,
        dry_run=args.dry_run,
        include_full_text=args.include_full_text_output,
    )


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = build_config(args)

    config_errors = validate_benchmark_config(config)
    manifest_result = validate_manifest(config.manifest, config.corpus_root)
    errors = config_errors + manifest_result.errors
    if errors:
        print_json({"ok": False, "errors": errors})
        return 2

    if config.dry_run:
        print_json({"ok": True, "plan": dry_run_plan(config, manifest_result.entries)})
        return 0

    if args.no_model_smoke:
        smoke_config = replace(config, dry_run=False)
        result = run_benchmark(smoke_config, manifest_result.entries, NoModelTranscriber(), sampler_factory=None, model_load_ms=0.0)
        paths = write_all_outputs(result)
        print_json({"ok": True, "mode": "no-model-smoke", "outputs": [str(path) for path in paths], "exit_code": result.exit_code})
        return result.exit_code

    load_start = time.perf_counter()
    add_windows_cuda_dll_dirs()
    try:
        transcriber = FasterWhisperTranscriber(config.model_path, device=config.device, compute_type=config.compute_type)
    except Exception as exc:
        print_json({"ok": False, "errors": [f"failed to load local model: {type(exc).__name__}: {exc}"]})
        return 10
    model_load_ms = (time.perf_counter() - load_start) * 1000

    result = run_benchmark(config, manifest_result.entries, transcriber, sampler_factory=ResourceSampler, model_load_ms=model_load_ms)
    paths = write_all_outputs(result)
    print_json({"ok": result.exit_code == 0, "outputs": [str(path) for path in paths], "exit_code": result.exit_code})
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
