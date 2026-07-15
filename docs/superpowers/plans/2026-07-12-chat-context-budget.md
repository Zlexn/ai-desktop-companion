# Chat Provider Context Character Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Bound final chat Provider input to a configurable character budget while preserving the role system prompt and current user message.

**Architecture:** Keep persistence and `ContextBuilder` unchanged. Add one positive setting and one deterministic final-boundary helper in `ChatService`; it removes whole soft messages in an explicit priority order immediately before `LLMProvider.generate()`.

**Tech Stack:** Python 3.11+, dataclasses, FastAPI settings/dependency wiring, existing `LLMMessage` model, pytest, pytest-asyncio.

---

## Scope and protected baseline

- Design source: `docs/superpowers/specs/2026-07-12-chat-context-budget-design.md`.
- In scope: `CHAT_CONTEXT_MAX_CHARACTERS`, final Provider-message pruning, tests, and Stage 3/3M regression verification.
- Out of scope: tokenizer dependencies, per-Provider budgets, individual-message truncation, summary injection, automatic conflict resolution, MemoryPanel editing, Stage 4, or unrelated refactoring.
- Preserve the existing mixed Stage 3M WIP. Do not reset, checkout, amend, commit, delete `.superpowers/`, or touch user databases.
- The historical failing test is the RED starting point; do not weaken or delete it.

## File structure

### Modify

- `.env.example` — document the safe default.
- `backend/app/core/config.py` — add the setting, positive integer parsing, and redacted diagnostics.
- `backend/app/services/chat_service.py` — prune the complete Provider message list before generation.
- `backend/tests/conftest.py` — clear the new variable so tests remain deterministic.
- `backend/tests/test_config.py` — default/override/invalid/redacted behavior.
- `backend/tests/test_chat_service.py` — retention priority, order, overflow, persistence, and existing regression.
- `docs/stage3m-session-summary-generation.md` or a Stage 3 closeout evidence file — update only with observed rerun results; do not rewrite 3M behavior.

No repository, schema, frontend, summary, memory, or Provider adapter file should change.

---

### Task 1: Add the configurable positive character budget

**Files:**
- Modify: `.env.example`
- Modify: `backend/app/core/config.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_config.py`

- [x] **Step 1: Add failing default and override tests**

Add the environment name to the cleanup fixture and tests equivalent to:

```python
def test_chat_context_max_characters_defaults_to_24000(monkeypatch):
    monkeypatch.delenv("CHAT_CONTEXT_MAX_CHARACTERS", raising=False)

    settings = load_settings()

    assert settings.chat_context_max_characters == 24_000
    assert settings.redacted()["chat_context_max_characters"] == 24_000


def test_chat_context_max_characters_accepts_positive_override(monkeypatch):
    monkeypatch.setenv("CHAT_CONTEXT_MAX_CHARACTERS", "12000")

    settings = load_settings()

    assert settings.chat_context_max_characters == 12_000
```

- [x] **Step 2: Run the tests and verify RED**

```powershell
python -m pytest backend/tests/test_config.py -k chat_context_max_characters -q
```

Expected: FAIL because `Settings` lacks `chat_context_max_characters`.

- [x] **Step 3: Add failing invalid-value tests**

```python
@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer"])
def test_chat_context_max_characters_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("CHAT_CONTEXT_MAX_CHARACTERS", value)

    with pytest.raises(ValueError, match="CHAT_CONTEXT_MAX_CHARACTERS"):
        load_settings()
```

Run the same focused command. Expected: FAIL until parsing is implemented.

- [x] **Step 4: Implement the minimal setting**

Add to `Settings` beside `recent_context_messages`:

```python
chat_context_max_characters: int = 24_000
```

In `load_settings()`, populate it using the existing positive-integer environment helper:

```python
chat_context_max_characters=_get_positive_int_env(
    "CHAT_CONTEXT_MAX_CHARACTERS",
    24_000,
),
```

Add to `Settings.redacted()`:

```python
"chat_context_max_characters": self.chat_context_max_characters,
```

Add to `.env.example` near chat model/context settings:

```dotenv
# Maximum total characters sent to the chat Provider. Role prompt and current user text are always preserved.
CHAT_CONTEXT_MAX_CHARACTERS=24000
```

