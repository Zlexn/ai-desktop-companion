# 2B-3 Browser Manual Recording UI Design

> Status: design only. This document does not implement code, install dependencies, access the microphone, or call any real ASR/LLM API.
>
> Current phase: Stage 2 — voice features. 2B-1 Backend ASR Foundation: COMPLETED. 2B-2 Multipart Transcription API: COMPLETED. 2B-3 Browser Manual Recording UI: COMPLETED.
>
> Scope lock: this design must not implement real ASR, VAD, continuous listening, wake word, auto-send, streaming recognition, TTS interruption, simultaneous record+playback, device picker, volume visualization, long-term memory, or emotion state.

## 1. Goal and non-goals

### Goal

Milestone 2B-3 completes the Fake ASR vertical slice by adding browser-side manual recording, multipart upload to the existing `POST /api/audio/transcriptions`, and transcript insertion into the existing input box:

```text
user click "开始录音" → getUserMedia permission → MediaRecorder → user click "停止录音"
→ Blob → POST /api/audio/transcriptions (FormData file + language)
→ Fake ASR transcript → filled into MessageInput → user manually sends
```

### Product boundary

1. User clicks "开始录音".
2. Browser requests microphone permission exactly at that moment (not on page load).
3. On permission granted, recording begins with explicit recording indicator.
4. User clicks "停止录音", or 30-second max timer auto-stops.
5. Blob uploads to existing `POST /api/audio/transcriptions`.
6. Fake ASR returns deterministic test transcription.
7. Transcript enters the existing input box (with conflict handling).
8. No auto-send. User must click "发送" manually.
9. Existing `ChatService` and SQLite message persistence remain unchanged.
10. Existing `/api/audio/speech` and TTS playback remain functional.

### Non-goals

- Real ASR, model download, GPU use, faster-whisper, CTranslate2, torch, FFmpeg.
- VAD, continuous listening, wake word, background recording.
- Auto-send transcript, auto-create chat messages.
- Streaming recognition, streaming TTS.
- TTS interruption (speech-stops-playback).
- Simultaneous recording and playback (half-duplex in 2C only).
- Device selector, volume waveform, gain visualization.
- Raw audio persistence (localStorage, IndexedDB, SQLite).
- Long-term memory, emotion system.

## 2. Component and Hook structure

### New files

```
frontend/src/hooks/useManualAudioRecorder.ts   # recorder state machine + cleanup
frontend/src/components/VoiceRecorder.tsx      # UI controls
frontend/src/api/client.ts                     # + transcribeAudio method
frontend/src/api/types.ts                      # + TranscriptionResult, VoiceInputError types
```

### Modified files

```
frontend/src/App.tsx                           # wire recorder hook, TTS stop on record
frontend/src/components/ChatLayout.tsx          # pass recorder props
frontend/src/components/MessageInput.tsx        # controlled draft injection support
```

### Hook: useManualAudioRecorder

```typescript
// frontend/src/hooks/useManualAudioRecorder.ts

type RecordingStatus =
  | "idle"
  | "requesting_permission"
  | "recording"
  | "stopping"
  | "uploading"
  | "transcribing"
  | "ready"
  | "error";

interface RecordedAudio {
  blob: Blob;
  mediaType: string;
  durationMs: number;
}

interface UseManualAudioRecorderResult {
  status: RecordingStatus;
  elapsedMs: number;
  transcript: string | null;
  error: VoiceInputError | null;
  startRecording(): Promise<void>;
  stopRecording(): Promise<void>;
  cancelRecording(): void;
  discardTranscript(): void;
  onStopTTSForRecording(): void;    // callback: called before startRecording
  onPlaybackBlocked(): boolean;     // query: true when recording/uploading/transcribing
}
```

Internal refs:
- `streamRef: MutableRefObject<MediaStream | null>`
- `recorderRef: MutableRefObject<MediaRecorder | null>`
- `chunksRef: MutableRefObject<Blob[]>`
- `abortControllerRef: MutableRefObject<AbortController | null>`
- `timerRef: MutableRefObject<number | null>` (monotonic elapsed)
- `maxTimerRef: MutableRefObject<number | null>` (setTimeout for 30 s cap)
- `mountedRef: MutableRefObject<boolean>` (prevents state updates after unmount)
- `draftSnapshotRef: MutableRefObject<string>` (input content at record start)

