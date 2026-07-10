# Stage 2D VAD Auto-stop Design

Date: 2026-06-28
Status: Approved design for the next Stage 2 voice task.

## Context

Stage 2C is complete: the app can run a half-duplex voice turn through ASR, text chat, and TTS. The next Stage 2 task is 2D VAD auto-stop. This design stays inside Stage 2 voice functionality. It does not implement long-term memory, emotion, wake word detection, background listening, voice interruption, or streaming ASR/TTS.

Existing recorder behavior is centered in `frontend/src/hooks/useManualAudioRecorder.ts` and `frontend/src/components/VoiceRecorder.tsx`:

- The user must explicitly click `开始录音`.
- `MediaRecorder` captures browser audio.
- Manual `停止录音` and `取消录音` are available while recording.
- A 30-second max-duration timer already auto-stops as a safety cap.
- Stopping uploads the captured Blob to the existing ASR API.
- Recording/transcribing blocks TTS playback through the existing audio busy state.

## Goal

After the user explicitly starts recording, Silero/ONNX VAD detects speech end and automatically stops the existing recording flow. Manual stop and cancel remain available at all times. If VAD misfires, the user can cancel, retry, or re-record through existing recovery paths.

## Non-goals

- No background microphone listening before explicit user action.
- No wake word.
- No TTS interruption or barge-in; that remains Stage 2E.
- No streaming upload or streaming ASR; that remains Stage 2F.
- No backend VAD endpoint.
- No database schema changes.
- No memory or emotion behavior.
- No claim that the full app is real-time; this milestone only adds active-recording auto-stop.

## Chosen approach

Use `@ricky0123/vad-web` behind a project-owned adapter. The package wraps Silero VAD with ONNX Runtime Web and exposes browser speech-start/speech-end callbacks. The app should not call the package directly from UI components. Instead, add a narrow adapter that can be replaced by fake VAD in tests and by a different model later.

Reference checked during design: `ricky0123/vad` describes browser VAD using Silero VAD and ONNX Runtime Web, with asset paths for ONNX Runtime WASM and VAD model files.

## Architecture

### New units

1. `frontend/src/voiceActivity/types.ts`
   - Defines the project interface for VAD.
   - Keeps third-party types out of the recorder UI.

2. `frontend/src/voiceActivity/createSileroVad.ts`
   - Creates the real browser VAD instance using `@ricky0123/vad-web`.
   - Owns ONNX Runtime and VAD asset path configuration.
   - Maps third-party callbacks to project events.

3. `frontend/src/hooks/useVadAutoStop.ts`
   - Coordinates VAD lifecycle with recorder lifecycle.
   - Starts VAD only after the recorder has entered `recording`.
   - Calls the existing `stopRecording()` callback on speech end.
   - Stops and cleans VAD on manual stop, cancel, unmount, session reset, or recording completion.

4. Test fake VAD factory
   - Used by unit tests to simulate speech start, speech end, load failure, and cleanup.
   - Default automated tests must not download or load the real ONNX model.

### Existing units to modify

1. `useManualAudioRecorder`
   - Keep MediaRecorder as the source of uploaded audio.
   - Add minimal metadata/status needed by VAD coordination if necessary.
   - Do not embed Silero-specific logic in this hook.

2. `App.tsx`
   - Wire `useVadAutoStop` to the recorder.
   - Preserve existing voice-turn generation guards and audio mutex behavior.

3. `VoiceRecorder.tsx`
   - Display VAD state while recording.
   - Keep manual `停止录音` and `取消录音` visible.

## VAD lifecycle

1. User clicks `开始录音`.
2. App resets TTS playback as today.
3. Existing recorder requests microphone permission and starts `MediaRecorder`.
4. Once status is `recording`, `useVadAutoStop` starts the Silero/ONNX VAD.
5. VAD may report:
   - loading/ready
   - speech started
   - speech ended
   - error/unavailable
6. On speech ended, `useVadAutoStop` calls the same `stopRecording()` used by the manual button.
7. Existing stop handler builds the Blob, validates duration/size, uploads to ASR, and exposes the pending transcript.
8. If the user manually stops first, VAD is stopped and must not call stop again.
9. If the user cancels, VAD is stopped and the recording is discarded.
10. If VAD fails to load, recording continues manually and shows a non-blocking VAD warning.

## State and UI

Add a small VAD status string to the recorder UI while recording:

- `正在加载语音端点检测` while assets/model are loading.
- `正在监听语音结束` when VAD is active.
- `检测到语音结束，正在停止录音` after VAD triggers auto-stop.
- `语音端点检测不可用，请手动停止` for recoverable VAD load/runtime failure.

The manual stop and cancel buttons remain visible and enabled whenever current recorder state allows them. VAD status must not replace the elapsed timer.

