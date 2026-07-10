# Stage 2G-2 Real FasterWhisper Streaming ASR Feasibility Evidence

Status: COMPLETED on 2026-07-01.

## Scope

This slice adds opt-in real FasterWhisper streaming-ASR feasibility through the existing `POST /api/audio/transcriptions/stream` NDJSON contract.

It preserves the stable batch `POST /api/audio/transcriptions` endpoint and the fake/default streaming ASR path. It does not implement production-grade simultaneous ASR, WebSockets, always-on listening, automatic spoken barge-in, final seamless low-gap audio, long-term memory, or emotion state.

## Implemented behavior

- Added explicit FasterWhisper streaming feasibility settings, disabled by default:
  - `ASR_FASTER_WHISPER_STREAMING_ENABLED=false`
  - `ASR_FASTER_WHISPER_STREAMING_WINDOW_MS=3000`
  - `ASR_FASTER_WHISPER_STREAMING_STEP_MS=1000`
  - `ASR_FASTER_WHISPER_STREAMING_MIN_PARTIAL_CHARS=1`
  - `ASR_FASTER_WHISPER_STREAMING_MAX_PARTIALS=8`
- `FasterWhisperASRProvider` now accepts those settings through the ASR factory.
- `FasterWhisperASRProvider.transcribe_stream(...)` implements a provider-local feasibility path:
  - ordered chunks are accumulated;
  - cumulative audio is decoded through the existing local FasterWhisper batch path;
  - changed partial text is emitted as `TranscriptionPartialEvent`;
  - a final full decode emits `TranscriptionFinalEvent`;
  - temporary inference files are deleted by the existing `_transcribe_sync(...)` cleanup.
- Partial cumulative decode failures are skipped so non-decodable early container fragments do not abort the whole stream; final full decode remains authoritative.
- Partial events carry provider/model metadata so `/api/audio/transcriptions/stream` can emit a correct `start` event for real provider streams.
- Added a local smoke script: `scripts/smoke_faster_whisper_streaming_asr.py`.

## Validation

| Command / Surface | Result |
|---|---|
| `python -m pytest backend/tests/test_config.py -k "faster_whisper_streaming" -v` | PASS — 3 passed |
| `python -m pytest backend/tests/test_asr_factory.py::test_asr_factory_passes_faster_whisper_streaming_settings -v` | PASS — 1 passed |
| `python -m pytest backend/tests/test_faster_whisper_streaming_asr_provider.py -v` | PASS — 5 passed |
| `python -m pytest backend/tests/test_faster_whisper_asr_provider.py -v` | PASS — 5 passed |
| `python -m pytest backend/tests/test_api_audio_transcriptions_streaming.py backend/tests/test_api_audio_transcriptions_streaming_faster_whisper.py -v` | PASS — 3 passed |
| `python -m pytest backend/tests/test_config.py backend/tests/test_asr_factory.py backend/tests/test_faster_whisper_asr_provider.py backend/tests/test_faster_whisper_streaming_asr_provider.py backend/tests/test_asr_streaming.py backend/tests/test_api_audio_transcriptions_streaming.py backend/tests/test_api_audio_transcriptions_streaming_faster_whisper.py -v` | PASS — 49 passed |
| `npm --prefix frontend test -- src/api/transcriptionStream.test.ts src/hooks/useManualAudioRecorder.test.ts src/components/VoiceRecorder.test.tsx src/App.test.tsx` | PASS — 4 files, 51 tests passed |
| `npm --prefix frontend run typecheck` | PASS — `tsc -b` exited 0 |
| `npm --prefix frontend run build` | PASS — Vite built 34 modules |
| `python -m pytest backend/tests -v` | PASS — 233 passed |
| Real API smoke: `python scripts/smoke_faster_whisper_streaming_asr.py --url http://127.0.0.1:8000/api/audio/transcriptions/stream --audio asr-benchmark-corpus/clean/P001.m4a --language zh --chunk-bytes 86000` | PASS — HTTP 200 NDJSON, 1 partial, 1 final |
| Disabled streaming probe through same API surface | PASS — HTTP 502 JSON with `asr_unavailable` and message indicating FasterWhisper streaming is not enabled |

## Real smoke observations

Setup:

