# Stage 2E Explicit Voice Interruption Design

Date: 2026-06-29
Status: Approved recommended design for the next Stage 2 voice task.

## Context

Stage 2D is complete: after explicit user recording start, browser-side Silero/ONNX VAD can auto-stop recording after speech end while preserving manual stop/cancel. The app currently prevents recording while audio is busy:

- `App.tsx` disables the recorder when `audioController.isAudioBusy` is true.
- `handleStartRecording()` already calls `audioController.reset()` before `recorder.startRecording('')`.
- `useAudioPlaybackController.reset()` stops playback, aborts in-flight TTS synthesis, revokes object URLs, and clears audio entries.
- Existing 2C voice turn status uses `synthesizing_or_playing` to block new recorder starts during send-and-speak playback.

Stage 2E should add interruption/turn-control behavior without adding background listening or streaming.

## Goal

Allow the user to explicitly interrupt current TTS synthesis/playback by clicking `开始录音`. The click stops or cancels current assistant audio work, starts a new recording, and then uses the existing VAD/ASR/transcript confirmation path.

This is the smallest safe 2E slice: explicit user action interrupts audio. It does not open the microphone in the background while TTS is playing.

## Non-goals

- No always-on microphone.
- No wake word.
- No automatic speech-detected barge-in during playback.
- No echo cancellation beyond browser `getUserMedia` constraints already used by the recorder.
- No streaming ASR or streaming TTS.
- No backend `/voice-turns` endpoint.
- No database schema changes.
- No long-term memory or emotion behavior.
- No claim that the app is fully real-time.

## Chosen approach

Use explicit recorder start as the interruption action.

When audio is busy and the user clicks `开始录音`:

1. Stop active playback or abort in-flight synthesis through `audioController.reset()`.
2. Clear voice-turn playback/synthesis state if the interrupted audio came from `发送并朗读`.
3. Start the existing recorder.
4. Let Stage 2D VAD auto-stop the new recording.
5. Continue through the existing pending transcript review and `发送并朗读` path.

This preserves privacy and keeps the first 2E implementation small. A later task may add automatic playback-time VAD after echo/device risks are addressed.

## Architecture

### Existing units to modify

1. `frontend/src/hooks/useAudioPlaybackController.ts`
   - Expose enough state to distinguish audio busy categories if needed.
   - Keep `reset()` as the single cleanup path for playback/synthesis interruption.
   - Ensure reset aborts synthesis and stops playback idempotently.

2. `frontend/src/App.tsx`
   - Stop blocking `开始录音` solely because `audioController.isAudioBusy` is true.
   - Add a voice-interruption handler around recorder start.
   - If `voiceTurnStatus === 'synthesizing_or_playing'`, advance the voice-turn generation guard before starting recording so stale TTS completion cannot overwrite the new turn.
   - Keep recorder blocked while chat send is still in `sending_chat`; interrupting before the assistant reply exists is not part of 2E.

3. `frontend/src/components/VoiceRecorder.tsx`
   - Keep one visible `开始录音` button.
   - When audio is busy, the button label may remain `开始录音`; optional helper text can say `点击开始录音会停止当前朗读`.
   - Do not add a second destructive-looking button unless tests show ambiguity.

4. `frontend/src/components/ChatLayout.tsx`
   - Pass a short interruption hint to `VoiceRecorder` if implemented.

### New units

No new backend or state-machine library is required for the first 2E slice.

A small frontend helper may be added only if `App.tsx` becomes hard to read, for example `frontend/src/voiceInterruption.ts`, but this is optional.

## State rules

- `audioController.isAudioBusy` no longer disables the recorder by itself.
- Recorder remains disabled when:
  - app is loading session/message data,
  - there is no active session,
  - recorder is already active,
  - voice turn is `sending_chat`.
- If the current status is `synthesizing_or_playing`, starting a recording is treated as an explicit interruption:
  - increment voice-turn generation,
  - clear `voiceTurnInFlightRef`,
  - set `voiceTurnStatus` back to `idle`,
  - clear transient `voiceTurnError`,
  - call `audioController.reset()`,
  - start recorder.
- If regular assistant-message audio is playing, starting a recording simply calls `audioController.reset()` and starts recorder.
- If synthesis was in flight and later resolves, its stale result must not start playback after reset.
- Existing text messages remain visible; interruption only affects audio work.

## User flow

### Assistant-message playback interruption

1. User clicks `播放` on an assistant message.
2. Audio is synthesizing or playing.
3. User clicks `开始录音`.
4. Current audio stops or synthesis aborts.
5. Recorder enters `recording`.
6. VAD auto-stop or manual stop produces a pending transcript.
7. User chooses `发送并朗读` or normal text send.

