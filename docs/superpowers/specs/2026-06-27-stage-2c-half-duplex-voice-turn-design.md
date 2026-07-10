# 2C Half-Duplex Voice Turn Design

> Status: design for the next Stage 2 voice task. This document does not implement code, change runtime behavior, add long-term memory, or add emotion.

**Current phase:** Stage 2 — voice features.

**Goal:** Add the first complete half-duplex voice turn by composing the already implemented ASR, text chat, and TTS paths. The user records speech, reviews the transcript, explicitly sends it as a chat message, receives the assistant text reply through the existing chat pipeline, and hears that reply through the existing TTS playback path.

**Recommended implementation shape:** Frontend-orchestrated three-step flow. Do not add a backend `/voice-turns` endpoint for this first 2C slice unless implementation evidence shows the client orchestration cannot satisfy cancellation or error handling requirements.

---

## 1. Context

The project is in Stage 2. The following voice primitives are already implemented and verified:

- Stage 2A: assistant-message TTS playback controls with fake TTS, no autoplay by default.
- Stage 2B: manual browser recording and ASR upload flow.
- 2B-5 and 2B-6: FasterWhisper real ASR provider and main-app smoke.
- 2B-7: CosyVoice HTTP TTS provider smoke through backend `/api/audio/speech` and browser playback.

The remaining Stage 2 items in `CLAUDE.md` are 2C full half-duplex voice turn, VAD, interruption/turn control, audio device management, and streaming ASR/TTS. This design covers only the first item.

Today the user can already perform the sequence manually:

1. Record audio and get a transcript.
2. Apply the transcript to the text input.
3. Send the text message.
4. Click the assistant message playback control.

2C should turn that manual sequence into a clearer single voice-turn UX while preserving explicit user confirmation and text fallback.

## 2. Recommended next task

The next minimal closed-loop task is **2C-1 Fake full half-duplex voice turn, frontend-orchestrated**.

This is smaller and safer than adding a backend orchestration endpoint because all required API primitives already exist:

- `POST /api/audio/transcriptions` for ASR.
- `POST /api/sessions/{session_id}/messages` for text chat and persistence.
- `POST /api/audio/speech` for TTS.
- Frontend playback controls for assistant messages.

The first 2C implementation should be fully testable with fake ASR, fake LLM, and fake TTS providers. A real FasterWhisper + DeepSeek + CosyVoice smoke is a separate validation step after the fake full-turn path is stable. If that real-provider smoke is deferred, documentation must say **2C-1 fake-provider baseline is complete, but full 2C real-provider closure remains incomplete**; `CLAUDE.md` must not mark the whole 2C milestone complete until real evidence exists.

## 3. Scope

### In scope

- Add an explicit user action for a pending transcript, such as `发送并朗读`.
- Use the pending ASR transcript as the user-confirmed message content.
- Call the existing text-chat endpoint to persist the user message and assistant reply.
- Refresh sessions and messages using the existing frontend flow.
- Determine the exact assistant message created by the send operation using a stable rule, not a blind newest-message heuristic.
- Invoke the existing TTS playback controller for that assistant message.
- Expose enough global audio busy state to enforce half-duplex behavior: recording and playback/synthesis cannot be active at the same time.
- Prevent duplicate voice-turn submission while the current turn is sending, synthesizing, or playing.
- Preserve text messages if TTS synthesis or playback fails after chat succeeds.
- Keep text input and normal text send usable as fallback.
- Update documentation and validation evidence for 2C-1.

### Out of scope

- No VAD or automatic end-of-speech detection.
- No speech interruption or barge-in during TTS playback.
- No background listening, wake word, or continuous microphone capture.
- No streaming ASR or streaming TTS.
- No audio device selection UI.
- No new backend `VoiceTurnService` or `/api/sessions/{session_id}/voice-turns` endpoint in 2C-1.
- No changes to message database schema.
- No persistence of raw audio or generated audio files.
- No long-term memory.
- No emotion state machine or emotional voice control.
- No Live2D expression, mouth movement, or character animation binding.

## 4. Architecture decision

### Decision: frontend orchestration first

