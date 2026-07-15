# Stage 4D ExpressionPlan / TTS Expression

> Verdict: **VERIFIED PASS (fake-first)**  
> Date: 2026-07-14  
> Real CosyVoice smoke: **BLOCKED / 未运行（未显式配置并授权真实本地 CosyVoice 服务）**

## Scope

Stage 4D adds a bounded, provider-neutral, assistant-message-bound `ExpressionPlan` and applies its safe subset to TTS. It preserves the existing text reply as the authoritative result: plan generation, plan persistence, provider mapping, synthesis, streaming, and playback failures cannot roll back or hide a persisted assistant reply.

This milestone implements only ExpressionPlan and TTS expression. It does not implement Live2D, character motion, a desktop shell, background listening, persistent audio caching, or unverified character/voice assets.

## Architecture delivered

### One pre-reply snapshot

`ChatService` reads the committed emotion snapshot at most once before LLM generation. The exact same `EmotionState` object is used for:

- the bounded text expression context; and
- deterministic ExpressionPlan derivation.

The assistant message is persisted before the plan side effect. The current turn's local emotion update and optional Stage 4C analysis still run after plan creation and affect later turns only.

If snapshot reading fails, chat continues without emotion context or a personalized plan. If plan creation fails after message persistence, the reply still returns and later post-turn side effects still run.

### Versioned, message-bound persistence

`expression_plans` stores one immutable plan for each `(assistant_message_id, schema_version)`:

- `schema_version = 1`
- non-negative integer `source_emotion_version`
- `delivery`: `neutral | warm | reassuring | reserved | firm`
- bounded `rate` in `[0.90, 1.10]`
- `intensity`: `low | medium`

Domain and SQLite constraints reject non-finite rates, bool/float version values, invalid enums, out-of-range values, and duplicate message/schema plans. Message/session deletion cascades to plans. Unique-race recovery rolls back the losing SQLite transaction before returning the existing plan, so it does not retain a write lock.

Plans do not persist message text, full emotion vectors, memories, prompts, SSML, free-form style, provider options, credentials, or provider payloads.

### Deterministic expression policy

The v1 ordered policy is:

| Condition | Delivery | Rate | Intensity |
|---|---|---:|---|
| high concern | reassuring | 0.94 | medium |
| high irritation and high formality | firm | 0.94 | medium |
| high trust and low distance | warm | 1.04 | medium |
| high distance or high formality | reserved | 0.94 | low |
| otherwise | neutral | 1.00 | low |

The policy shares the text formatter's `0.34` / `0.67` bucket boundaries. Disabled or invalid snapshots do not generate a personalized plan. Missing, corrupt, or incompatible plans resolve to an in-memory neutral `1.0` fallback without writing a fake source version or recomputing from current emotion.

### Message-bound TTS and provider isolation

The backend now exposes:

```text
POST /api/messages/{assistant_message_id}/speech
POST /api/messages/{assistant_message_id}/speech/stream
```

The request body allows only `voice_id` and `speed`; Pydantic rejects `text`, `delivery`, `intensity`, `style`, `ssml`, and provider options. The backend reads the persisted assistant message and plan by ID, validates the user speed, computes:

```text
final_speed = clamp(plan.rate * user_speed, 0.5, 2.0)
```

and calls the existing TTS service. Streaming and non-streaming share the same resolution and provider-neutral mapping. Unknown messages return 404; non-assistant messages return a TTS request error.

Current Fake and CosyVoice HTTP providers keep their existing `text / voice_id / speed` contract. `delivery` and `intensity` are safely ignored because those provider capabilities have not been verified. CosyVoice payload tests continue to permit only the existing OpenAI-compatible fields and `stream=true` on streaming calls.

Legacy `/api/audio/speech` and `/api/audio/speech/stream` remain available and plan-independent.

### Failure and privacy boundaries

- Plan creation is a best-effort side effect after assistant persistence.
- TTS timeout, provider failure, invalid audio, and playback failure affect only the audio request/state.
- Pre-start streaming failures preserve normal 422/502/504 HTTP mapping.
- Post-start streaming failures emit a fixed generic NDJSON error and never include provider error text, internal URLs, or tokens.
- The frontend keeps assistant text visible and permits retry after audio failure.
- Voice turns and history playback bind directly to `assistant_message_id`; transcript/diff heuristics were removed.
- Session/generation stale guards, recording interruption, Blob URL cleanup, stream scheduler fallback, stop/replay, and output-device behavior remain covered.

## Automated verification

### Backend

