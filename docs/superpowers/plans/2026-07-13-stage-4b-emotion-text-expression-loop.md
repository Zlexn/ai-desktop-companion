# Stage 4B Emotion Text Expression Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inject a short deterministic expression-policy system message from the committed emotion snapshot into each chat request, while preserving role/current-user/emotion budget priority and keeping all emotion failures non-blocking.

**Architecture:** A pure `EmotionContextFormatter` converts enabled Stage 4A state into bounded discrete labels. `ContextBuilder` receives narrow reader/formatter protocols and returns emotion before memory/history. `ChatService` receives explicit context-priority metadata so its character budget removes old history and memory before the protected emotion message; post-turn emotion updates remain after assistant persistence and affect only the next request.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, pytest, existing `LLMMessage`/Provider adapters; no frontend product change except regression validation.

---

## Files

- Create: `backend/app/services/emotion_context.py` — snapshot reader protocol, formatter protocol, deterministic formatter, max length.
- Modify: `backend/app/services/context_builder.py` — optional emotion context and fault isolation.
- Modify: `backend/app/services/chat_service.py` — explicit protected context priority during budget fitting.
- Modify: `backend/app/api/dependencies.py` — inject Stage 4A EmotionService and formatter into ContextBuilder.
- Create: `backend/tests/test_emotion_context.py` — formatter contract.
- Modify: `backend/tests/test_context_builder.py` — ordering, disabled, reader/formatter failure.
- Modify: `backend/tests/test_chat_service.py` — budget priority and turn timing.
- Modify: `backend/tests/test_api_chat.py` — real DI/provider payload composition.
- Create: `docs/stage4b-emotion-text-expression-loop.md` — observed evidence.
- Modify: `README.md`, `CLAUDE.md` — status after fresh validation.

Do not modify Prompt template files, EmotionPolicy transition rules, emotion tables/API, LLM provider implementations, TTS, frontend expression behavior, consent, or desktop assets.

### Task 1: TDD the Deterministic Formatter

**Files:**
- Create: `backend/tests/test_emotion_context.py`
- Create: `backend/app/services/emotion_context.py`

- [ ] Write failing tests for enabled baseline, low/high vectors, disabled None, determinism, no decimal dump, fixed safety text, and `len(output) <= 500`.

Use immutable `EmotionState` fixtures and assert phrases including `表达策略`、`不代表真实感情或意识`、`不得改变事实、安全要求、用户明确指令或角色边界`.

- [ ] Run:

```powershell
python -m pytest backend/tests/test_emotion_context.py -q
```

Expected: missing module failure.

- [ ] Implement protocols and formatter:

```python
class EmotionSnapshotReader(Protocol):
    def get_state(self, *, apply_decay: bool = True) -> EmotionState: ...

class EmotionContextFormatterProtocol(Protocol):
    def format(self, state: EmotionState) -> str | None: ...

MAX_EMOTION_CONTEXT_CHARACTERS = 500
```

Bucket function: `<0.34`, `<0.67`, else high. Use fixed phrase tuples for each dimension and one fixed safety preamble. Raise `ValueError` if generated content exceeds max; return None if disabled.

- [ ] Rerun formatter tests; expected PASS.

### Task 2: TDD ContextBuilder Injection and Failure Isolation

**Files:**
- Modify: `backend/tests/test_context_builder.py`
- Modify: `backend/app/services/context_builder.py`

- [ ] Add failing tests with fake reader/formatter:
  - enabled order is emotion system, memory system, chronological history;
  - disabled formatter None produces memory/history only;
  - reader raises and formatter raises both fall back to memory/history;
  - emotion context is not written to messages/memories.

- [ ] Run focused tests and observe missing constructor/API failure.

- [ ] Add optional constructor fields:

```python
emotion_snapshot_reader: EmotionSnapshotReader | None = None
emotion_context_formatter: EmotionContextFormatterProtocol | None = None
```

Add `build_emotion_context()` with try/except Exception and return 0/1 SYSTEM messages. `build_context` concatenates emotion, memory, recent.

- [ ] Rerun `test_context_builder.py`; expected PASS.

### Task 3: TDD Explicit Budget Priority

**Files:**
- Modify: `backend/tests/test_chat_service.py`
- Modify: `backend/app/services/chat_service.py`

