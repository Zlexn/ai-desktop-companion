# 2C-2 Real-provider Full-turn Smoke Design

> Status: design for the next Stage 2 voice validation task. This document does not implement code, change runtime behavior, add long-term memory, or add emotion.

**Current phase:** Stage 2 — voice features.

**Goal:** Validate and record one complete real-provider half-duplex voice turn using the existing Stage 2C frontend orchestration: real FasterWhisper ASR, a real configured LLM provider, and CosyVoice HTTP TTS.

**Recommended implementation shape:** Semi-automated smoke runner plus manual microphone/playback confirmation. Keep this as a validation and evidence task unless the smoke exposes a small, directly related defect.

---

## 1. Context

The project has already completed the fake-provider 2C-1 baseline:

```text
record/transcribe -> pending transcript -> 发送并朗读 -> text chat -> matching assistant reply -> TTS playback
```

The remaining 2C gap is not a new product feature. It is proof that the same path works when all three providers are real:

- ASR: `ASR_PROVIDER=faster-whisper` with the current C3 GPU candidate, or the documented C4 CPU fallback if needed.
- LLM: a real provider configured through local secret environment variables.
- TTS: `TTS_PROVIDER=cosyvoice-http` with the local CosyVoice OpenAI-compatible smoke server running.

This task remains inside Stage 2. It must not add long-term memory, emotional state, VAD, interruption, streaming ASR/TTS, wake-word behavior, or audio device management.

## 2. Recommended next task

The next minimal closed-loop task is **2C-2 Real-provider full-turn smoke**.

The task should answer one question:

> Can the current app complete a browser voice turn with real ASR, real LLM, and real TTS, while preserving the 2C-1 text fallback and privacy boundaries?

If the answer is yes, record the evidence and update status. If the answer is no, record the exact failing step and define the next smallest repair task. Do not broaden the work into a redesign unless the evidence shows the current client orchestration cannot support the path.

## 3. Scope

### In scope

- Add or refine a local smoke script/checklist for 2C-2.
- Check that the CosyVoice HTTP smoke server is reachable before starting the main app flow.
- Start or document the main backend with explicit real-provider environment variables.
- Start or document the frontend dev server.
- Drive a browser through one full voice turn:
  1. record microphone audio;
  2. receive a real ASR transcript;
  3. click `发送并朗读`;
  4. receive a real assistant text reply;
  5. synthesize and play the assistant reply through CosyVoice HTTP.
- Capture browser console errors, API request status, and provider metadata when available.
- Record GPU/VRAM or model co-residency observations if visible from existing tools/logs.
- Update `docs/stage2c-half-duplex-voice-turn.md`, `README.md`, and `CLAUDE.md` only after the smoke evidence is known.

### Out of scope

- No backend `/voice-turns` endpoint.
- No database schema changes.
- No persistence of raw microphone audio or generated TTS audio.
- No unauthorized voice cloning, voice actor imitation, celebrity voice, or copyrighted character asset claim.
- No VAD, automatic send, wake word, background listening, interruption, streaming, audio device picker, long-term memory, or emotion system.
- No key printing, `.env` dumping, committed recordings, committed generated audio, or committed model cache files.

## 4. Approach

Use a **semi-automated smoke runner plus manual confirmation**.

The runner should automate the parts that are reliable and safe to automate:

- Verify required local services and environment are present.
- Start or reuse backend and frontend processes where practical.
- Open a browser context with console/error collection.
- Guide the operator through the microphone and playback steps.
- Save a concise evidence summary without secrets or private audio.

The operator confirms the parts that are inherently local/hardware-dependent:

- Microphone permission and spoken test phrase.
- Whether the transcript is plausible for the spoken phrase.
- Whether audible CosyVoice playback occurs.

This is preferred over a fully automated E2E test because microphone input, real LLM variability, and audible playback assertions are not stable enough for a normal regression suite yet. Existing fake-provider Playwright coverage remains the automated regression guard for the 2C UI state machine.

## 5. Expected smoke flow

### Pre-flight

1. Confirm the working tree does not contain unexpected secret or audio artifacts.
2. Confirm `DEEPSEEK_API_KEY` or the selected real LLM provider key exists without printing its value.
3. Confirm the FasterWhisper model path exists.
4. Confirm the CosyVoice HTTP server is responding at `TTS_COSYVOICE_BASE_URL`.
5. Confirm the main backend and frontend ports are free or intentionally reused.

### Runtime configuration

Recommended C3 ASR configuration:

```powershell
$env:ASR_PROVIDER = "faster-whisper"
$env:ASR_FASTER_WHISPER_MODEL_PATH = "$env:USERPROFILE\.cache\huggingface\hub\models--Systran--faster-whisper-medium\snapshots\08e178d48790749d25932bbc082711ddcfdfbc4f"
$env:ASR_FASTER_WHISPER_MODEL_NAME = "medium"
$env:ASR_FASTER_WHISPER_MODEL_REVISION = "08e178d48790749d25932bbc082711ddcfdfbc4f"
$env:ASR_FASTER_WHISPER_DEVICE = "cuda"
$env:ASR_FASTER_WHISPER_COMPUTE_TYPE = "float16"
$env:ASR_FASTER_WHISPER_BEAM_SIZE = "1"
$env:ASR_FASTER_WHISPER_TIMEOUT_SECONDS = "30"
```

Recommended TTS configuration:

```powershell
$env:TTS_PROVIDER = "cosyvoice-http"
$env:TTS_DEFAULT_VOICE = "default-zh-female"
$env:TTS_COSYVOICE_BASE_URL = "http://127.0.0.1:8001"
$env:TTS_COSYVOICE_MODEL = "Fun-CosyVoice3-0.5B-2512"
$env:TTS_COSYVOICE_TIMEOUT_SECONDS = "90"
```

Real LLM configuration should use the existing provider docs. The smoke script may check that the selected key environment variable exists, but it must never print the value, length, or prefix.

### Browser steps

1. Open the app.
2. Create or select a test session.
3. Start recording.
4. Speak a short, non-private Chinese sentence for smoke validation.
5. Stop recording and wait for the real ASR transcript.
6. Click `发送并朗读`.
7. Wait for the user and assistant messages to appear.
8. Wait for `/api/audio/speech` to return audio.
9. Confirm audible playback.
10. Record any console errors or unexpected UI errors.

## 6. Success criteria

2C-2 passes only when all required evidence is recorded:

1. Real FasterWhisper ASR is enabled and produces a transcript from microphone input.
2. The transcript is not automatically sent before explicit confirmation.
3. `发送并朗读` sends the transcript through the normal text-chat path.
4. A real LLM provider produces the assistant text reply.
5. CosyVoice HTTP is called through the main backend TTS provider.
6. The browser plays the synthesized assistant reply.
7. Text messages remain visible even if a later TTS/playback step fails.
8. Browser console errors are captured and either zero or documented.
9. Provider/model metadata and exact non-secret environment choices are recorded.
10. No secrets, raw audio, generated audio, or model cache files are committed.

If any required step fails, the task result is **not complete**. Record the failing step and keep `CLAUDE.md` clear that 2C-2 remains incomplete.

## 7. Error handling and fallback expectations

- **CosyVoice server unavailable:** mark smoke blocked; do not change app architecture.
- **ASR model load failure or OOM:** try the documented C4 CPU fallback only if appropriate; otherwise record the failure.
- **LLM key missing:** mark smoke blocked by local secret configuration; do not print or request the key value in logs.
- **Chat succeeds but TTS fails:** record partial success; verify text messages remain visible; do not mark 2C-2 fully complete.
- **Browser microphone permission denied:** record as environment failure; do not persist audio or add background capture behavior.
- **Console errors:** include count and short non-sensitive descriptions in the evidence doc.

## 8. Files likely to change

Expected files:

- `scripts/smoke_real_full_turn_ui.ps1` or similar
  - Optional semi-automated runner/checklist for the 2C-2 smoke.
- `scripts/smoke_real_full_turn_ui.cmd` or similar
  - Optional Windows command wrapper matching the existing smoke script style.
- `docs/stage2c-half-duplex-voice-turn.md`
  - Record 2C-2 result, exact commands, provider metadata, console observations, and limitations.
- `README.md`
  - Update Stage 2 status only after evidence is known.
- `CLAUDE.md`
  - Update the official phase status only after evidence is known.

No backend or frontend runtime code is expected to change unless the smoke exposes a directly related defect in the already implemented 2C-1 path.

## 9. Validation plan

### Primary validation

Run the real-provider browser smoke and record:

- ASR provider/model/revision/device/compute type.
- LLM provider/model name, without secrets.
- TTS provider/model/base URL host only.
- Whether transcript appeared.
- Whether chat reply appeared.
- Whether TTS request succeeded.
- Whether audible playback was confirmed.
- Console error count.
- Any GPU/VRAM or co-residency observations available from logs/tools.

### Regression validation

If only scripts/docs are changed, run the smoke and inspect the changed docs/scripts. Full backend/frontend regression is optional but recommended before marking 2C closed.

If runtime code is changed, run the normal regression suite:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -v
Push-Location frontend
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
Pop-Location
```

## 10. Security and privacy

- Do not record a private phrase; use a short non-sensitive smoke phrase.
- Do not commit raw recordings or generated TTS files.
- Do not print or commit API keys.
- Do not dump `.env`.
- Do not send microphone audio to the LLM provider; only confirmed ASR text goes through chat.
- Do not claim the voice is Yukinoshita Yukino, a voice actor, a celebrity, or any unauthorized person.
- Treat CosyVoice output in this task as technical local TTS smoke only.

## 11. Acceptance criteria

The task is complete when:

1. A real-provider full-turn smoke is executed or honestly recorded as blocked.
2. Evidence is written to `docs/stage2c-half-duplex-voice-turn.md`.
3. `README.md` and `CLAUDE.md` reflect exactly what happened.
4. If the smoke passes, 2C-2 is marked complete while Stage 2 remains `IMPLEMENTING` for VAD/interruption/streaming follow-ups.
5. If the smoke fails or is blocked, 2C-2 remains incomplete and the next smallest repair task is named.

## 12. Follow-up sequence after 2C-2

If 2C-2 passes, recommended next Stage 2 tasks are:

1. 2D VAD: explicit-start recording with auto-stop, manual stop retained.
2. 2E Interruption: user speech can stop TTS playback and start a new turn.
3. 2F Streaming/performance: evaluate lower-latency ASR/TTS and sentence-level synthesis.

Do not begin Stage 3 long-term memory until Stage 2 acceptance is actually complete and recorded.

## 13. Self-review

- The design stays within Stage 2 voice validation.
- The design does not add memory or emotion behavior.
- The design does not require a new backend orchestration endpoint.
- The design preserves explicit confirmation before ASR text reaches the LLM.
- The design keeps secrets, raw audio, generated audio, and model caches out of git.
- The design defines pass, fail, and blocked outcomes without ambiguity.
