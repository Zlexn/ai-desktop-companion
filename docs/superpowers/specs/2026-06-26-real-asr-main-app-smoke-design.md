# 2B-6 Real ASR Main-App Smoke Design

> Status: design for the next Stage 2 voice task. This document does not implement VAD, full voice-turn orchestration, real TTS, long-term memory, or emotion.

**Current phase:** Stage 2 — voice features.

**Goal:** Verify that the existing FasterWhisper ASR provider works in the main application environment and current browser recording UI, not only in the isolated `.venv-asr-bench` smoke path.

**Architecture:** Keep the existing Stage 2B boundary: browser recording uploads audio to `POST /api/audio/transcriptions`, `ASRService` validates the upload and calls the selected `ASRProvider`, and transcription text returns to the editable frontend input. No chat message is created by the transcription endpoint, and text remains the internal exchange format.

---

## 1. Context

The project is currently in Stage 2. The following Stage 2 pieces are already complete:

- Stage 2A Fake TTS playback loop.
- Stage 2B manual browser recording UI with Fake ASR.
- Backend ASR foundation and multipart transcription API.
- ASR benchmark runner and C1-C4 benchmark matrix.
- FasterWhisper provider implementation baseline.

The remaining explicit blocker in `CLAUDE.md` is that the real ASR optional dependencies have not been installed into the main `.venv`, and the real provider has not been smoked through the main FastAPI process and browser recording UI.

## 2. Recommended next task

The next minimal closed-loop task is **2B-6 Real ASR Main-App Smoke & Documentation**.

This is smaller and safer than starting real TTS or Stage 2C because it validates the real ASR path already implemented in 2B-5. It also keeps Fake ASR as the default automated path, so normal tests remain offline and deterministic.

## 3. Scope

### In scope

- Install or verify the main `.venv` optional ASR dependencies declared by `backend[asr]`.
- Configure the main backend with `ASR_PROVIDER=faster-whisper` and a local FasterWhisper model snapshot.
- Run an API smoke against `POST /api/audio/transcriptions` using a non-private local test recording.
- Run a browser UI smoke through the existing manual recording UI and confirm the transcript enters the editable input.
- Preserve the default Fake ASR path for automated tests.
- Update `README.md`, `docs/stage2b5-real-asr-provider.md`, and `CLAUDE.md` with accurate evidence.

### Out of scope

- No new ASR provider.
- No final production ASR selection.
- No real TTS provider.
- No Stage 2C half-duplex voice-turn orchestration.
- No VAD, interruption, streaming ASR, streaming TTS, or audio device management.
- No long-term memory or emotion system.
- No raw audio persistence.

## 4. Configuration decision

Use the already benchmarked initial candidate C3 for the first main-app GPU smoke:

| Setting | Value |
|---|---|
| Provider | `faster-whisper` |
| Model | `medium` |
| Revision | `08e178d48790749d25932bbc082711ddcfdfbc4f` |
| Device | `cuda` |
| Compute type | `float16` |
| Beam size | `1` |
| Language | `zh` |

Keep C4 as the documented CPU fallback:

| Setting | Value |
|---|---|
| Model | `small` |
| Device | `cpu` |
| Compute type | `int8` |

The task must not claim this is the final production ASR selection. It is only the main-app smoke candidate.

## 5. Expected data flow

```text
Browser MediaRecorder blob
  -> POST /api/audio/transcriptions
  -> ASRService upload validation
  -> FasterWhisperASRProvider temporary file
  -> faster-whisper local model
  -> TranscriptionResponse JSON
  -> frontend editable message input
```

The endpoint still must not create chat messages. The user sends the resulting text manually through the existing text-chat path.

## 6. Files likely to change

- `README.md`
  - Bring Stage 2 status up to date.
  - Add real ASR setup and smoke instructions.
  - Correct obsolete text saying browser recording and real ASR are not available.
- `docs/stage2b5-real-asr-provider.md`
  - Add a 2B-6 addendum with main `.venv` and UI smoke evidence.
- `CLAUDE.md`
  - Update current Stage 2 status after validation.
  - Remove the blocker only if main `.venv` and UI smoke actually pass.
- Optional: a small local smoke helper may be added only if existing tools are insufficient; it must not contain private audio or hard-coded local-only paths.

## 7. Validation plan

Run automated regression first with default Fake ASR:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -v
Push-Location frontend
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
Pop-Location
```

Then validate real ASR in the main app environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e "backend[asr]"
```

Use local environment variables for the real ASR smoke, without committing `.env`:

```powershell
$env:ASR_PROVIDER = "faster-whisper"
$env:ASR_FASTER_WHISPER_MODEL_PATH = "<local medium snapshot path>"
$env:ASR_FASTER_WHISPER_MODEL_NAME = "medium"
$env:ASR_FASTER_WHISPER_MODEL_REVISION = "08e178d48790749d25932bbc082711ddcfdfbc4f"
$env:ASR_FASTER_WHISPER_DEVICE = "cuda"
$env:ASR_FASTER_WHISPER_COMPUTE_TYPE = "float16"
$env:ASR_FASTER_WHISPER_BEAM_SIZE = "1"
$env:ASR_FASTER_WHISPER_TIMEOUT_SECONDS = "30"
```

Smoke criteria:

- The main backend imports and lazy-loads the real provider without crashing.
- API transcription returns a non-empty transcript with provider metadata `faster-whisper`.
- Temporary audio is not persisted by application code.
- Browser manual recording sends audio to the real endpoint and places the transcript in the editable input.
- Text chat remains usable after transcription.

## 8. Error handling and fallback

If installation is blocked, document the exact blocked command and ask the user to run it manually with `! .\.venv\Scripts\python.exe -m pip install -e "backend[asr]"`.

If CUDA loading fails, do not rewrite the provider architecture. Try the documented CPU fallback only after recording the GPU failure:

```powershell
$env:ASR_FASTER_WHISPER_MODEL_PATH = "<local small snapshot path>"
$env:ASR_FASTER_WHISPER_MODEL_NAME = "small"
$env:ASR_FASTER_WHISPER_DEVICE = "cpu"
$env:ASR_FASTER_WHISPER_COMPUTE_TYPE = "int8"
```

If the model snapshot cannot be found, do not download silently unless the user has already allowed network and the command is safe. Record the missing path and use the existing model download script if needed.

## 9. Security and privacy

- Do not log raw audio.
- Do not commit `.env`, model files, cache files, or private recordings.
- Do not include private transcript text in docs unless it is a synthetic test sentence.
- Continue using Fake ASR for default tests.
- Keep real ASR opt-in through environment variables.

## 10. Acceptance criteria

The task is complete only if all applicable evidence is recorded:

1. Backend regression with Fake ASR passes.
2. Frontend unit/type/build/E2E checks pass or any failure is explicitly reported.
3. Main `.venv` can import and run `faster-whisper`, or installation is clearly blocked with the exact required user command.
4. Real ASR API smoke returns non-empty text from a non-private audio input.
5. Real ASR UI smoke records audio, transcribes it, and fills the editable input.
6. Documentation reflects exactly what passed and what remains incomplete.
7. Stage 2 remains `IMPLEMENTING`; Stage 3 and Stage 4 remain not started.

## 11. Self-review

- Scope is limited to the existing ASR provider and current UI path.
- The design does not implement or assume real TTS, VAD, interruption, streaming, memory, or emotion.
- The default Fake ASR test path remains intact.
- The design avoids saving raw audio or committing local secrets/cache paths.
- The success criteria require actual verification before status is changed.