Use the frontend as the orchestration layer for 2C-1:

```text
MediaRecorder blob
  -> apiClient.transcribeAudio
  -> pending transcript
  -> user clicks Send and Speak
  -> apiClient.sendMessage
  -> apiClient.listSessions + apiClient.listMessages
  -> assistant message selected by stable post-send matching rule
  -> audioController.play(assistantMessage.id, assistantMessage.content)
```

Assistant message selection rule for 2C-1:

1. Before sending, capture the active `sessionId`, the current message list, and the current maximum assistant-message creation/order marker available in the frontend data.
2. After `apiClient.sendMessage` returns and messages are refreshed, ignore the result if the active session changed.
3. Prefer the first assistant message in the refreshed list that was not present before the send and that appears after the newly persisted user transcript in message order.
4. If multiple new assistant messages are detected, choose the one directly following the new user transcript in the refreshed message order.
5. If no stable match can be found, do not auto-play any message; show a recoverable voice-turn error and leave manual assistant playback available.

This rule avoids using “newest assistant message” as a blind heuristic. If the existing message schema lacks enough ordering information to implement this reliably, implementation should add the smallest frontend-side comparison needed using existing message IDs/timestamps/order from `listMessages`, not a new backend endpoint.

Backend services remain separated:

```text
/api/audio/transcriptions -> ASRService -> ASRProvider
/api/sessions/{id}/messages -> ChatService -> LLMProvider -> SQLite messages
/api/audio/speech -> TTSService -> TTSProvider
```

### Why not add `/voice-turns` now

A backend voice-turn endpoint would need a new response design for mixed JSON metadata and binary audio, or a temporary audio resource mechanism. It would also need carefully defined partial-success semantics when ASR and chat succeed but TTS fails. The current frontend-orchestrated flow already has the desired partial-success behavior: once chat succeeds, the text messages remain visible even if TTS fails.

A backend endpoint remains a valid later option if 2C-1 reveals a concrete need for server-side cancellation, unified telemetry, or stricter transactional orchestration.

## 5. User experience

### Primary flow

1. User selects or creates a session.
2. User clicks `开始录音`.
3. Any current playback stops before recording begins.
4. User clicks `结束录音` or the existing 30-second cap stops recording.
5. ASR returns a pending transcript.
6. UI shows the transcript and explicit choices:
   - Replace input.
   - Append to input.
   - Discard.
   - Send and speak.
7. User clicks `发送并朗读`.
8. The app sends the transcript as a normal text message.
9. The app refreshes the message list.
10. The app selects the assistant message produced by this send using the stable post-send matching rule.
11. The app synthesizes and plays that assistant reply.
12. User can pause, resume, stop, or replay with existing controls.

### Default confirmation policy

2C-1 must keep user confirmation explicit. It should not automatically send ASR text immediately after transcription.

An auto-send option may be designed later in Stage 2 only if it is explicit opt-in and default off. It is not required for 2C-1.

### Text fallback

Text input remains usable when no send request is in flight. If ASR, chat, TTS, or playback fails, the user can continue by typing or by using the existing assistant playback controls.

## 6. State model

2C-1 can extend current frontend state without introducing a large framework.

Recommended voice-turn states:

```text
idle
recording_or_transcribing
ready_to_send
sending_chat
synthesizing_or_playing
error
```

These states may be represented by existing recorder status, existing global loading state, and a small new `voiceTurnStatus` only where necessary. Implementation must also expose a global audio busy signal from the playback controller, for example `isAudioBusy`, that is true while any assistant message is synthesizing, playing, or paused for a turn. The existing per-message `stateFor(messageId)` API is not sufficient by itself to block recording globally.

Rules:

- Starting recording calls the existing playback reset/stop path first.
- Recording cannot start while an assistant reply is synthesizing, playing, or paused unless the user explicitly stops playback first.
- `发送并朗读` is disabled while chat send, TTS synthesis, or playback for the current turn is in flight.
- Repeated clicks on `发送并朗读` cannot create duplicate user messages.
- Stale async results must not overwrite state after session switch, delete, or a newer voice action.
- Switching, creating, or deleting sessions clears pending transcript and stops playback.
- TTS failure after chat success sets a voice-specific error but does not remove messages.