Design rules:
1. MediaStream, MediaRecorder, chunks, timers, AbortController live in refs — never in React state.
2. Do not put MediaStream or raw Blob into global state, localStorage, IndexedDB, or SQLite.
3. On unmount: stop recorder, stop all tracks, cancel upload.
4. On session switch: same cleanup as unmount.
5. Prevent duplicate `MediaRecorder` — startRecording is blocked if status is not `idle` or `error`.
6. All async callbacks check `mountedRef.current` before calling `setState`.
7. AbortController prevents stale upload responses from overwriting newer recordings.
8. Old abort errors are silently ignored (they carry `AbortError` DOMException).

### Component: VoiceRecorder

```typescript
// frontend/src/components/VoiceRecorder.tsx

interface VoiceRecorderProps {
  recorder: UseManualAudioRecorderResult;
  onTranscriptReady: (text: string) => void;   // called by parent to fill input
  disabled: boolean;                            // e.g. when sending a chat message
}
```

Renders:
- idle: `<button aria-label="开始录音">开始录音</button>`
- requesting_permission: disabled button + "正在请求麦克风权限"
- recording: red dot indicator, elapsed seconds, "停止录音", "取消"
- stopping: "正在结束录音" (no click targets)
- uploading / transcribing: "正在转写" + "取消转写"
- ready: no visible controls (transcript in input box, user edits/sends)
- error: error message + "重试" + text input remains available

Accessibility:
- All buttons use `<button>` elements.
- `aria-label` present on every control.
- `aria-live="polite"` region announces status transitions.
- Recording state not indicated by color alone (includes text + icon).
- No fake volume meter or fake waveform is displayed.

## 3. State machine

### States

| State | Meaning | Entry actions | Exit actions |
|---|---|---|---|
| `idle` | No recording active | — | — |
| `requesting_permission` | `getUserMedia` in flight | set status, disable duplicate clicks | — |
| `recording` | MediaRecorder collecting | start monotonic timer, start 30 s max timer, snapshot input draft | — |
| `stopping` | `recorder.stop()` called, waiting for `stop` event | set status, disable all controls | — |
| `uploading` | FormData being sent to `/api/audio/transcriptions` | build FormData, call apiClient.transcribeAudio | — |
| `transcribing` | Server processing upload | — | — |
| `ready` | Transcript available | call `onTranscriptReady(text)` | — |
| `error` | Recoverable failure | set error message | — |

### Transitions

```
idle
  → startRecording() → requesting_permission

requesting_permission
  → getUserMedia success → recording
  → getUserMedia deny/error → error

recording
  → stopRecording() → stopping
  → cancelRecording() → idle (discard chunks, stop tracks)
  → maxTimer 30 s → stopping (auto-stop, only once)
  → track ended (browser/device) → error
  → MediaRecorder error → error

stopping
  → stop event + Blob present → uploading
  → stop event + empty Blob → error

uploading
  → fetch 200 → transcribing
  → fetch error / abort → error

transcribing
  → API success → ready
  → API error → error

ready
  → user manually sends text (existing MessageInput flow, resets to idle)
  → re-record (startRecording) → requesting_permission
  → discardTranscript() → idle

error
  → dismiss / startRecording → requesting_permission
  → dismiss → idle
```

### Concurrent controls guard

- startRecording blocked unless status is `idle` or `error`.
- stopRecording blocked unless status is `recording`.
- cancelRecording works from `recording`, `stopping`, `uploading`, `transcribing`.
- Duplicate rapid clicks ignored by status gate + ref check.

## 4. getUserMedia permission flow

### Call timing

`getUserMedia` is called **only** inside `startRecording()`, after an explicit user click. Page load and React render must never call it.

### Constraints

```typescript
const stream = await navigator.mediaDevices.getUserMedia({
  audio: {
    echoCancellation: { ideal: true },
    noiseSuppression: { ideal: true },
    autoGainControl: { ideal: true },
  },
});
```

- Use `ideal` constraints only — never `exact`.
- Do not enumerate devices before requesting permission.
- No device selection UI in 2B-3.
- `navigator.mediaDevices` absent → safe degrade: `error` with `microphone_unsupported`.
- `MediaRecorder` absent → safe degrade: `error` with `microphone_unsupported`.

### Error mapping

