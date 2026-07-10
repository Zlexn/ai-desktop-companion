# Stage 2F-pre Audio Input Device Management Design

Date: 2026-06-29
Status: Recommended design for the next Stage 2 voice task.

## Context

Stage 2E is complete: the user can explicitly interrupt assistant audio synthesis/playback by clicking `开始录音`, and the app starts the existing recorder/VAD/ASR path. Stage 2 still has two broad remaining areas in `CLAUDE.md`: audio device management and streaming ASR/TTS.

The current recorder uses the browser default microphone only:

```ts
navigator.mediaDevices.getUserMedia({
  audio: {
    echoCancellation: { ideal: true },
    noiseSuppression: { ideal: true },
    autoGainControl: { ideal: true },
  },
});
```

There is no `enumerateDevices()` flow, no selected input device state, no refresh control, and no `devicechange` handling. Existing device errors are generic but useful: permission denied, no microphone, microphone unavailable, unsupported context, and device disconnected.

MDN constraints relevant to this design:

- `enumerateDevices()` requires a secure context and visible document.
- Device labels may be empty until a stream is active or persistent permission exists.
- Non-default devices may be hidden until permission is granted.
- `getUserMedia({ audio: { deviceId } })` or `{ ideal: deviceId }` expresses a preferred device.
- `getUserMedia({ audio: { deviceId: { exact } } })` requires the device and may fail if unavailable.
- `devicechange` exists but should not be the only refresh path.

## Goal

Add a browser-side microphone input device management minimum loop:

1. Show available audio input devices.
2. Let the user choose `系统默认麦克风` or one enumerated microphone.
3. Use the selected microphone preference when starting recording.
4. Let the user refresh the device list.
5. Keep text chat and existing voice flows usable if device enumeration fails.

This task improves local real-voice reliability before streaming work. It remains inside Stage 2 and does not implement memory or emotion.

## Non-goals

- No speaker/output device selection.
- No `setSinkId()` or `selectAudioOutput()`.
- No microphone volume meter.
- No test recording wizard.
- No persistent device preference in localStorage or backend storage.
- No backend changes.
- No database schema changes.
- No streaming ASR or streaming TTS.
- No background listening, wake word, or automatic barge-in.
- No Stage 3 long-term memory.
- No Stage 4 emotion behavior.

## Chosen approach

Use a conservative input-only device picker.

The selected device is stored in React state for the current page session. The default value is the empty string `''`, meaning browser/system default microphone. When a non-empty device ID is selected, recording passes it to `getUserMedia` as an ideal constraint:

```ts
deviceId: { ideal: selectedDeviceId }
```

This avoids hard failure when a selected USB/Bluetooth microphone disappears or the browser chooses another device. The existing `NotFoundError`, `NotReadableError`, and track `ended` handling remains the primary user-facing recovery path.

## Architecture

### New unit: `frontend/src/hooks/useAudioInputDevices.ts`

Responsibilities:

- Detect whether `navigator.mediaDevices.enumerateDevices` is available.
- Enumerate devices and filter `kind === 'audioinput'`.
- Map each microphone to a stable frontend shape:

```ts
interface AudioInputDeviceOption {
  deviceId: string;
  label: string;
}
```

- Use browser labels when present.
- Use fallback labels `麦克风 1`, `麦克风 2`, etc. when labels are empty.
- Expose:

```ts
interface UseAudioInputDevicesResult {
  devices: AudioInputDeviceOption[];
  selectedDeviceId: string;
  setSelectedDeviceId: (deviceId: string) => void;
  refreshDevices: () => Promise<void>;
  status: 'idle' | 'loading' | 'ready' | 'unsupported' | 'error';
  error: string | null;
}
```

- On mount, run one best-effort enumeration without asking for microphone permission.
- Listen for `navigator.mediaDevices.devicechange` when available and refresh best-effort.
- If the selected device disappears after refresh, reset `selectedDeviceId` to `''`.

### Modify: `frontend/src/hooks/useManualAudioRecorder.ts`

Add an options object:

```ts
interface UseManualAudioRecorderOptions {
  audioInputDeviceId?: string;
}

export function useManualAudioRecorder(options: UseManualAudioRecorderOptions = {}): UseManualAudioRecorderResult
```

When starting recording, build audio constraints from the selected input:

```ts
const audioConstraints: MediaTrackConstraints = {
  echoCancellation: { ideal: true },
  noiseSuppression: { ideal: true },
  autoGainControl: { ideal: true },
};

if (options.audioInputDeviceId) {
  audioConstraints.deviceId = { ideal: options.audioInputDeviceId };
}
```

Then call:

```ts
navigator.mediaDevices.getUserMedia({ audio: audioConstraints });
```

No other recorder behavior changes.

### Modify: `frontend/src/App.tsx`

- Instantiate `useAudioInputDevices()`.
- Pass `audioInputDevices` state to `ChatLayout`.
- Pass `selectedDeviceId` into `useManualAudioRecorder({ audioInputDeviceId })`.
- Keep existing voice-turn generation, VAD, and interruption logic unchanged.

### Modify: `frontend/src/components/ChatLayout.tsx`

Pass device-management props to `VoiceRecorder`.

### Modify: `frontend/src/components/VoiceRecorder.tsx`

Render a small microphone device selector near existing recorder controls:

- Label: `麦克风`
- Select options:
  - `系统默认麦克风` with value `''`
  - Each enumerated microphone option
