# Stage 2D VAD Auto-stop Evidence

Status: COMPLETED on 2026-06-29.

## Scope

Stage 2D adds browser-side VAD auto-stop only after the user explicitly starts recording. It does not add background listening, wake word detection, voice interruption, streaming ASR/TTS, long-term memory, or emotion behavior.

The implementation keeps `MediaRecorder` as the source of uploaded ASR audio. VAD is only an auto-stop signal that calls the existing stop path.

## Validation

| Command | Result |
|---|---|
| `npm test -- --run src/hooks/useVadAutoStop.test.ts` | PASS — 6 fake VAD lifecycle tests passed |
| `npm test -- --run` | PASS — 7 frontend test files / 71 tests passed |
| `npm run typecheck` | PASS |
| `npm run build` | PASS |
| `REAL_VAD_HEADLESS=1 REAL_VAD_REQUIRE_AUTO_STOP=0 .\scripts\smoke_real_vad_ui.ps1` | PASS — browser loaded real VAD/ONNX assets and showed `正在监听语音结束`, 0 console errors |
| `.\scripts\smoke_real_vad_ui.ps1` | PASS — headed browser real VAD auto-stopped after speech end and reached pending transcript state, 0 console errors |
| Backend regression | SKIPPED — Stage 2D changed frontend VAD/UI/docs/scripts only; backend runtime files were not changed |

## Behavior verified

- VAD does not start on page load or before `开始录音`.
- VAD starts only during active recording.
- Real Silero/ONNX VAD assets load from local Vite-served files.
- VAD speech-end calls the existing recorder stop path.
- Manual `停止录音` remains available while VAD is active.
- `取消录音` remains available while VAD is active.
- VAD failure is recoverable and does not block manual recording.
- The existing ASR transcript confirmation path remains unchanged.
- No raw audio is saved or logged by the smoke scripts.

## Real smoke evidence

Latest headed smoke result from `frontend/test-results/real-vad-ui-smoke.json`:

```json
{
  "verdict": "PASS",
  "autoStopObserved": true,
  "requireAutoStop": true,
  "bodyContainsPendingTranscript": true,
  "consoleErrorCount": 0,
  "failedResponses": []
}
```

Smoke artifacts are generated locally and are not committed by default:

- `frontend/test-results/real-vad-ui-smoke.json`
- `frontend/test-results/real-vad-ui-smoke.png`

## Notes

The first smoke attempts exposed two issues in the smoke/app integration path:

1. The original VAD adapter imported `@ricky0123/vad-web` as an npm ESM module while ONNX Runtime assets were copied into Vite `public/`. Vite rejected `/vendor/onnxruntime/*.mjs?import` because files in `public/` cannot be imported as source modules. The adapter now follows the package README's browser pattern: it loads `/vendor/onnxruntime/ort.js` and `/vendor/vad/bundle.min.js` as scripts, then uses `window.vad.MicVAD` through the project-owned adapter boundary.
2. The smoke clicked `开始录音` before session message loading had finished. The smoke now waits until `处理中……` is hidden and the record button is enabled.

These fixes stay inside Stage 2 voice functionality and do not implement memory or emotion behavior.