The final complete backend suite was run with both the backend and repository root on `PYTHONPATH`, which is required by the pre-existing `backend/tests/test_cosyvoice_text.py` import:

```text
617 passed in 33.55s
```

The first complete invocation used only the backend on `PYTHONPATH` and stopped during collection because the pre-existing test imports `scripts.cosyvoice_text` from the repository root. An import probe confirmed the environment cause; adding the repository root produced the successful complete result above. No product code change was needed for that collection issue.

### Project-level tests

```text
54 passed in 2.14s
```

This includes the Stage 4D E2E database verifier tests, including missing/empty table, orphan, role mismatch, duplicate plan, invalid v1 values, non-finite rate, and case-insensitive forbidden-column checks.

### Frontend

```text
Vitest: 20 files, 178 tests passed
TypeScript: tsc -b passed
Vite production build: passed (36 modules transformed)
```

The obsolete transcript-matching `voiceTurn.ts` and its tests were removed after explicit user authorization. The complete Vitest suite then passed.

### Browser E2E

```text
9 passed (14.8s)
PASS: Stage 4C E2E analysis tables are metadata-only (jobs=1, audits=1, outcome=applied)
PASS: Stage 4D E2E expression plans satisfy persistence invariants
```

The E2E environment explicitly pins fake TTS. Browser assertions prove:

- voice turn uses the exact `assistant_message_id` returned by chat;
- the message-bound stream body contains no text/expression/provider fields;
- historical playback uses the assistant message ID and reuses the same ID after refresh;
- normal chat, memories, emotion, recording UI, and Stage 4C continue to work;
- teardown verifies Stage 4C and Stage 4D before best-effort database/WAL/SHM cleanup and preserves primary verification errors.

## Runtime verification observations

An isolated backend was started on loopback with:

- a uniquely named SQLite database;
- fake LLM;
- fake session summary provider;
- fake TTS;
- environment proxy bypass for loopback requests.

Observed success flow:

```text
health: 200
chat assistant ID matched the persisted assistant message: true
message-bound non-stream speech: 200, valid RIFF/WAVE, 12,844 bytes
message-bound stream: start + 11 segments + done
client text/style injection: 422
assistant text remained persisted after failed speech request: true
```

Direct inspection of the isolated SQLite file showed a v1 plan whose assistant ID matched the chat response and whose related message role was `assistant`:

```text
schema_version=1
source_emotion_version=0
delivery=neutral
rate=1.0
intensity=low
```

A second isolated runtime used `TTS_FAKE_MODE=error`:

```text
chat: 200
message-bound speech: 502 / tts_unavailable
assistant message still persisted with non-empty text: true
```

Both uvicorn processes were stopped after observation. The isolated verification database is a newly created test artifact, not a user/pre-existing database.

## Review evidence

The implementation was reviewed after every TDD task. Review-discovered issues were fixed and regression-tested, including:

- integer/bool version constraints;
- SQLite rollback after a unique-plan race;
- post-start provider error text leakage;
- exact E2E response-ID binding;
- teardown error priority and complete best-effort cleanup;
- case-insensitive forbidden-column verification;
- strict real-smoke WAV/NDJSON validation and cleanup semantics;
- bool segment-index rejection.

A final independent Stage 4D correctness/security review reported **PASS** with no remaining reproducible findings. A four-angle cleanup review identified duplicated stream event orchestration and duplicated DI construction; these were locally consolidated without behavior changes. Potential joined-query optimization and removal of a redundant index were intentionally skipped because they would add repository/schema churn for negligible Stage 4D benefit.

`git diff --check` passed. No files were staged or committed.

## Real CosyVoice boundary

The offline CosyVoice smoke harness and adapter contract tests passed. The harness requires `STAGE4D_REAL_COSYVOICE=1`, validates non-stream WAV and strict `start → ordered segment(s) → done` NDJSON, checks cleanup, writes no audio files, and does not print replies/provider payloads.

No explicitly configured and authorized real local CosyVoice service was provided for this run, so:

```text
Real CosyVoice smoke: BLOCKED / 未运行
```

This does not claim acoustic delivery/intensity quality. A future provider-specific task must establish an authorized voice, verified capability fields, and listening/evaluation criteria before claiming expressive acoustic quality.

## Known limitations

- Current real provider mapping uses speed only; `delivery` and `intensity` remain provider-neutral metadata.
- No pitch, energy, emotion, free-form style, or SSML support is claimed.
- Audio is not persistently cached.
- Real CosyVoice protocol availability and acoustic quality were not verified in this run.
- Live2D, desktop shell, background listening, and expression animation remain outside Stage 4D.
