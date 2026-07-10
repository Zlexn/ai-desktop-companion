# Stage 2F-pre Audio Input Device Management Evidence

Status: COMPLETED on 2026-06-29.

## Scope

This slice adds browser-side microphone input device management: the UI shows a microphone selector, lets the user choose system default or an enumerated audio input device, lets the user refresh devices, and passes the selected device as an ideal `getUserMedia` constraint when recording starts.

It does not add speaker/output device selection, persistent device preferences, streaming ASR/TTS, background listening, long-term memory, or emotion behavior.

## Validation

| Command | Result |
|---|---|
| `npm test -- --run src/hooks/useAudioInputDevices.test.ts` | PASS — 6 passed |
| `npm test -- --run src/App.test.tsx` | PASS — 18 passed |
| `npm test -- --run src/hooks/useVadAutoStop.test.ts` | PASS — 6 passed |
| `npm test -- --run` | PASS — 81 passed |
| `npm run typecheck` | PASS |
| `npm run build` | PASS |
| `npm run test:e2e` | PASS — 5 passed |

## Runtime verification

A local runtime verification launched the FastAPI backend on `127.0.0.1:18102` and the Vite frontend on `127.0.0.1:15175` with fake providers and `--mode test`, then drove the browser UI through the real controls.

Observed result:

```json
{
  "selectorVisible": true,
  "refreshVisible": true,
  "defaultOptionPresent": true,
  "usbOptionPresent": true,
  "optionValues": [
    { "value": "", "text": "系统默认麦克风" },
    { "value": "default", "text": "Default Mic" },
    { "value": "usb-mic", "text": "USB Mic" }
  ],
  "getUserMediaCallsBeforeRecord": 0,
  "selectedDeviceId": "usb-mic",
  "usedIdealDeviceId": true,
  "recordingStarted": true,
  "getUserMediaCallsAfterRecord": 1,
  "consoleErrors": []
}
```

## Behavior verified

- The UI shows `系统默认麦克风` and enumerated microphone options.
- Empty browser device labels fall back to safe labels such as `麦克风 1`.
- The user can refresh the microphone list.
- Selected device ID is passed as `deviceId: { ideal: selectedDeviceId }`.
- Page load does not request microphone permission.
- Enumeration failure does not block recording or text chat.
- Existing VAD, voice interruption, and fake voice-turn tests remain passing.

## Evidence notes

No raw audio, private transcript, API key, generated speech artifact, or persistent device ID is committed by this document.