```powershell
$env:APP_ENV='development'
$env:DATABASE_URL='sqlite:///./data/stage2g2-smoke.db'
$env:LLM_PROVIDER='fake'
$env:TTS_PROVIDER='fake'
$env:ASR_PROVIDER='faster-whisper'
$env:ASR_FASTER_WHISPER_MODEL_PATH='C:\Users\张乐航\.cache\huggingface\hub\models--Systran--faster-whisper-medium\snapshots\08e178d48790749d25932bbc082711ddcfdfbc4f'
$env:ASR_FASTER_WHISPER_MODEL_NAME='medium'
$env:ASR_FASTER_WHISPER_MODEL_REVISION='08e178d48790749d25932bbc082711ddcfdfbc4f'
$env:ASR_FASTER_WHISPER_DEVICE='cuda'
$env:ASR_FASTER_WHISPER_COMPUTE_TYPE='float16'
$env:ASR_FASTER_WHISPER_BEAM_SIZE='1'
$env:ASR_FASTER_WHISPER_STREAMING_ENABLED='true'
python -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Smoke output:

```text
HTTP 200 application/x-ndjson
{"type": "start", "provider": "faster-whisper", "model": "medium@08e178d48790749d25932bbc082711ddcfdfbc4f", "elapsed_ms": 7117}
{"type": "partial", "index": 0, "text": "<Chinese transcript displayed as mojibake in this PowerShell capture>", "is_final": false, "audio_ms": null, "elapsed_ms": 7117}
{"type": "final", "text": "<Chinese transcript displayed as mojibake in this PowerShell capture>", "detected_language": "zh", "duration_ms": 6677, "provider": "faster-whisper", "model": "medium@08e178d48790749d25932bbc082711ddcfdfbc4f", "inference_ms": 7521, "elapsed_ms": 14642}
{"type": "done", "elapsed_ms": 14642}
SUMMARY {"audio": "asr-benchmark-corpus\\clean\\P001.m4a", "chunk_count": 2, "chunk_bytes": 86000, "partial_count": 1, "first_partial_ms": 7117, "final_ms": 14642, "final_text": "<Chinese transcript displayed as mojibake in this PowerShell capture>"}
```

Observed metrics:

- Provider: `faster-whisper`
- Model: `medium@08e178d48790749d25932bbc082711ddcfdfbc4f`
- Device / compute type: `cuda` / `float16`
- Fixture: `asr-benchmark-corpus/clean/P001.m4a`
- Fixture bytes: 171837
- Chunk bytes: 86000
- Chunk count: 2
- Partial count: 1
- First partial latency: 7117 ms
- Final latency: 14642 ms
- Final event `duration_ms`: 6677
- Final event `inference_ms`: 7521
- Terminal note: Chinese transcript text appeared as mojibake in the PowerShell capture because of console encoding, but the API emitted structured JSON events with expected provider/model/partial/final/done fields.

## Disabled streaming probe

With `ASR_FASTER_WHISPER_STREAMING_ENABLED=false`, the same API surface returned:

```text
HTTP 502 application/json
{"error":{"code":"asr_unavailable","message":"<message displayed as mojibake; original message indicates FasterWhisper streaming is not enabled>"}}
```

This confirms real-provider streaming remains explicit opt-in and disabled by default.

## Root-cause finding during runtime smoke

The first real smoke returned HTTP 502. Backend logs showed PyAV raised `InvalidDataError` when decoding the first byte-sliced `.m4a` partial window:

```text
av.error.InvalidDataError: Invalid data found when processing input: temporary .m4a
```

Root cause: early chunks of an MP4/M4A container are not guaranteed to be independently decodable. The fix was to skip failed partial-window decodes and continue accumulating audio; the final full decode remains authoritative.

## Limitations

- This implementation repeatedly decodes cumulative audio windows; it is a feasibility layer, not final production streaming ASR.
- Partial latency was about 7.1 seconds for the P001 fixture with the current local model/settings, so this is not yet seamless realtime conversation.
- Partial text can be revised and remains provisional.
- Terminal transcript display in this smoke was affected by PowerShell encoding; future smoke scripts should force UTF-8 output if exact transcript text evidence is needed.
- Final seamless low-gap audio, long-term memory, and emotion state remain unimplemented.

## Historical next recommended task

At the time of Stage 2G-2, the recommended next minimum closed loop was Stage 2H low-gap audio playback. That task has since been completed and recorded in `docs/stage2h-low-gap-streaming-audio.md`; this section is retained only as historical evidence.