| DOMException name | VoiceInputError code | User message |
|---|---|---|
| `NotAllowedError` | `microphone_permission_denied` | 未获得麦克风权限，请在浏览器设置中允许后重试。 |
| `NotFoundError` | `microphone_not_found` | 未检测到麦克风设备。 |
| `NotReadableError` | `microphone_in_use_or_unavailable` | 麦克风被其他应用占用或不可用。 |
| `SecurityError` | `microphone_security_error` | 当前页面不支持麦克风（需要 HTTPS 或 localhost）。 |
| `AbortError` | `microphone_start_aborted` | 录音请求已取消。 |
| `TypeError` | `microphone_unsupported_context` | 当前浏览器环境不支持录音功能。 |
| Other | `microphone_unknown_error` | 麦克风无法启动，请检查设备后重试。 |

Error messages must not include browser internal stack traces.

### Edge: track ended prematurely

Listen to `track.onended` on each `MediaStreamTrack`. If a track ends while status is `recording`, transition to `error` with `microphone_device_disconnected`.

### Edge: late getUserMedia resolution

`getUserMedia` may take a long time to resolve (user hesitates on permission prompt) or may resolve after the user has navigated away, switched sessions, or cancelled. The hook must handle this:

1. Increment a `generationRef` before calling `getUserMedia`.
2. When `getUserMedia` resolves, check `generationRef` against the current generation.
3. If generations differ (cancelled, session switch, unmount):
   - Immediately stop all tracks in the resolved stream.
   - Do NOT create a `MediaRecorder`.
   - Do NOT update UI state.
4. The stale stream must not leak — every track must be stopped.

## 5. MediaRecorder lifecycle

### MIME selection

Candidate order:
1. `audio/webm;codecs=opus`
2. `audio/webm`
3. `audio/mp4`

Algorithm:
1. For each candidate, call `MediaRecorder.isTypeSupported(candidate)`.
2. Use the first that returns `true`.
3. Create `new MediaRecorder(stream, { mimeType: chosen })`.
4. After construction, read `recorder.mimeType` as the authoritative MIME for upload.
5. If all three candidates fail, do **not** create a `MediaRecorder` with an unpredictable browser default — instead, set `error` with `microphone_unsupported_format`.

**`isTypeSupported` fragility:** `isTypeSupported("audio/webm;codecs=opus")` returning `true` does not guarantee the `MediaRecorder` constructor will succeed. Resource limits, codec initialization failures, or platform-specific restrictions may still cause the constructor or `start()` to throw. The hook must wrap both `new MediaRecorder(...)` and `recorder.start()` in try/catch and transition to `error` on failure.

Backend-only check: if the final `recorder.mimeType` (after possible browser transformation) does not match a backend-supported family, the frontend should **not** attempt the upload and should show `microphone_unsupported_format`. However, the backend `ASRService` will independently validate signature against declared MIME regardless.

### Blob collection and stop sequence

1. `dataavailable` handler: push `event.data` to `chunksRef` only if `event.data.size > 0`.
2. `stop` handler:
   a. Merge chunks into a single `Blob` using the actual `recorder.mimeType`.
   b. If merged `Blob.size === 0`: set error, do not upload.
   c. If merged `Blob.size` > `MAX_BLOB_SIZE` (10 MiB): set error, do not upload.
   d. Stop all `MediaStreamTrack`s.
   e. Clear `streamRef`, `recorderRef`, `chunksRef`.
   f. Call upload.
3. `error` handler: transition to `error`, stop all tracks, clean up refs.
4. User `cancelRecording()`: `recorder.stop()` + discard chunks + stop tracks.

### Timer

- Elapsed time: `performance.now()` delta from `recording` entry to stop event. Rounded to integer ms for UI.
- 30 s max timer: `setTimeout` created at `recording` entry. On fire: if status is still `recording`, call `recorder.stop()` (triggers auto-stop). Use a guard to prevent double-firing.
- Do not use `dataavailable` event timing to infer real recording duration.

### Blob size guard

If merged Blob exceeds 10 MiB (10,485,760 bytes):
- Do not upload.
- Set error: `recording_too_large` (friendly message: "录音文件过大，请缩短录音时间后重试。").
- Backend independently enforces `ASR_MAX_UPLOAD_BYTES` as a second layer.

## 6. Duration and file size limits