### Send-and-speak playback interruption

1. User has pending transcript.
2. User clicks `发送并朗读`.
3. Chat reply is generated and TTS synthesis/playback begins.
4. User clicks `开始录音` during `synthesizing_or_playing`.
5. Current TTS work is interrupted and stale voice-turn completion is guarded.
6. New recording starts.
7. Existing transcript confirmation and send path handles the next turn.

## Error handling

- If stopping audio succeeds but microphone permission fails, show the existing microphone error; text chat remains usable.
- If synthesis abort produces an internal `AbortError`, do not show it as a user-facing failure for the interrupted turn.
- If playback stop fails unexpectedly, still attempt recorder start after `audioController.reset()` because reset is already best-effort.
- If a stale interrupted TTS request resolves after new recording starts, ignore it through existing active-message and voice-turn generation checks.
- If user switches session while interruption is happening, existing reset/generation logic wins and recorder state is cleaned.

## Privacy and safety

- Microphone still starts only after explicit user click.
- No listening while TTS plays unless the user clicked `开始录音`.
- No raw audio is saved by default.
- No private transcript or audio content is logged.
- No Stage 3 memory or Stage 4 emotion behavior is introduced.

## Testing plan

### Unit/component tests

- During assistant-message `playing`, `开始录音` is enabled.
- Clicking `开始录音` during assistant-message playback calls audio reset and starts recording.
- During assistant-message `synthesizing`, `开始录音` aborts synthesis and starts recording.
- During `voiceTurnStatus === 'synthesizing_or_playing'`, clicking `开始录音` clears stale voice-turn state and starts recording.
- Stale voice-turn TTS completion after interruption does not set a voice error or restart playback.
- `sending_chat` still blocks recording.
- Manual stop/cancel and VAD auto-stop behavior from 2D remain unchanged.

### Integration/E2E smoke

Use fake providers first:

1. Start playback for an assistant message.
2. Click `开始录音` while playback is busy.
3. Assert playback stopped and recorder entered recording.
4. Trigger stop/VAD and assert pending transcript appears.

Optional real local smoke after fake regression passes:

- With real VAD assets and fake ASR/TTS, start assistant playback, click `开始录音`, speak briefly, and verify pending transcript with 0 console errors.

## Documentation updates after implementation

- Add `docs/stage2e-explicit-voice-interruption.md` evidence file.
- Update `README.md` only after validation passes.
- Update `CLAUDE.md` only after validation passes.
- Add an addendum to `docs/stage2-voice-architecture.md`.

## Acceptance criteria

Stage 2E explicit interruption is complete only when all are true:

- User can click `开始录音` while assistant audio is synthesizing or playing.
- The click stops/aborts current assistant audio work.
- Recording starts after the interruption click.
- Existing VAD/manual stop/ASR pending transcript flow still works.
- Stale interrupted TTS completion does not restart playback or corrupt voice-turn state.
- Recording remains blocked during `sending_chat`.
- Text chat remains usable if microphone start fails.
- Default automated tests do not require real ASR/TTS/VAD models.
- Evidence is recorded in docs.
- No background listening, memory, or emotion behavior is introduced.

## Risks

| Risk | Mitigation |
|---|---|
| User expects automatic spoken barge-in | Label this slice as explicit interruption; keep automatic barge-in for a later task |
| Stale TTS completion changes state after interruption | Reuse generation guard and active message checks; add regression tests |
| Recorder starts while app is still loading | Keep loading/no-session blockers |
| Aborted synthesis shows confusing error | Treat interruption aborts as expected cleanup, not a voice-turn failure |
| Regression in 2D VAD auto-stop | Re-run VAD hook tests and App voice tests |
| Scope drifts into streaming or background listening | Keep 2E explicit-only and document non-goals |

## Alternatives considered

1. Playback-time automatic VAD barge-in.
   - More natural, but it requires microphone listening during playback and echo/feedback handling. This is too large for the first 2E slice.

2. Full-duplex streaming turn control.
   - Best long-term interaction model, but it belongs after explicit interruption and streaming measurements.

3. Separate `打断并录音` button.
   - Clearer wording but adds UI surface. The initial design keeps the existing `开始录音` button and may add helper text only.

## Self-review

- Placeholder scan: no TODO/TBD placeholders remain.
- Internal consistency: explicit user click is the only interruption trigger.
- Scope check: focused on Stage 2E; does not add background listening, streaming, memory, or emotion.
- Ambiguity check: blocked states, stale completion behavior, and acceptance criteria are explicit.