Add `CHAT_CONTEXT_MAX_CHARACTERS` to the test environment cleanup tuple.

- [x] **Step 5: Verify configuration GREEN**

```powershell
python -m pytest backend/tests/test_config.py -k chat_context_max_characters -q
python -m pytest backend/tests/test_config.py -q
```

Expected: all selected and complete config tests PASS.

Do not commit; preserve the mixed WIP.

---

### Task 2: Make the existing large-history regression pass at the final Provider boundary

**Files:**
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/tests/test_chat_service.py`

- [x] **Step 1: Re-run the existing regression and capture RED**

```powershell
python -m pytest backend/tests/test_chat_service.py::test_chat_service_prunes_old_history_before_provider_when_context_is_large -q
```

Expected: FAIL because old history remains and total content exceeds 24,000 characters.

- [x] **Step 2: Add the minimal private helper contract**

In `ChatService`, add a static/private helper with this exact shape:

```python
@staticmethod
def _fit_provider_messages(
    messages: list[LLMMessage],
    max_characters: int,
) -> list[LLMMessage]:
    if len(messages) <= 2:
        return messages

    kept = list(messages)
    while sum(len(message.content) for message in kept) > max_characters and len(kept) > 2:
        removable_index = next(
            (
                index
                for index, message in enumerate(kept[1:-1], start=1)
                if message.role in {ChatRole.USER, ChatRole.ASSISTANT}
            ),
            None,
        )
        if removable_index is None:
            removable_index = 1
        kept.pop(removable_index)
    return kept
```

This preserves the first role system prompt and final current user message, removes oldest historical user/assistant segments first, then optional system blocks, and allows hard-message overflow.

- [x] **Step 3: Call the helper at the only correct boundary**

Change the final assembly from:

```python
provider_messages = [LLMMessage(role=ChatRole.SYSTEM, content=system_prompt), *context]
```

To:

```python
provider_messages = self._fit_provider_messages(
    [LLMMessage(role=ChatRole.SYSTEM, content=system_prompt), *context],
    self._settings.chat_context_max_characters,
)
```

Do not modify persisted messages or `ContextBuilder`.

- [x] **Step 4: Verify the existing regression becomes GREEN**

```powershell
python -m pytest backend/tests/test_chat_service.py::test_chat_service_prunes_old_history_before_provider_when_context_is_large -q
```

Expected: PASS; role prompt and current message remain, old history is removed, and final character count is at most 24,000.

---

### Task 3: Lock retention priority and overflow behavior

**Files:**
- Modify: `backend/tests/test_chat_service.py`
- Modify only if a new test exposes a design mismatch: `backend/app/services/chat_service.py`

- [x] **Step 1: Write a failing oldest-history-first test**

Use `Settings(chat_context_max_characters=<small deterministic value>)`, persisted old/new history, and `FakeProvider`. Assert:

```python
sent = provider.calls[0]
assert sent[0].role is ChatRole.SYSTEM
assert sent[-1] == LLMMessage(role=ChatRole.USER, content=current_text)
assert "oldest-history" not in [message.content for message in sent]
assert "newest-history" in [message.content for message in sent]
```

Run only that test; expected RED if priority is wrong, then make the smallest helper correction.

- [x] **Step 2: Write a memory-preservation test**

Create active memory and enough old history that removing old history alone reaches budget. Assert the retained system messages still include the standard memory disclaimer and memory content.

```python
assert any("可能过时或不完整" in message.content for message in sent)
assert any("existing-memory" in message.content for message in sent)
```

Expected: PASS after Task 2 helper if budget values are selected correctly.

- [x] **Step 3: Write a memory-removal-after-history test**

Use a large memory block and no removable history beyond the current user message. Set a budget smaller than role + memory + current but larger than role + current. Assert:

```python
assert sent[0].role is ChatRole.SYSTEM
assert sent[-1].content == current_text
assert all("large-memory" not in message.content for message in sent)
assert sum(len(message.content) for message in sent) <= settings.chat_context_max_characters
```

- [x] **Step 4: Write a hard-preserved overflow test**

Call through `ChatService` with a current message whose length plus role prompt exceeds the small budget. Assert both are unchanged and total content exceeds the configured budget by design:

```python
assert sent[0].content == default_prompt_renderer().render()
assert sent[-1].content == current_text
assert sum(len(message.content) for message in sent) > settings.chat_context_max_characters
```

- [x] **Step 5: Prove persistence is untouched**

After a pruned Provider call, list repository messages and assert every seeded historical message plus the new user/assistant messages remains stored in insertion order. The helper affects only outbound `LLMMessage` objects.

- [x] **Step 6: Run the complete ChatService suite**

```powershell
python -m pytest backend/tests/test_chat_service.py -q
```

Expected: all ChatService tests PASS, including the former baseline failure.

---

### Task 4: Verify Stage 3 closeout and preserve Stage 3M boundaries

**Files:**
- No product changes unless a new regression directly identifies a defect.
- Update evidence only from observed output.

- [x] **Step 1: Run focused config/chat tests**

```powershell
python -m pytest backend/tests/test_config.py backend/tests/test_chat_service.py -q
```

Expected: PASS with no historical context-pruning failure.

- [x] **Step 2: Run Stage 3M production-composition regressions**

```powershell
python -m pytest `
  backend/tests/test_session_summaries.py `
  backend/tests/test_session_summary_sanitizer.py `
  backend/tests/test_session_summary_provider.py `
  backend/tests/test_session_summary_service.py `
  backend/tests/test_api_chat.py -q
```