| Limit | Value | Enforced by | Hard/soft | Notes |
|---|---|---|---|---|
| Max recording | 30 s | Frontend max timer auto-stop | Hard (frontend operational cap) | Backend does **not** currently validate actual audio duration; 30 s is a frontend UX guard only. Server-side duration validation requires future reliable decoder/prober. |
| Min recording | 300 ms | Frontend elapsed monotonic-time check | Soft UX guard | Backend independently validates upload size but not decoded duration. |
| Max upload size | 10 MiB | Frontend Blob check + backend `ASR_MAX_UPLOAD_BYTES` | Hard (dual layer) | Backend independently enforces `ASR_MAX_UPLOAD_BYTES`. |
| Empty Blob | — | Frontend: don't upload | Hard | — |

**Backend current capabilities (2B-2):**
- Validates upload byte size against `ASR_MAX_UPLOAD_BYTES`.
- Validates declared MIME against allowlist.
- Validates basic container signature (WebM EBML, MP4 ftyp, WAV RIFF/WAVE).
- Does **not** decode actual audio duration, detect silence, or verify media validity beyond container headers.
- `TranscriptionResult.duration_ms` is `null` from Fake ASR.

**Implication for frontend:**
- 30 s max timer is an operational UX cap, not a verified server-side audio duration limit.
- Do not claim in documentation or UI that the server has validated a 30-second real audio duration.
- `durationMs` from `performance.now()` is for UI display only; never sent to backend as trusted audio duration.
- Fake ASR ignores actual audio content; the transcript is deterministic fake text.

## 7. Input box conflict strategy

### Problem

User may have typed text before or during recording. The transcript must not silently overwrite their work.

### Design

`MessageInput` remains the **sole owner** of the input draft (`content` via `useState`). No second draft state exists in `App`, the recorder hook, or `VoiceRecorder`.

To support transcript insertion without duplicating ownership:

**Approach (selected):** `MessageInput` receives an optional `pendingTranscript` prop. When non-null, `MessageInput` shows a "转写待确认" area above the textarea with Replace / Append / Discard buttons. Only on explicit user choice is the locally-owned `content` state modified.

**Rejected:** Lifting `content` from `MessageInput` to `App` — this would spread draft ownership and complicate the existing send path for no clear benefit in 2B-3.

**Rules:**
- `MessageInput` is the single source of truth for the current draft text.
- `useManualAudioRecorder` stores no chat draft text — it only holds `pendingTranscript` (the raw ASR result not yet applied).
- `App` does not maintain a parallel `draft` state.
- The recorder hook captures `draftSnapshot` at record start only for conflict detection — this is a readonly snapshot, not a second draft.

### Conflict flow

1. At `startRecording()`, the recorder hook captures a readonly `draftSnapshot` of the current input value.
2. When transcript arrives (`transcribing → ready`):
   - If input is still empty/whitespace: insert directly (call `onTranscriptReady` → `MessageInput.setContent(transcript)`).
   - If input content is unchanged from `draftSnapshot` AND `draftSnapshot` was empty: insert directly.
   - If input contains user content (different from `draftSnapshot` or `draftSnapshot` was non-empty): set `pendingTranscript` in `MessageInput` → show Replace / Append / Discard.
3. Replace: `MessageInput.setContent(transcript)` — single owner mutation.
4. Append: `MessageInput.setContent(prev => prev + "\n" + transcript)`.
5. Discard: clear `pendingTranscript`, keep existing draft unchanged.
6. In all cases: **never auto-send**.

### Placement

`App.tsx` owns the recorder hook instance and wires `onTranscriptReady` callback. `VoiceRecorder` passes the transcript up via `onTranscriptReady`. `MessageInput` receives `pendingTranscript` prop and manages all three conflict actions internally. No parallel draft state exists outside `MessageInput`.

## 8. TTS mutual exclusion strategy

2B-3 enforces minimal recording/playback mutual exclusion (not full 2C half-duplex):

| Trigger | Action |
|---|---|
| `startRecording()` called | Call `audioController.stop()` (stop current playback) |
| During `recording` / `uploading` / `transcribing` | Assistant "播放" buttons disabled via `playbackBlocked` flag |
| TTS `synthesizing` in progress | `startRecording()` aborts current TTS fetch via AbortController, then proceeds |

