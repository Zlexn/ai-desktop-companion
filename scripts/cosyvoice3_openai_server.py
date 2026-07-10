from __future__ import annotations

import base64
import io
import json
import sys
import time
from pathlib import Path
from typing import Literal

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from scripts.cosyvoice_text import split_tts_text

ROOT = Path(__file__).resolve().parents[1]
COSYVOICE_ROOT = ROOT / "external" / "CosyVoice"
MATCHA_ROOT = COSYVOICE_ROOT / "third_party" / "Matcha-TTS"
MODEL_DIR = COSYVOICE_ROOT / "pretrained_models" / "Fun-CosyVoice3-0.5B-2512"
PROMPT_WAV = COSYVOICE_ROOT / "asset" / "zero_shot_prompt.wav"
PROMPT_TEXT = "You are a helpful assistant.<|endofprompt|>希望你以后能够做的比我还好呦。"

sys.path.insert(0, str(COSYVOICE_ROOT))
sys.path.insert(0, str(MATCHA_ROOT))

from cosyvoice.cli.cosyvoice import AutoModel  # noqa: E402


class SpeechRequest(BaseModel):
    model: str = Field(default="Fun-CosyVoice3-0.5B-2512")
    input: str = Field(min_length=1, max_length=1000)
    voice: str = Field(default="default-zh-female")
    response_format: Literal["wav"] = "wav"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    stream: bool = False


app = FastAPI(title="Local CosyVoice3 TTS Smoke Server")
model_started = time.perf_counter()
cosyvoice = AutoModel(model_dir=str(MODEL_DIR), load_trt=False, load_vllm=False, fp16=True)
model_load_ms = round((time.perf_counter() - model_started) * 1000)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "provider": "cosyvoice-http",
        "model": "Fun-CosyVoice3-0.5B-2512",
        "model_load_ms": model_load_ms,
    }


def _wav_bytes_from_array(audio: np.ndarray, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def _ndjson_event(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


@app.post("/v1/audio/speech")
def speech(request: SpeechRequest) -> Response:
    if request.model not in {"Fun-CosyVoice3-0.5B-2512", "test-model"}:
        raise HTTPException(status_code=400, detail="Unsupported model")
    started = time.perf_counter()
    if request.stream:
        return StreamingResponse(
            _speech_stream_events(request, started),
            media_type="application/x-ndjson",
        )
    print(f"speech request input_len={len(request.input)} input_repr={request.input[:30]!r} voice={request.voice!r} speed={request.speed}", flush=True)
    try:
        segments = split_tts_text(request.input.strip(), max_chars=36)
        print(f"speech segments count={len(segments)} lengths={[len(segment) for segment in segments]}", flush=True)
        speech_parts = []
        silence = np.zeros(round(cosyvoice.sample_rate * 0.12), dtype=np.float32)
        for index, segment in enumerate(segments, start=1):
            segment_started = time.perf_counter()
            chunks = list(
                cosyvoice.inference_zero_shot(
                    segment,
                    PROMPT_TEXT,
                    str(PROMPT_WAV),
                    stream=True,
                    speed=request.speed,
                )
            )
            if not chunks:
                print(f"CosyVoice returned no chunks for segment {index}", flush=True)
                continue
            segment_parts = [chunk["tts_speech"].squeeze(0).detach().cpu().numpy() for chunk in chunks]
            segment_speech = np.concatenate(segment_parts) if len(segment_parts) > 1 else segment_parts[0]
            speech_parts.append(segment_speech)
            if index < len(segments):
                speech_parts.append(silence)
            print(
                f"speech segment {index}/{len(segments)} chars={len(segment)} chunks={len(chunks)} elapsed_ms={round((time.perf_counter() - segment_started) * 1000)}",
                flush=True,
            )
        if not speech_parts:
            print("CosyVoice returned no chunks", flush=True)
            return JSONResponse(status_code=502, content={"error": "CosyVoice returned no audio"})
        speech_tensor = np.concatenate(speech_parts) if len(speech_parts) > 1 else speech_parts[0]
        audio_bytes = _wav_bytes_from_array(speech_tensor, cosyvoice.sample_rate)
        duration_ms = round(len(speech_tensor) / cosyvoice.sample_rate * 1000)
        inference_ms = round((time.perf_counter() - started) * 1000)
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={
                "X-Audio-Sample-Rate": str(cosyvoice.sample_rate),
                "X-Audio-Duration-Ms": str(duration_ms),
                "X-TTS-Inference-Ms": str(inference_ms),
            },
        )
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        return JSONResponse(
            status_code=502,
            content={
                "error": type(exc).__name__,
                "message": str(exc),
                "input_length": len(request.input),
                "voice": request.voice,
                "speed": request.speed,
            },
        )


def _speech_stream_events(request: SpeechRequest, started: float):
    try:
        segments = split_tts_text(request.input.strip(), max_chars=36)
        print(
            f"speech stream request input_len={len(request.input)} voice={request.voice!r} speed={request.speed} segments={len(segments)}",
            flush=True,
        )
        yield _ndjson_event({"type": "start", "provider": "cosyvoice-http", "model": request.model})
        emitted = 0
        for index, segment in enumerate(segments):
            segment_started = time.perf_counter()
            chunks = cosyvoice.inference_zero_shot(
                segment,
                PROMPT_TEXT,
                str(PROMPT_WAV),
                stream=True,
                speed=request.speed,
            )
            chunk_parts = []
            for chunk in chunks:
                chunk_parts.append(chunk["tts_speech"].squeeze(0).detach().cpu().numpy())
            if not chunk_parts:
                print(f"CosyVoice stream returned no chunks for segment {index}", flush=True)
                continue
            audio = np.concatenate(chunk_parts) if len(chunk_parts) > 1 else chunk_parts[0]
            audio_bytes = _wav_bytes_from_array(audio, cosyvoice.sample_rate)
            duration_ms = round(len(audio) / cosyvoice.sample_rate * 1000)
            elapsed_ms = round((time.perf_counter() - segment_started) * 1000)
            print(
                f"speech stream segment {index + 1}/{len(segments)} chars={len(segment)} duration_ms={duration_ms} elapsed_ms={elapsed_ms}",
                flush=True,
            )
            yield _ndjson_event({
                "type": "segment",
                "index": emitted,
                "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                "media_type": "audio/wav",
                "duration_ms": duration_ms,
                "sample_rate": cosyvoice.sample_rate,
            })
            emitted += 1
        if emitted == 0:
            yield _ndjson_event({"type": "error", "message": "CosyVoice returned no audio"})
            return
        total_ms = round((time.perf_counter() - started) * 1000)
        print(f"speech stream done segments={emitted} total_ms={total_ms}", flush=True)
        yield _ndjson_event({"type": "done", "segment_count": emitted})
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        yield _ndjson_event({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
