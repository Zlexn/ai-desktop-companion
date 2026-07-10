from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test FasterWhisper streaming ASR endpoint.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/audio/transcriptions/stream")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--chunk-bytes", type=int, default=256_000)
    return parser.parse_args()


def chunks(data: bytes, size: int) -> list[bytes]:
    return [data[index:index + size] for index in range(0, len(data), size) if data[index:index + size]]


def main() -> int:
    args = parse_args()
    audio_path = Path(args.audio)
    data = audio_path.read_bytes()
    audio_chunks = chunks(data, args.chunk_bytes)
    files = [
        ("chunks", (f"chunk-{index}.m4a", chunk, "audio/mp4"))
        for index, chunk in enumerate(audio_chunks)
    ]
    started = time.perf_counter()
    first_partial_ms: int | None = None
    final_ms: int | None = None
    events: list[dict[str, object]] = []

    with requests.post(args.url, files=files, data={"language": args.language}, stream=True, timeout=120) as response:
        print(f"HTTP {response.status_code} {response.headers.get('content-type', '')}")
        response.raise_for_status()
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            event = json.loads(raw_line)
            event["elapsed_ms"] = elapsed_ms
            events.append(event)
            if event.get("type") == "partial" and first_partial_ms is None:
                first_partial_ms = elapsed_ms
            if event.get("type") == "final" and final_ms is None:
                final_ms = elapsed_ms
            print(json.dumps(event, ensure_ascii=False))

    partials = [event for event in events if event.get("type") == "partial"]
    finals = [event for event in events if event.get("type") == "final"]
    summary = {
        "audio": str(audio_path),
        "chunk_count": len(audio_chunks),
        "chunk_bytes": args.chunk_bytes,
        "partial_count": len(partials),
        "first_partial_ms": first_partial_ms,
        "final_ms": final_ms,
        "final_text": finals[-1].get("text") if finals else None,
    }
    print("SUMMARY " + json.dumps(summary, ensure_ascii=False))
    return 0 if partials and finals else 1


if __name__ == "__main__":
    raise SystemExit(main())