Implementation:
- `useManualAudioRecorder` exposes `onStopTTSForRecording: () => void` — called by `App` at start of `startRecording()`.
- `useManualAudioRecorder` exposes `isPlaybackBlocked: boolean` — `true` when `status` is `recording`, `stopping`, `uploading`, or `transcribing`. Passed to `MessageList` → `AssistantAudioControls`.
- `AssistantAudioControls` `disabled` prop set to `isPlaybackBlocked || loading`.

After recording completes (success or error), `isPlaybackBlocked` returns to `false`.

This is NOT the 2C full half-duplex state machine; it only ensures record/playback don't collide within 2B scope.

## 9. API client extension

### New types

```typescript
// frontend/src/api/types.ts

export interface TranscriptionResult {
  text: string;
  detected_language: string | null;
  duration_ms: number | null;
  provider: string;
  model: string;
  inference_ms: number;
}

export interface VoiceInputError {
  code: string;        // e.g. "microphone_permission_denied"
  message: string;     // user-facing message
}
```

### New method

```typescript
// frontend/src/api/client.ts (add to apiClient)

transcribeAudio(
  audio: Blob,
  options?: { language?: string; signal?: AbortSignal }
): Promise<TranscriptionResult>
```

Implementation:
1. Construct `FormData`.
2. `formData.append("file", audio, filename)` where `filename` is mapped from `audio.type`:
   - `audio/webm` → `recording.webm`
   - `audio/mp4` → `recording.mp4`
   - `audio/wav` → `recording.wav`
   - unknown → `recording.bin` (backend rejects by signature anyway)
3. `formData.append("language", options?.language ?? "zh")`.
4. `fetch("/api/audio/transcriptions", { method: "POST", body: formData, signal: options?.signal })`.
5. Do NOT set `Content-Type` header — browser sets `multipart/form-data; boundary=...` automatically.
6. On non-ok: throw error parsed via existing `responseErrorMessage()`.
7. On ok: parse JSON, validate `TranscriptionResult` fields (at minimum `text` and `provider` must be present).
8. Return `TranscriptionResult`.

Rules:
- File extension only for protocol compatibility, not for format detection.
- Do not log Blob content, full transcript, or FormData.
- `provider` and `model` are retained in the result object but not displayed to the user in 2B-3.

## 10. Cleanup and cancellation

### Session switch

```typescript
// In App.handleSelectSession:
audioController.reset();
recorder.cancelRecording();   // stops tracks, cancels upload, clears pending transcript
```

### Session delete

Same as session switch.

### Page unload

`useEffect` cleanup in `useManualAudioRecorder`:
```typescript
useEffect(() => {
  mountedRef.current = true;
  return () => {
    mountedRef.current = false;
    // stop recorder if active
    // stop all tracks
    // abort upload
    // clear timers
  };
}, []);
```

### Cancel during recording

