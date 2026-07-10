# Stage 2F-2 Audio Output Device Selection and Device Preference Persistence Design

Date: 2026-06-29

## Status

Design approved for implementation planning. This document does not implement code.

## Current phase

Stage 2 — voice features. This task remains inside Stage 2 and does not implement long-term memory, emotion state, background listening, streaming ASR, or streaming TTS.

## Goal

Complete the remaining Stage 2 device-management gap by letting the user choose the audio output device used for assistant speech playback and by persisting both microphone and output-device preferences locally in the browser.

The existing text chat, ASR transcription, half-duplex voice turn, VAD auto-stop, explicit interruption, and TTS playback flows must continue to work when device selection is unsupported, denied, or stale.

## Non-goals

- Do not implement streaming ASR or streaming TTS.
- Do not change backend APIs, provider abstractions, or database schema.
- Do not store device preferences on the backend.
- Do not persist raw audio.
- Do not implement output volume control, equalization, wake word, background listening, long-term memory, or emotion behavior.
- Do not require browser microphone permission on page load.

## Existing baseline

The app already has:

- `useAudioInputDevices` for microphone enumeration and explicit selection.
- `useManualAudioRecorder` accepting `audioInputDeviceId` and passing it to `getUserMedia` as `deviceId: { ideal }`.
- `useAudioPlaybackController` owning one internal `HTMLAudioElement` and all assistant TTS playback state.
- `VoiceRecorder` showing microphone selection and refresh controls.
- Fake-provider E2E and front-end unit tests around voice recording, voice turns, VAD, interruption, and playback.

Current gaps:

- No output-device selector.
- Microphone choice is not persisted after page reload.
- There is no reusable local preference boundary for audio devices.

## Recommended architecture

### 1. Local device preferences

Add a small front-end-only preference layer for audio device IDs.

Recommended shape:

```ts
interface AudioDevicePreferences {
  inputDeviceId: string;
  outputDeviceId: string;
}
```

Storage:

- Use `localStorage` only.
- Use empty string to mean system default.
- Store only browser-provided opaque device IDs, never labels, raw audio, transcripts, or message content.
- Treat storage failures as non-fatal and fall back to system defaults.

Suggested storage key:

```text
ai-desktop-companion.audio-device-preferences.v1
```

The preference helper should be small and testable. It should tolerate missing `window`, unavailable `localStorage`, malformed JSON, unknown fields, and quota/security exceptions.

### 2. Persist microphone selection

Extend `useAudioInputDevices` so it:

1. Initializes `selectedDeviceId` from local preference when available.
2. Writes preference changes when the user selects a microphone.
3. Clears or resets the selected microphone to default if device enumeration succeeds and the saved device ID is no longer present.
4. Keeps the current no-permission-on-page-load behavior. Device enumeration must not call `getUserMedia` by itself.

The existing recorder should continue to receive the selected input ID through `useManualAudioRecorder({ audioInputDeviceId })`.

### 3. Output device hook

Add `useAudioOutputDevices` with behavior parallel to the input hook but adapted to output APIs.

Responsibilities:

- Feature-detect `HTMLMediaElement.prototype.setSinkId`.
- Feature-detect `navigator.mediaDevices.enumerateDevices`.
- Optionally feature-detect `navigator.mediaDevices.selectAudioOutput`.
- Enumerate `audiooutput` devices that the browser exposes.
- Maintain `selectedDeviceId`, `status`, `error`, and device list.
- Persist selected output ID in local preferences.
- Reset to default if enumeration confirms the saved output device is gone.
- Provide a method such as `selectOutputDevice()` that uses `navigator.mediaDevices.selectAudioOutput()` when available, then persists the returned `deviceId` and refreshes devices.
- Provide `refreshDevices()` for already-authorized devices.

Suggested return type:

```ts
interface UseAudioOutputDevicesResult {
  devices: AudioOutputDeviceOption[];
  selectedDeviceId: string;
  setSelectedDeviceId(deviceId: string): void;
  refreshDevices(): Promise<void>;
  selectOutputDevice(): Promise<void>;
  status: 'idle' | 'loading' | 'ready' | 'unsupported' | 'error';
  error: string | null;
  canSelectOutput: boolean;
}
```

Unsupported behavior:

- If `setSinkId` is unavailable, mark the hook `unsupported`, keep `selectedDeviceId` as default, and let playback use the system default.
- If `selectAudioOutput` is unavailable but `setSinkId` and `enumerateDevices` exist, allow choosing among enumerated devices only.
- If enumeration fails, keep playback usable with the system default and show a non-blocking error.

### 4. Playback controller integration

Extend `useAudioPlaybackController` so the internal `HTMLAudioElement` is routed to the selected output device before playback.

Recommended behavior:

1. The hook accepts `audioOutputDeviceId?: string`.
2. Before `audio.play()` in `playExisting`, call a small helper such as `applySinkId(audio, audioOutputDeviceId)`.
3. Empty output device ID means default output; call `setSinkId('')` only when supported.
4. If `setSinkId` rejects, return a playback failure message that is specific enough for the user, but do not lose the synthesized audio URL or assistant text.
5. If unsupported, do not call `setSinkId`; playback continues through the browser/system default output.
6. Existing stop, pause, resume, replay, interruption, and session-switch cleanup semantics must remain unchanged.

If a user changes output device while audio is already playing, the minimal implementation may apply the new sink on the next play/resume/replay. Live rerouting during active playback is optional and should not be required for this slice.

### 5. UI integration