Expected: PASS. Summary remains nonblocking, independently stored, absent from chat context, and isolated from memories/embeddings.

- [x] **Step 3: Run the complete backend suite**

```powershell
python -m pytest backend/tests -q
```

Expected: fully green. Based on the current 399-test suite plus new tests, the exact count will increase; record the actual count and exit status rather than predicting it in evidence.

- [x] **Step 4: Run a real fake-provider API smoke**

Launch an isolated backend with a unique SQLite file and a deliberately small positive budget. Use environment-proxy bypass and `--no-access-log`. Through HTTP:

1. create a session;
2. send enough large historical turns to require pruning;
3. send a current question;
4. observe HTTP 200 and persisted message history;
5. confirm server remains healthy.

Because the fake Provider exposes no public request-context endpoint, use the automated recording-provider test as the exact pruning evidence and the HTTP smoke as the real API health/persistence evidence.

- [x] **Step 5: Run code review and runtime verify**

Invoke `/code-review` on the context-budget diff and `/verify` on the chat API flow. Fix only confirmed issues inside this slice.

- [x] **Step 6: Update evidence and Stage 3 status only if all required checks pass**

Record:

- config/chat focused result;
- Stage 3M regression result;
- full backend result;
- HTTP smoke observation;
- code-review disposition.

Only after full backend is green may `CLAUDE.md` move Stage 3 toward closed/accepted. Do not mark MemoryPanel editing complete; retain it as a separate Stage 3 UI closeout item unless explicitly fixed and verified.

- [x] **Step 7: Final diff check**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; existing mixed WIP remains intact. Do not commit without explicit user instruction.

---

## Completion evidence

Implemented and verified on 2026-07-12 without committing the mixed working tree:

- focused configuration tests: 5 passed;
- combined configuration and ChatService tests: 83 passed;
- complete ChatService suite: 27 passed;
- Stage 3M production-composition regression set: 45 passed;
- complete backend suite: 410 passed;
- final Provider-boundary tests cover oldest-history-first removal, optional system-context priority, serialized system separators, hard-preserved overflow, and persistence isolation.

The configured budget is Provider-neutral and applies only to outbound `LLMMessage` objects. No summary injection, repository deletion, Provider adapter change, conflict automation, or Stage 4 behavior was added.

## Final acceptance checklist

- [x] Default and override character budgets are validated and visible in redacted settings.
- [x] Final Provider messages, not persisted data, are pruned.
- [x] Role system prompt and current user message are always preserved unchanged.
- [x] Oldest historical user/assistant messages are removed first.
- [x] Optional memory system context is retained when possible and removed only after history.
- [x] No individual message is truncated.
- [x] Hard-preserved overflow behavior is explicit and tested.
- [x] The former context-pruning baseline test passes.
- [x] Full backend suite is green.
- [x] Stage 3M nonblocking, storage, isolation, and no-injection tests remain green.
- [x] No summary injection, conflict automation, UI editing, or Stage 4 code was added.