- Call `recorder.stop()`.
- In `stop` event handler, check cancel flag.
- Discard chunks (don't build Blob).
- Stop all tracks.
- Return to `idle`.

### Cancel during upload/transcription

- `abortController.abort()`.
- Ignore subsequent responses (check `signal.aborted` before processing).
- Do not modify input box on aborted responses.
- Return to `idle`.

## 11. Test plan — unit and component

### Hook tests (useManualAudioRecorder.test.ts)

Mocked APIs (unit/component tests):
- `navigator.mediaDevices.getUserMedia`
- `MediaRecorder` constructor
- `MediaStream`
- `MediaStreamTrack` (with `stop()`)

Do NOT mock at global level:
- `Blob` — use jsdom native `Blob`.
- `FormData` — use jsdom native `FormData` (verify `append` calls through inspection or `formData.get("file")` returning the File).

Coverage:

1. Page load does not call `getUserMedia`.
2. `startRecording()` calls `getUserMedia` exactly once.
3. Permission denied → error `microphone_permission_denied`.
4. `NotFoundError` → error `microphone_not_found`.
5. `MediaRecorder` unsupported → error `microphone_unsupported`.
6. MIME candidate selection order: `webm;codecs=opus` → `webm` → `mp4`.
7. `MediaRecorder` created with first supported MIME.
8. `recorder.mimeType` used as upload Blob type.
9. `dataavailable` chunks with `size > 0` collected.
10. Zero-size chunks ignored.
11. Empty merged Blob → not uploaded, error set.
12. `< 300 ms` soft rejection.
13. 30 s max timer fires → `recorder.stop()` called.
14. Auto-stop only fires once (guard flag).
15. Tracks stopped after normal completion.
16. Tracks stopped after cancel.
17. Tracks stopped after error.
18. Tracks stopped after unmount.
19. `cancelRecording()` during recording → tracks stopped, chunks discarded, `idle`.
20. Double `startRecording()` prevented (status gate).
21. `startRecording()` aborts TTS via callback.
22. `isPlaybackBlocked` true during recording/uploading/transcribing.
23. Session switch calls `cancelRecording()` + clears pending transcript.

### Component tests (VoiceRecorder.test.tsx)

24. Renders "开始录音" button in `idle`.
25. Renders elapsed time during `recording`.
26. "停止录音" and "取消" buttons present during `recording`.
27. Spinner/indicator during `uploading` / `transcribing`.
28. Error message displayed with "重试".
29. `aria-live` region announces state changes.
30. `aria-label` present on buttons.
31. Controls disabled when `disabled` prop is true.

### API client tests (client.test.ts)

32. `transcribeAudio` uses `FormData`.
33. Does not set `Content-Type` header manually.
34. `file` and `language` field names correct.
35. File extension derived from MIME.
36. Transcription JSON parsed correctly.
37. API error mapped to user message.
38. `AbortSignal` respected.

### App integration tests (App.test.tsx)

39. Transcript fills empty input box.
40. Transcript does not overwrite non-empty input.
41. Replace / Append / Discard presented with pending transcript.
42. Transcript never auto-sent.
43. Aborted upload does not insert text into input.
44. ASR error does not break text input or send.
45. Recording stops TTS playback.
46. Playback button disabled during recording.

All tests use mocks — no real microphone required.

## 12. E2E design

### Playwright init script

Mock `navigator.mediaDevices.getUserMedia` to resolve a fake `MediaStream` with mock `MediaStreamTrack`s (track `stop()` is a no-op).

Mock `MediaRecorder`:
- Constructor records `mimeType`.
- `start()` begins collecting.
- `stop()` fires a `dataavailable` event with a minimal WebM-signature Blob (`\x1a\x45\xdf\xa3` + padding), then fires `stop` event.
- `isTypeSupported("audio/webm;codecs=opus")` returns `true`.

### E2E scenario

1. Open page with fake LLM + fake TTS + fake ASR.
2. Confirm page load did not trigger `getUserMedia`.
3. Click "开始录音".
4. Assert `getUserMedia` called once.
5. UI shows recording indicator.
6. Click "停止录音".
7. Mock `MediaRecorder` emits `dataavailable` + `stop`.
8. Frontend calls `POST /api/audio/transcriptions`.
9. Fake ASR returns deterministic transcript.
10. Transcript appears in input box.
11. Message list still has no new user message.
12. Click "发送".
13. User message and assistant reply appear.
14. Assistant Fake TTS "播放" button still works.
15. No browser console errors.
16. No 404 or 5xx.

No E2E test claims real microphone or real speech recognition.

## 13. Manual smoke plan

After implementation, the user manually verifies:

1. Open page on localhost.
2. No microphone permission prompt on page load.
3. Click "开始录音" → browser requests permission.
4. Grant permission → recording indicator visible.
5. Speak briefly, click "停止录音".
6. Fake ASR returns fixed test text "这是 Fake ASR 测试转写。".
7. Text appears in input box, not auto-sent.
8. Click "发送" → chat flow works normally.
9. Recording ends → browser microphone indicator disappears.
10. Deny permission → clear error message, text chat still works.
11. Type text before recording → conflict UI appears after transcript.

Note: Fake ASR does not recognize the user's actual speech. The transcript is always the deterministic fake text.

## 14. Privacy and security

- `getUserMedia` requires secure context (localhost OK, plain HTTP LAN IP may not work).
- No background recording, no wake word, no continuous listening.
- No pre-requested microphone permission.
- Audio exists as in-memory Blob during recording/upload only.
- No localStorage, IndexedDB, Cache Storage, or SQLite audio storage.
- No sending audio to DeepSeek — DeepSeek receives only manually submitted text.
- No logging of Blob content, full transcripts, or filenames.
- No device enumeration.
- Firefox/Safari format compatibility is not guaranteed; only Edge/Chromium WebM is the tested target.

## 15. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Browser MIME differs from declared | Upload rejected by backend | Use `recorder.mimeType`, backend signature check is authoritative |
| User has unsent text when recording | Transcript could overwrite | Conflict UI: Replace / Append / Discard |
| Fast repeated clicks | Multiple recorders | Status gate at hook level |
| Permission denied | User cannot record | Clear error, text fallback |
| Track cleanup bug | Microphone stays active | `finally` block on all error paths |
| TTS not stopped before record | Record+play conflict | `startRecording` calls `audioController.stop()` |
| Stale upload response | Overwrites newer transcript | AbortController + `mountedRef` guard |
| 30 s max timer fires twice | Double upload | Guard flag in ref |
| Browser recovers `recorder.mimeType` to unsupported value | Upload to backend fails with 415 | Frontend pre-check: don't upload if MIME family unsupported |
| Empty/silent recording | Fake ASR returns text anyway (no silence detection) | 2B-3 Fake ASR limitation; user can discard transcript manually |

## 16. Recommended implementation order

1. Add `TranscriptionResult` and `VoiceInputError` types to `frontend/src/api/types.ts`.
2. Add `transcribeAudio` method to `frontend/src/api/client.ts`.
3. Implement `useManualAudioRecorder` hook with full state machine and cleanup.
4. Test the hook with Vitest (no real microphone).
5. Implement `VoiceRecorder` UI component.
6. Test the component with Vitest.
7. Wire into `App.tsx` + `ChatLayout.tsx`:
   - Create recorder hook instance.
   - Wire `onStopTTSForRecording` to `audioController`.
   - Wire `isPlaybackBlocked` to playback controls.
   - Wire `onTranscriptReady` to input conflict logic.
   - Wire session switch cleanup.
8. Add input conflict resolution in `App` / `MessageInput`.
9. Add `MessageInput` `pendingText` support.
10. Run full offline regression (Vitest + typecheck + build + E2E).
11. Update E2E with mocked MediaRecorder.
12. Manual smoke.

## 17. Items pending user approval

1. **Input draft lifting**: whether to lift `content` from `MessageInput` to `App` (cleaner but more invasive) or keep the `pendingTranscript` prop approach (less invasive but adds a temporary UI element). Recommendation: `pendingTranscript` prop approach for minimal change.
2. **Blob size pre-check**: whether to additionally check Blob size in frontend before upload. Recommendation: yes, as a fast UX guard (backend check is the authoritative layer).
3. **MIME fallback**: whether to allow `MediaRecorder` without explicit `mimeType` when all three candidates fail. Recommendation: do not allow it — fail with `microphone_unsupported_format` and require explicit allowlist expansion to support that browser.
4. **Recording while sending**: whether "开始录音" should be disabled while a chat message is being sent (`loading` state). Recommendation: disable — `disabled` prop on VoiceRecorder should include `loading`.
5. **Cancel transcript after Ready**: after transcript is in input, should the recorder show a "清除转写" button? Recommendation: no — user can clear the input text directly in `MessageInput`.

---

## 18. Items decided and implemented — 2026-06-26

### Design decisions confirmed

1. **Draft ownership:** `MessageInput` remains sole draft owner; `pendingTranscript` prop approach selected.
2. **Blob size pre-check:** Frontend checks Blob.size ≤ 10 MiB before upload; backend `ASR_MAX_UPLOAD_BYTES` is the authoritative layer.
3. **MIME fallback:** Fail-closed. No unknown default format. Three candidates exhausted → `microphone_unsupported_format`.
4. **Recording while sending:** "开始录音" disabled when `loading` is true (chat message in flight).
5. **No "清除转写" button after ready:** User clears input directly in the textarea.

### 2B-3 implementation boundary verified

- The design doc was committed at `3df3c7d` after the 7-item fix pass (late getUserMedia resolution, isTypeSupported fragility, Blob/FormData native mock policy, draft sole ownership, 30 s frontend-cap clarification).
- Full offline regression at that point: backend 189 passed, Vitest 47 passed (5 files), typecheck PASS, build PASS, E2E 4/4 passed (including 3 new voice-recorder specs).
- No real microphone, real ASR, network requests, or audio file persistence involved.
- All implementation files remain uncommitted per task directive.

---

This document is design only. No implementation, no dependency installation, no microphone access, no API calls.