Add output controls next to the existing microphone controls in the voice control area.

Minimum UI:

- Label: `扬声器/耳机`.
- Select option: `系统默认输出设备`.
- Options for enumerated `audiooutput` devices.
- Button: `选择输出设备` when `selectAudioOutput` is supported.
- Button: `刷新输出设备` for enumeration refresh.
- Unsupported text: `当前浏览器不支持单独选择输出设备，将使用系统默认输出。`
- Error text for enumeration or selection failure, without blocking text chat, recording, ASR, or TTS through default output.

The UI should avoid requesting microphone permission on page load. It may prompt for speaker selection only when the user explicitly clicks `选择输出设备`.

## Data flow

### Page load

```text
localStorage -> audio device preference helper
  -> useAudioInputDevices selectedDeviceId
  -> useAudioOutputDevices selectedDeviceId
  -> enumerate devices if supported
  -> invalid saved IDs reset to default after successful enumeration
```

### Recording

```text
selected input device ID
  -> useManualAudioRecorder
  -> getUserMedia({ audio: { deviceId: { ideal: selectedDeviceId }, echoCancellation, noiseSuppression, autoGainControl } })
```

### Assistant speech playback

```text
assistant text
  -> existing TTS request
  -> Blob URL
  -> internal HTMLAudioElement
  -> apply selected output sink if supported
  -> audio.play()
```

### Output selection prompt

```text
user clicks 选择输出设备
  -> navigator.mediaDevices.selectAudioOutput()
  -> selected deviceId persisted locally
  -> output devices refreshed
  -> future playback uses selected sink
```

## Error handling

- `localStorage` read/write failure: ignore and use defaults.
- Malformed preference JSON: ignore and overwrite on next valid selection.
- Saved input device missing after enumeration: reset input preference to default.
- Saved output device missing after enumeration: reset output preference to default.
- `setSinkId` unsupported: show unsupported output-device message; playback uses default output.
- `selectAudioOutput` unsupported: hide or disable prompt button; allow only visible enumerated devices.
- `selectAudioOutput` user cancellation or denial: keep previous/default output and show a non-blocking message.
- `setSinkId` `NotAllowedError`, `NotFoundError`, or `AbortError`: surface a user-facing playback/output error and keep the assistant message and synthesized URL available for retry.
- Device enumeration failure: show a non-blocking device error and keep default devices usable.

Voice failures must not break text chat. Output-device failures must not break microphone recording or ASR.

## Privacy and security

- Only opaque browser device IDs are persisted locally.
- Device labels should not be persisted because labels may contain personally identifying hardware names.
- No raw audio is stored.
- No new backend storage or telemetry is introduced.
- The speaker-selection prompt happens only after explicit user action.
- Existing API key and provider secret rules are unchanged.

## Testing plan

### Unit tests

Add or update front-end tests for:

1. Preference helper reads valid preferences.
2. Preference helper tolerates malformed JSON and storage exceptions.
3. Microphone selection initializes from saved input preference.
4. Microphone selection persists changes.
5. Missing saved microphone after enumeration resets to default.
6. Output hook reports unsupported when `setSinkId` is unavailable.
7. Output hook enumerates `audiooutput` devices when supported.
8. Output hook persists selected output device.
9. Output hook uses `selectAudioOutput()` when explicitly requested.
10. Output hook handles selection rejection without throwing to React.
11. Playback controller calls `setSinkId(selectedOutputDeviceId)` before `play()` when supported.
12. Playback continues through default output when `setSinkId` is unsupported.
13. Playback reports a useful error when `setSinkId` rejects.

### E2E / integration tests

Extend fake-provider Playwright coverage so that:

1. The output-device UI renders without prompting for microphone permission.
2. Selecting a mocked output device and running a voice turn still produces exactly one chat request, one TTS request, and one play call.
3. Output-device unsupported mode still allows default TTS playback controls.
4. Device preference persistence survives reload in a mocked browser environment if practical; otherwise cover this with Vitest and document why E2E cannot reliably assert browser-generated IDs.

### Commands

Expected validation commands:

```text
cd frontend
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
```

If a headed browser smoke is run, record browser support and result without claiming cross-browser support beyond what was tested.

## Documentation updates

Update:

- `CLAUDE.md` current Stage 2 status after implementation and validation.
- A new evidence document, recommended path: `docs/stage2f2-audio-output-device-preferences.md`.
- README only if user-facing setup or browser support notes change.

The evidence document must state that this task does not implement streaming ASR/TTS, long-term memory, or emotion behavior.

## Acceptance criteria

This task is complete only when:

1. User can keep using the system default microphone and output device without changing settings.
2. User can select a microphone and the preference is restored after page reload when still valid.
3. In browsers supporting `setSinkId`, user can select an output device for assistant speech playback.
4. Output preference is restored after page reload when still valid.
5. Unsupported output-device selection falls back to system default with a clear message.
6. Missing/stale saved device IDs reset safely to defaults.
7. Text chat remains usable when any device enumeration, selection, or sink routing fails.
8. Voice recording, ASR, chat, TTS synthesis, playback, interruption, and session-switch cleanup still pass existing regressions.
9. Automated tests, typecheck, build, and necessary E2E pass.
10. Validation commands and results are recorded in the evidence document.

## Phase boundary

This design stays within Stage 2 voice features. It prepares the browser audio layer for future streaming playback but does not implement streaming, memory, or emotion. Stage 3 and Stage 4 remain blocked until Stage 2 acceptance is fully completed and recorded.