## Configuration and assets

Add front-end configuration constants for:

- VAD enabled flag for local development and smoke runs.
- ONNX Runtime WASM base path.
- VAD model asset base path.
- Speech end threshold parameters only if exposed by the chosen package and needed after smoke testing.

Default automated tests should use fake VAD and should not require model assets. Production/dev local runs can enable real VAD after static assets are copied or served by Vite.

## Error handling

- If the browser does not support the required audio APIs, keep the existing recorder error behavior.
- If VAD assets fail to load, show a non-blocking VAD warning and keep manual recording working.
- If VAD fires speech end after manual stop/cancel, ignore it through generation guards or an active flag.
- If VAD fires too early, existing short-recording validation may reject the recording; user can retry.
- If VAD never fires, the user can manually stop and the existing 30-second cap still applies.

## Privacy and safety

- VAD starts only after explicit user click.
- If the chosen `MicVAD` implementation opens its own microphone stream, it is created only during active recording and is cleaned up with the recording generation.
- No microphone stream is opened before `开始录音`.
- No VAD audio chunks are saved by default.
- No raw audio is logged.
- No transcript or generated speech is written to VAD logs.
- This milestone must not clone or imitate any unauthorized voice.

## Testing plan

### Unit tests

- VAD is not started on hook mount.
- VAD starts only after recorder status becomes `recording`.
- Fake speech end calls `stopRecording()` once.
- Manual stop before speech end stops VAD and prevents duplicate stop.
- Cancel before speech end stops VAD and discards recording.
- VAD load failure shows a recoverable warning and does not block manual stop.
- Session reset/unmount cleans VAD resources.

### Integration/component tests

- Recording UI shows VAD status while recording.
- Manual stop and cancel remain visible while VAD is active.
- Auto-stop still leads to pending transcript confirmation through the existing ASR path.
- Voice-turn `发送并朗读` behavior remains unchanged after VAD-generated stop.

### Real smoke

Create an opt-in local smoke for real Silero/ONNX VAD that verifies:

- VAD assets load in the Vite-served app.
- VAD does not request or use the microphone before `开始录音`.
- After explicit recording start, speech-end detection can auto-stop a recording.
- Manual stop still works if VAD is disabled or unavailable.
- Browser console has no relevant errors.

The smoke may use a controlled browser microphone shim if it can exercise the real VAD model path. If that is not practical, the smoke should require a short manual utterance and record operator confirmation.

## Documentation updates after implementation

- Update `docs/stage2-voice-architecture.md` with the implemented 2D boundary.
- Add a `docs/stage2d-vad-auto-stop.md` evidence file or section.
- Update `README.md` only after validation passes.
- Update `CLAUDE.md` only after validation passes.

## Acceptance criteria

2D is complete only when all are true:

- VAD auto-stop works after explicit user start.
- Manual stop remains available and tested.
- Cancel/re-record recovery remains available and tested.
- VAD does not run as background listening before explicit user start.
- VAD failure does not break manual recording or text chat.
- Default automated tests do not require real model download or secrets.
- A real local VAD smoke records command/result evidence.
- No Stage 3 or Stage 4 behavior is introduced.

## Risks

| Risk | Mitigation |
|---|---|
| ONNX/WASM/model asset paths fail under Vite or packaged builds | Keep paths explicit and verify with opt-in smoke before marking complete |
| Real VAD adds noticeable first-use latency | Show loading status and keep manual stop available |
| VAD and MediaRecorder compete for microphone resources | Reuse explicit recording lifecycle; clean both in one generation-guarded path |
| VAD misdetects noise or silence | Keep manual stop/cancel/re-record and short-recording validation |
| Tests become slow or flaky due to real model loading | Use fake VAD in default tests; real VAD only in opt-in smoke |
| Scope drifts into interruption or streaming | Keep 2E/2F separate and reject background listening in this milestone |

## Alternatives considered

1. Browser energy-threshold VAD.
   - Smaller and dependency-free, but the user selected Silero/ONNX for a model-based VAD path.

2. Direct `onnxruntime-web` plus a Silero model.
   - More control, but it requires owning resampling, windows, thresholds, and state-machine details. This is too large for the first 2D slice.

3. Backend Silero VAD.
   - Easier to control model deployment, but it cannot stop an in-progress browser recording without streaming upload. That would pull 2F into 2D.

## Self-review

- Placeholder scan: no TODO/TBD placeholders remain.
- Internal consistency: design keeps MediaRecorder as the upload source and VAD as an auto-stop signal only.
- Scope check: focused on Stage 2D; does not implement memory, emotion, interruption, or streaming.
- Ambiguity check: VAD failure behavior, manual override, and acceptance criteria are explicit.