- [ ] Add tests defining a protected-context wrapper:

```python
@dataclass(frozen=True)
class ProviderContext:
    messages: list[LLMMessage]
    protected_system_messages: int = 0
```

Alternatively use a named `protected_system_messages` integer returned by ContextBuilder; choose one explicit type and use it consistently.

Required cases:
1. delete oldest history first while emotion and memory remain;
2. after history removal delete memory before emotion;
3. role+emotion+current user may exceed budget unchanged;
4. no emotion keeps existing memory behavior.

- [ ] Run focused budget tests and confirm current algorithm fails case 2.

- [ ] Implement explicit protection. Recommended minimal signature:

```python
_fit_provider_messages(messages, max_characters, *, protected_system_messages=0)
```

Protected system messages are immediately after role prompt. Removal searches unprotected history first, then unprotected system messages; never removes first role, protected expression messages, or last current user.

- [ ] Rerun all ChatService tests; expected PASS.

### Task 4: Wire Reader/Formatter Through DI

**Files:**
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/tests/test_api_chat.py`

- [ ] Write failing composition tests using a recording provider and isolated SQLite:
  - enabled state produces role → emotion → memory/history/current user order;
  - API disable removes emotion from next provider payload;
  - no expression text is persisted as a Message;
  - Provider payload contains no raw six-float dump.

- [ ] Run and observe missing injection.

- [ ] In `get_chat_service`, inject existing request-connection `EmotionService` as snapshot reader and `EmotionContextFormatter()` into ContextBuilder. Avoid fresh connection for pre-provider reading; this also supports `sqlite:///:memory:`.

- [ ] Pass the number of built emotion messages to ChatService budget explicitly. Do not infer protection solely from role.

- [ ] Rerun API/chat/context tests; expected PASS.

### Task 5: Lock Current/Next-Turn Timing and Fault Isolation

**Files:**
- Modify: `backend/tests/test_chat_service.py`

- [ ] Add a mutable recording snapshot reader/updater test:
  - first request reads baseline formatter output;
  - updater changes snapshot only after assistant persistence;
  - second request gets updated expression;
  - first payload does not contain updated label.

- [ ] Add reader failure and formatter failure tests proving provider/reply/message persistence continue.

- [ ] Add updater failure test proving success is retained.

- [ ] Run focused suite; fix only integration defects, not behavior scope.

### Task 6: Full Verification and Runtime Observation

- [ ] Run focused:

```powershell
python -m pytest backend/tests/test_emotion_context.py backend/tests/test_context_builder.py backend/tests/test_chat_service.py backend/tests/test_api_chat.py -q
```

- [ ] Run full backend:

```powershell
python -m pytest backend/tests -q
```

- [ ] Run frontend regression:

```powershell
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

- [ ] Use `AI桌宠:verify` with unique SQLite/fake provider and a recording provider harness to observe:
  - baseline expression in first payload;
  - gratitude changes state after first reply;
  - second payload changes expression;
  - disabled state has no expression;
  - forced reader/formatter failure still returns reply;
  - tight budget removes history then memory, preserves emotion;
  - messages table contains no expression context;
  - no emotion LLM call and no TTS change;
  - cleanup.

### Task 7: Evidence, Review, and Status

- [ ] Create `docs/stage4b-emotion-text-expression-loop.md` with scope, formatter mapping, payload ordering, timing, budget, fault isolation, commands/counts, runtime evidence, security, limitations, PASS/BLOCKED.

- [ ] On PASS update:
  - `CLAUDE.md`: Stage 4 IMPLEMENTING; 4A/4B completed; NEXT 4C LLM-assisted analysis design.
  - `README.md`: same, explicitly state no remote emotion analysis/consent/TTS expression.

- [ ] Run code review on task-owned files; fix confirmed critical/high/medium correctness findings and rerun affected/full tests.

- [ ] Run `git diff --check` and inspect status. Do not stage or commit.

## Self-Review

- Covers formatter, ContextBuilder, explicit budget priority, DI, next-turn timing, fault isolation, recording payload, runtime and docs.
- No remote emotion LLM, consent, ExpressionPlan, TTS, desktop UI/assets.
- Protected budget is explicit rather than positional inference.
- Existing Stage 4A updater remains post-persistence.
- No placeholders; automatic execution is authorized, commit is not.