## 7. Data and persistence

No new persistent data model is introduced.

Message persistence remains exactly the Stage 1 text-chat model:

- ASR transcript becomes the normal user message only after explicit user confirmation.
- Assistant text reply is persisted by `ChatService` through the existing chat endpoint.
- TTS audio is not persisted as a chat message.
- Raw recording audio is not persisted by application code.
- Generated TTS object URLs remain browser-local and are revoked through the existing playback controller lifecycle.

## 8. Error handling

### ASR failure

- Show the existing transcription error.
- Allow re-recording or manual text input.
- Do not create a chat message.

### Chat failure

- Show the existing chat error.
- Do not start TTS.
- Preserve pending transcript or input text when possible so the user can retry.

### TTS synthesis failure

- Keep the user and assistant text messages visible.
- Show a clear message such as `文字回复已生成，但语音合成失败。可稍后重试播放。`
- Leave the assistant message playback control available for retry.

### Playback failure

- Keep the text reply visible.
- Show the existing playback error or a voice-turn level message.
- Allow replay or manual continuation.

### Session changes during a voice turn

- Stop playback and recording.
- Abort or ignore stale frontend requests where practical.
- Clear pending transcript for the old session.
- Do not delete already persisted messages.

## 9. Files likely to change in implementation

Expected frontend files:

- `frontend/src/App.tsx`
  - Add a voice-turn send handler that sends pending transcript, selects the matching assistant reply with the stable post-send rule, and then plays that assistant reply.
  - Track minimal voice-turn status if existing `loading` and recorder status are not enough.
- `frontend/src/components/MessageInput.tsx`
  - Add an explicit `发送并朗读` action for pending transcripts, or expose a prop that lets the parent render this action near transcript confirmation.
- `frontend/src/components/ChatLayout.tsx`
  - Thread new handler/status props.
- `frontend/src/hooks/useAudioPlaybackController.ts`
  - Add a small global audio busy helper, such as `isAudioBusy`, covering synthesis, playing, and paused playback, so the recorder can enforce the 2C half-duplex rule.
- `frontend/src/App.test.tsx` and/or component tests
  - Cover pending transcript voice-turn behavior.
- `frontend/e2e/*.spec.ts`
  - Add fake-provider full-turn coverage.

Expected docs:

- `README.md`
  - Update Stage 2 status and explain 2C-1 usage after validation.
- `CLAUDE.md`
  - Update only after tests and smoke evidence pass.
- A 2C implementation evidence doc may be added if needed.

No backend file is expected to change for 2C-1 unless tests reveal an existing API bug.

## 10. Testing plan

### Frontend automated tests

Add tests that verify:

1. A pending transcript exposes a `发送并朗读` action.
2. Clicking it calls the existing chat send path with the transcript text.
3. The message list is refreshed after chat send.
4. The assistant message produced by the voice-turn send is selected by the stable post-send matching rule and passed to the TTS playback controller.
5. If the active session changes before refreshed messages are applied, stale voice-turn results are ignored.
6. Duplicate clicks do not create duplicate chat sends.
7. TTS failure after chat success displays a recoverable voice error and keeps messages visible.
8. Global audio busy state blocks starting a new recording while synthesis, playback, or paused playback is active in 2C half-duplex mode.
9. Creating, selecting, or deleting a session clears pending transcript and stops recording/playback without applying stale results.
10. Normal text send still works without TTS autoplay.

### E2E tests with fake providers

Add a Playwright flow that uses deterministic fake providers and avoids real microphone/model calls. The test should verify:

1. The app does not call `getUserMedia` on page load.
2. A session can be created.
3. A transcript can reach the pending transcript UI through an existing fake recorder path or a controlled browser mock.
4. `发送并朗读` creates exactly one user message and one assistant message.
5. The assistant message TTS path is requested once.
6. Text chat remains usable afterward.
7. Browser console has no unexpected errors.
8. Session switch/create/delete during or after a pending voice turn clears stale transcript/playback state and does not auto-play a reply in the wrong session.

