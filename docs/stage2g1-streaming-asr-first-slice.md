# Stage 2G-1 Streaming ASR First Vertical Slice Evidence

Status: COMPLETED on 2026-07-01.

## Scope

This slice adds the first fake/default streaming ASR vertical slice. During an explicit browser recording, the recorder can send a bounded MediaRecorder chunk to `POST /api/audio/transcriptions/stream`, consume NDJSON partial transcript events, and show a provisional realtime transcript preview before the final transcript enters the existing confirmation UI.

It preserves the existing non-streaming `POST /api/audio/transcriptions` fallback and the existing final confirmation / `发送并朗读` voice-turn flow.

It does not implement real FasterWhisper streaming ASR, WebSocket ASR, always-on microphone capture, wake-word listening, automatic spoken barge-in, LLM response streaming, final seamless low-gap audio playback, long-term memory, or emotion behavior.

## Implemented behavior

- Backend exposes `POST /api/audio/transcriptions/stream` as `application/x-ndjson`.
- Backend streaming ASR contract includes `start`, `partial`, `final`, `done`, and recoverable `error` events.
- Fake ASR provider emits deterministic partial transcript events followed by a final transcript result.
- `ASRService.transcribe_stream(...)` validates streaming events and reports unsupported streaming providers clearly.
- Frontend `streamTranscription(...)` parses chunked NDJSON and maps events to typed frontend events.
- Browser recorder starts `MediaRecorder` with a 1000 ms timeslice.
- While recording, a non-empty chunk can trigger a preview streaming-ASR request and update `partialTranscript`.
- The visible UI labels preview text as `实时转写预览` so it is not confused with the final `转写待确认` transcript.
- Stopping the recording still runs the authoritative final transcription path and puts the final transcript into the existing confirmation UI.
- Cancel/reset aborts preview requests and clears stale partial transcript state.

## Validation

| Command / Surface | Result |
|---|---|
| `npm --prefix frontend test -- src/hooks/useManualAudioRecorder.test.ts -t "exposes partial transcript while recording before stop"` | PASS — focused TDD regression for recording-time partial preview |
| `npm --prefix frontend test -- src/components/VoiceRecorder.test.tsx` | PASS — provisional preview UI renders |
| `npm --prefix frontend test -- src/hooks/useManualAudioRecorder.test.ts src/components/VoiceRecorder.test.tsx src/api/transcriptionStream.test.ts` | PASS — 3 files, 30 tests passed |
| `npm --prefix frontend test -- src/App.test.tsx` | PASS — 1 file, 21 tests passed |
| Browser smoke through `http://127.0.0.1:5173/` with fake backend and mocked microphone | PASS — realtime preview appeared during recording, cancel cleared it, console error count 0 |

## Browser smoke observations

Setup:

```powershell
$env:APP_ENV='development'
$env:DATABASE_URL='sqlite:///./data/stage2g1-smoke.db'
$env:LLM_PROVIDER='fake'
$env:TTS_PROVIDER='fake'
$env:ASR_PROVIDER='fake'
$env:FAKE_ASR_TEXT='语音转写文本'
python -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port 8000

$env:BACKEND_PROXY_TARGET='http://127.0.0.1:8000'
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173

node frontend/.claude-stage2g1-streaming-asr-smoke.mjs
```

Observed output:

```json
{
  "previewText": "实时转写预览：语音",
  "timeslice": 1000,
  "streamingRequests": 1,
  "previewAfterCancel": 0,
  "consoleErrors": []
}
```

Interpretation:

- The browser reached the actual React UI at `http://127.0.0.1:5173/`.
- The smoke clicked `新建会话` and `开始录音`.
- The mocked browser `MediaRecorder.start(...)` received `timeslice=1000`.
- A recording-time chunk caused a real request to `/api/audio/transcriptions/stream` through the running app surface.
- The UI displayed `实时转写预览：语音` while the recording session was active.
- The adjacent cancel probe cleared the preview before returning to the idle `开始录音` state.
- Browser console errors observed by Playwright: 0.

## Notes from external API checks

- MDN documents `MediaRecorder.start(timeslice)` as a way to receive `dataavailable` Blob chunks at approximate intervals; the timeslice is not exact and can be delayed by browser scheduling and pending tasks.
- `faster-whisper` core usage remains batch/file-oriented; real streaming ASR typically needs an additional streaming layer with sliding windows, context, de-duplication, and endpointing. This slice intentionally validates app-level streaming mechanics first.
- MDN Media Source Extensions are relevant for later final low-gap playback, but this ASR slice does not change TTS playback buffering.

## Limitations

- Real FasterWhisper streaming ASR is not implemented.
- Browser MediaRecorder chunks are used for preview plumbing; the final transcript after stop remains authoritative.
- The current preview request can return a deterministic fake partial for validation; it is not a quality benchmark for real ASR.
- Final seamless low-gap audio streaming is not implemented.
- Long-term memory and emotion state are not implemented.

## Historical next recommended task

At the time of Stage 2G-1, the recommended next minimum closed loop was Stage 2G-2 real streaming ASR feasibility. That task has since been completed and recorded in `docs/stage2g2-real-fasterwhisper-streaming-asr-feasibility.md`; this section is retained only as historical evidence.
