from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COSYVOICE_ROOT = ROOT / "external" / "CosyVoice"
MATCHA_ROOT = COSYVOICE_ROOT / "third_party" / "Matcha-TTS"
MODEL_DIR = COSYVOICE_ROOT / "pretrained_models" / "Fun-CosyVoice3-0.5B-2512"
OUTPUT_PATH = ROOT / "data" / "cosyvoice-smoke-output.wav"

sys.path.insert(0, str(COSYVOICE_ROOT))
sys.path.insert(0, str(MATCHA_ROOT))


def gpu_snapshot():
    try:
        import torch

        if not torch.cuda.is_available():
            return {"cuda_available": False}
        return {
            "cuda_available": True,
            "gpu_name": torch.cuda.get_device_name(0),
            "allocated_mb": round(torch.cuda.memory_allocated(0) / 1024 / 1024, 2),
            "reserved_mb": round(torch.cuda.memory_reserved(0) / 1024 / 1024, 2),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": repr(exc)}


def wav_duration_ms(path: Path) -> int:
    import soundfile as sf

    info = sf.info(str(path))
    return round(info.frames / info.samplerate * 1000)


def main() -> None:
    started = time.perf_counter()
    if not MODEL_DIR.exists():
        raise SystemExit(f"model dir missing: {MODEL_DIR}")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    from cosyvoice.cli.cosyvoice import AutoModel

    before = gpu_snapshot()
    model_started = time.perf_counter()
    cosyvoice = AutoModel(model_dir=str(MODEL_DIR), load_trt=False, load_vllm=False, fp16=True)
    model_ms = round((time.perf_counter() - model_started) * 1000)
    after_load = gpu_snapshot()

    text = "今天晚上我想先休息十分钟，然后再继续整理桌面。"
    prompt_text = "You are a helpful assistant.<|endofprompt|>希望你以后能够做的比我还好呦。"
    prompt_wav = str(COSYVOICE_ROOT / "asset" / "zero_shot_prompt.wav")

    synth_started = time.perf_counter()
    results = []
    for result in cosyvoice.inference_zero_shot(
        text,
        prompt_text,
        prompt_wav,
        stream=False,
    ):
        results.append(result)
    synth_ms = round((time.perf_counter() - synth_started) * 1000)
    if not results:
        raise SystemExit("CosyVoice returned no audio chunks")

    import soundfile as sf

    speech = results[0]["tts_speech"].squeeze(0).detach().cpu().numpy()
    sf.write(str(OUTPUT_PATH), speech, cosyvoice.sample_rate, subtype="PCM_16")
    after_synth = gpu_snapshot()
    duration_ms = wav_duration_ms(OUTPUT_PATH)

    print(
        json.dumps(
            {
                "status": "PASS",
                "model_dir": str(MODEL_DIR),
                "output_path": str(OUTPUT_PATH),
                "output_bytes": OUTPUT_PATH.stat().st_size,
                "sample_rate": cosyvoice.sample_rate,
                "audio_duration_ms": duration_ms,
                "model_load_ms": model_ms,
                "synthesis_ms": synth_ms,
                "total_ms": round((time.perf_counter() - started) * 1000),
                "gpu_before": before,
                "gpu_after_load": after_load,
                "gpu_after_synth": after_synth,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