### Backend regression

Run the existing backend tests. Since 2C-1 should not change backend behavior, all current ASR, TTS, and chat API tests must remain passing.

### Real local smoke after fake validation

After fake automated validation passes, run one manual or scripted UI smoke with explicit real providers:

- ASR: `ASR_PROVIDER=faster-whisper` with the current C3 candidate or documented fallback.
- LLM: configured real text provider.
- TTS: `TTS_PROVIDER=cosyvoice-http` with the local CosyVoice service already started.

Smoke criteria:

- Browser records audio.
- Real ASR transcript appears for confirmation.
- User confirms `发送并朗读`.
- Text user and assistant messages appear.
- Assistant reply plays through real TTS.
- TTS failure, if any, is reported without losing text messages.
- Console errors are recorded.

## 11. Validation commands

Expected regression commands after implementation:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -v
Push-Location frontend
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
Pop-Location
```

Real-provider smoke commands will depend on the active local model paths and CosyVoice service process. They must be documented with exact environment variables and observed results when run. Do not commit secrets, private recordings, or model cache contents.

## 12. Security and privacy

- No background recording.
- No wake word.
- No raw audio persistence.
- No generated audio persistence.
- Do not log raw audio or full private transcripts.
- Do not send audio to the LLM provider.
- Send ASR text to the LLM only after explicit user confirmation.
- Keep voice providers opt-in through configuration.
- Do not introduce unauthorized voice cloning or unauthorized character/voice actor voices.
- Do not implement Stage 3 memory or Stage 4 emotion behavior in this task.

## 13. Acceptance criteria

2C-1 fake-provider baseline is complete only when all applicable evidence is recorded. Completing 2C-1 does **not** by itself close the full `2C 完整半双工语音回合` item in `CLAUDE.md` if the real-provider full-turn smoke is deferred.

1. User can complete a fake-provider half-duplex voice turn from pending transcript to assistant TTS playback.
2. ASR transcript is sent as a normal user text message only after explicit confirmation.
3. Assistant reply is persisted as a normal assistant text message through the existing chat path.
4. The auto-played assistant message is selected by a stable post-send matching rule; if no stable match exists, the app does not auto-play an unrelated message.
5. TTS failure after chat success does not remove or hide text messages.
6. Recording and playback/synthesis are mutually exclusive in the UI through a global audio busy signal.
7. Duplicate `发送并朗读` actions cannot create duplicate user messages.
8. Session switch, create, or delete clears pending voice-turn state and does not apply stale transcript, message refresh, or playback results to the wrong session.
9. Normal text chat remains usable.
10. Existing backend tests pass.
11. Frontend tests, typecheck, build, and E2E pass or any failure is documented honestly.
12. Real-provider UI smoke is run and recorded for full 2C closure; if deferred, document it as 2C-2 and keep `CLAUDE.md` clear that full 2C remains incomplete.
13. Documentation reflects exactly what passed and what remains incomplete.
14. Stage 2 remains `IMPLEMENTING`; Stage 3 and Stage 4 remain not started.

## 14. Follow-up tasks after 2C-1

Recommended sequence after 2C-1:

1. **2C-2 Real full-turn smoke:** validate FasterWhisper + real text provider + CosyVoice HTTP in one browser voice turn, including VRAM/stability observations.
2. **2D VAD:** add explicit-start VAD auto-stop while keeping manual stop.
3. **2E Interruption:** allow user speech to stop TTS playback and begin a new turn.
4. **2F Streaming/performance:** evaluate streaming ASR/TTS and sentence-level synthesis based on measured latency.

Do not begin Stage 3 long-term memory until Stage 2 acceptance is actually complete and recorded.

## 15. Self-review

- The design is limited to Stage 2 voice functionality.
- It composes existing ASR, chat, and TTS APIs instead of changing core backend architecture.
- It preserves text as the internal exchange format.
- It requires explicit confirmation before ASR text reaches the LLM.
- It keeps raw audio non-persistent by default.
- It does not implement VAD, interruption, streaming, memory, or emotion.
- It defines testable acceptance criteria before any status update.