- Button: `刷新设备`
- Status text:
  - `正在读取麦克风设备` when loading
  - `无法读取麦克风设备，请使用系统默认麦克风` on error
  - `当前浏览器不支持麦克风设备列表` on unsupported
- Disable select and refresh while recorder status blocks playback/recording operations.

The existing `开始录音`, VAD status, pending transcript, and voice interruption hint remain unchanged.

## State rules

- `selectedDeviceId === ''` means system default microphone.
- The picker is non-blocking: enumeration failure does not disable recording.
- Starting recording still requests microphone permission only after explicit user click.
- Selection is disabled while `recorder.status` is not `idle`, `ready`, or `error`.
- If the selected device disappears, reset to default and keep a recoverable status message.
- Do not persist device IDs. Device IDs can be privacy-sensitive and browser-generated.

## User flow

### Initial page load

1. App loads.
2. Device hook calls `enumerateDevices()` best-effort.
3. UI shows `系统默认麦克风` plus any visible input devices.
4. If labels are hidden, UI shows fallback names such as `麦克风 1`.
5. No microphone stream starts on page load.

### Selecting a microphone

1. User opens the `麦克风` select.
2. User picks a device.
3. User clicks `开始录音`.
4. Recorder calls `getUserMedia()` with the selected device as an ideal preference.
5. Existing recording, VAD, stop, upload, and transcript confirmation behavior continues.

### Refreshing devices

1. User plugs/unplugs a microphone or changes OS device state.
2. User clicks `刷新设备`, or browser fires `devicechange`.
3. Device list updates.
4. If selected device is missing, the app falls back to `系统默认麦克风`.

## Error handling

- `enumerateDevices` unsupported: show `当前浏览器不支持麦克风设备列表`; keep default recording available.
- `enumerateDevices` rejects: show `无法读取麦克风设备，请使用系统默认麦克风`; keep default recording available.
- Empty device list: show only `系统默认麦克风`; keep recording available.
- Selected device becomes unavailable: reset to default after refresh; if recording fails anyway, existing recorder errors apply.
- `getUserMedia` permission/device errors remain mapped by `useManualAudioRecorder`.
- No raw device IDs are logged.

## Privacy and safety

- No microphone permission request occurs on page load.
- No raw audio is saved by this feature.
- Device IDs are not sent to the backend.
- Device IDs are not persisted to localStorage or SQLite in this slice.
- No API keys, tokens, or private audio artifacts are introduced.

## Testing plan

### Hook tests for `useAudioInputDevices`

- Unsupported browser returns `unsupported` and empty device list.
- Successful enumeration returns only audio input devices.
- Empty labels produce `麦克风 1`, `麦克风 2` fallback labels.
- `refreshDevices()` updates the list.
- `devicechange` triggers best-effort refresh when available.
- Selected missing device resets to default after refresh.
- Enumeration rejection sets `error` but leaves selected device default.

### Recorder tests

- With no selected device, `getUserMedia` receives existing audio constraints without `deviceId`.
- With selected device, `getUserMedia` receives `deviceId: { ideal: selectedDeviceId }` while preserving echo/noise/auto-gain constraints.

### App/component tests

- The microphone selector renders with `系统默认麦克风`.
- Enumerated devices appear in the selector.
- Selecting a device and clicking `开始录音` passes the selected device to recorder.
- Refresh button calls `refreshDevices`.
- Selector is disabled while recording.
- Existing Stage 2D VAD and Stage 2E interruption tests still pass.

### E2E smoke

Use fake media and fake providers:

- Page load does not call `getUserMedia`.
- Recorder button and microphone selector are visible.
- Text chat remains usable.
- Existing fake voice-turn E2E remains PASS.

Real device smoke is optional after automated tests pass: manually verify that plugging/unplugging a microphone and pressing `刷新设备` updates the selector without console errors.

## Documentation updates after implementation

- Add `docs/stage2f-audio-device-management.md` evidence file.
- Update `README.md` only after validation passes.
- Update `CLAUDE.md` only after validation passes.
- Add an addendum to `docs/stage2-voice-architecture.md`.

## Acceptance criteria

Stage 2F-pre audio input device management is complete only when all are true:

- The UI shows a microphone selector with `系统默认麦克风`.
- The UI can display enumerated audio input devices with safe fallback labels.
- The user can refresh the device list.
- Selected device ID is used as an ideal `getUserMedia` audio constraint.
- Enumeration failure does not break recording or text chat.
- Page load does not request microphone permission.
- Recording/VAD/interruption flows remain functional.
- Automated tests do not require real microphones, real ASR, real TTS, or real VAD.
- Evidence is recorded in docs.
- No output-device selection, streaming, memory, or emotion behavior is introduced.

## Risks

| Risk | Mitigation |
|---|---|
| Device labels are blank before permission | Use fallback labels and keep default option clear |
| Selected device disappears | Reset to default on refresh/devicechange; use `ideal`, not `exact` |
| Browser does not support enumeration | Show unsupported message; keep default recording path |
| Device IDs are privacy-sensitive | Keep in memory only; do not persist or send to backend |
| Scope drifts into output device or testing wizard | Explicit non-goals; input-only picker |
| VAD/interrupt regressions | Re-run existing App, VAD, and E2E tests |

## Self-review

- Placeholder scan: no TODO/TBD placeholders remain.
- Internal consistency: the design is input-only and uses `ideal` device constraints everywhere.
- Scope check: focused on one Stage 2 browser-device slice; does not add output selection, streaming, memory, or emotion.
- Ambiguity check: selected-device default, missing-device reset, unsupported behavior, and validation criteria are explicit.
