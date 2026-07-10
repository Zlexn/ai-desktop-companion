from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time
from dataclasses import dataclass

import httpx


@dataclass
class SegmentStats:
    index: int
    bytes_len: int
    duration_ms: int
    sample_rate: int
    received_ms: int


async def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test backend streaming TTS with CosyVoice.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/audio/speech/stream")
    parser.add_argument("--text", default="这是一个本地流式语音合成测试。")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    started = time.perf_counter()
    first_segment_ms: int | None = None
    done_ms: int | None = None
    provider = None
    model = None
    segments: list[SegmentStats] = []

    async with httpx.AsyncClient(timeout=args.timeout, trust_env=False) as client:
        async with client.stream("POST", args.url, json={"text": args.text, "voice_id": None, "speed": 1.0}) as response:
            response.raise_for_status()
            pending = ""
            async for chunk in response.aiter_text():
                pending += chunk
                lines = pending.split("\n")
                pending = lines.pop() or ""
                for line in lines:
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    elapsed_ms = round((time.perf_counter() - started) * 1000)
                    if event["type"] == "start":
                        provider = event.get("provider")
                        model = event.get("model")
                    elif event["type"] == "segment":
                        audio_bytes = base64.b64decode(event["audio_base64"])
                        if first_segment_ms is None:
                            first_segment_ms = elapsed_ms
                        segments.append(SegmentStats(
                            index=int(event["index"]),
                            bytes_len=len(audio_bytes),
                            duration_ms=int(event["duration_ms"]),
                            sample_rate=int(event["sample_rate"]),
                            received_ms=elapsed_ms,
                        ))
                    elif event["type"] == "done":
                        done_ms = elapsed_ms
                    elif event["type"] == "error":
                        raise RuntimeError(str(event.get("message") or "stream returned error"))

    result = {
        "status": "PASS" if segments else "FAIL",
        "provider": provider,
        "model": model,
        "segment_count": len(segments),
        "first_segment_ms": first_segment_ms,
        "done_ms": done_ms,
        "segments": [segment.__dict__ for segment in segments],
        "text_length": len(args.text),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if segments else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
