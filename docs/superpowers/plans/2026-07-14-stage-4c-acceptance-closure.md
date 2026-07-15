# Stage 4C Acceptance Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce reproducible independent-process evidence that Stage 4C consent, DeepSeek HTTP analysis, local constraints, revocation, privacy, and fallback behavior work end to end, then truthfully close Stage 4C.

**Architecture:** Playwright starts a loopback-only fake DeepSeek-compatible HTTP server while the standard backend continues to use its production `DeepSeekProvider`. Browser assertions query the fake server's in-memory state and the normal product APIs; a focused Python verifier checks only metadata-only analysis tables after the servers stop. A separate opt-in script uses a real existing DeepSeek key with synthetic fixtures, while default automated verification remains deterministic and offline.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, SQLite, httpx, pytest, React, TypeScript, Vite, Vitest, Playwright.

---

## File Map

- Create `scripts/fake_deepseek_emotion_server.py`: loopback-only OpenAI-compatible deterministic test service and in-memory request recorder.
- Create `tests/test_fake_deepseek_emotion_server.py`: contract tests for request parsing, sanitization observability, state reset, and response shape.
- Create `scripts/verify_stage4c_e2e_database.py`: focused metadata-table privacy/count verifier and database cleanup helper.
- Create `tests/test_verify_stage4c_e2e_database.py`: verifier behavior tests against temporary SQLite fixtures.
- Modify `frontend/playwright.config.ts`: start the fake server and configure the standard backend to use it.
- Modify `frontend/e2e/emotion.spec.ts`: drive before-grant, grant, applied audit/state, revoke, zero-later-call, and local fallback flow.
- Modify `frontend/playwright.global-teardown.ts`: invoke the Python verifier after web servers stop, then remove database sidecars.
- Modify `frontend/playwright.global-teardown.test.ts`: test verifier invocation and cleanup behavior.
- Modify `backend/tests/test_emotion_analysis_runtime.py`: retain direct provider observation and add revoke/local-rule continuation coverage.
- Create `scripts/smoke_real_emotion_analysis.py`: explicit real-DeepSeek, synthetic-fixture smoke with temporary storage and redacted output.
- Create `backend/tests/test_smoke_real_emotion_analysis_script.py`: smoke argument/key-gating and result-reporting tests without network access.
- Create `docs/stage4c-llm-emotion-analysis-consent.md`: fresh acceptance evidence after all checks pass.
- Modify `README.md`: mark 4C complete only after PASS and state next scope accurately.
- Modify `CLAUDE.md`: mark 4A–4C complete and set next task to Stage 4D design only.

No commit is created because the user authorized execution but did not request a Git commit.

---

### Task 1: Loopback Fake DeepSeek HTTP Server

**Files:**
- Create: `scripts/fake_deepseek_emotion_server.py`
- Create: `tests/test_fake_deepseek_emotion_server.py`

- [ ] **Step 1: Write failing contract tests**

Create tests with FastAPI `TestClient` that reset state, send an OpenAI-compatible request containing the analyzer's JSON user message, and assert:

```python
response = client.post(
    "/chat/completions",
    headers={"Authorization": "Bearer stage4c-e2e-token"},
    json={
        "model": "stage4c-e2e-model",
        "messages": [
            {"role": "system", "content": "analysis system"},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "current_turn": {
                            "user_message_id": "user-1",
                            "user_content": "我今天很难受 [REDACTED]",
                            "assistant_message_id": "assistant-1",
                            "assistant_content": "我会陪你慢慢说。",
                        },
                        "recent_messages": [],
                        "memories": [],
                        "input_characters": 24,
                        "redaction_count": 1,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "max_tokens": 384,
        "stream": False,
        "thinking": {"type": "disabled"},
    },
)
assert response.status_code == 200
content = json.loads(response.json()["choices"][0]["message"]["content"])
assert content["source_ids"] == ["user-1", "assistant-1"]
assert content["schema_version"] == "emotion_analysis_v1"
state = client.get("/__test__/state").json()
assert state["request_count"] == 1
assert "stage4c-e2e-token" not in json.dumps(state)
```

Also test invalid bearer token returns `401`, malformed user content returns `422`, and `POST /__test__/reset` clears request count.

- [ ] **Step 2: Run tests and verify the module is absent**

Run from project root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fake_deepseek_emotion_server.py -q
```

Expected: collection/import failure because `scripts.fake_deepseek_emotion_server` does not exist.

- [ ] **Step 3: Implement the minimal fake server**

Implement a FastAPI `app` with:

```python
TEST_TOKEN = "stage4c-e2e-token"
REQUESTS: list[dict[str, object]] = []

@app.post("/chat/completions")
def chat_completions(request: Request, payload: ChatCompletionRequest) -> dict[str, object]:
    if request.headers.get("authorization") != f"Bearer {TEST_TOKEN}":
        raise HTTPException(status_code=401, detail="invalid test token")
    user_messages = [item for item in payload.messages if item.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=422, detail="missing user analysis payload")
    analysis_input = json.loads(user_messages[-1].content)
    current_turn = analysis_input["current_turn"]
    REQUESTS.append({
        "model": payload.model,
        "messages": [item.model_dump() for item in payload.messages],
        "max_tokens": payload.max_tokens,
        "stream": payload.stream,
        "thinking": payload.thinking,
    })
    proposal = {
        "schema_version": "emotion_analysis_v1",
        "should_apply": True,
        "signals": ["distress"],
        "proposed_delta": {
            "mood": -0.02,
            "trust": 0.0,
            "concern": 0.04,
            "distance": 0.0,
            "irritation": 0.0,
            "formality": 0.0,
        },
        "source_ids": [
            current_turn["user_message_id"],
            current_turn["assistant_message_id"],
        ],
        "reason_codes": ["user_distress"],
    }
    return {
        "id": f"stage4c-e2e-{len(REQUESTS)}",
        "model": payload.model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": json.dumps(proposal)},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
```

Expose `GET /__test__/state` with `request_count` and recorded request bodies, and `POST /__test__/reset`. Never store the authorization header.

- [ ] **Step 4: Run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fake_deepseek_emotion_server.py -q
```

Expected: all fake-server tests PASS.

---

### Task 2: Focused E2E Database Privacy Verifier

**Files:**
- Create: `scripts/verify_stage4c_e2e_database.py`
- Create: `tests/test_verify_stage4c_e2e_database.py`

- [ ] **Step 1: Write failing verifier tests**

Create temporary SQLite schemas containing `emotion_analysis_jobs` and `emotion_analysis_audits`. Test:

```python
verify_database(
    database_path,
    forbidden_markers=(
        "e2e-analysis-secret",
        "e2e-post-revoke-secret",
        "stage4c-e2e-token",
        "我今天很难受",
        "我需要帮助",
    ),
    expected_jobs=1,
    expected_audits=1,
    expected_outcome="applied",
)
```

A metadata-only fixture must pass. Parametrize fixtures that contain each marker in either analysis table and assert `VerificationError`. Test wrong counts and wrong outcome. Test `remove_database_files()` removes `.db`, `-wal`, and `-shm` but does not touch any other file.

- [ ] **Step 2: Run tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_verify_stage4c_e2e_database.py -q
```

Expected: import failure because the verifier does not exist.

- [ ] **Step 3: Implement verifier and CLI**

Implement:

```python
ANALYSIS_TABLES = ("emotion_analysis_jobs", "emotion_analysis_audits")

class VerificationError(RuntimeError):
    pass


def verify_database(
    database_path: Path,
    *,
    forbidden_markers: tuple[str, ...],
    expected_jobs: int,
    expected_audits: int,
    expected_outcome: str,
) -> None:
    connection = sqlite3.connect(database_path)
    try:
        jobs = connection.execute("SELECT * FROM emotion_analysis_jobs").fetchall()
        audits = connection.execute("SELECT * FROM emotion_analysis_audits").fetchall()
        if len(jobs) != expected_jobs or len(audits) != expected_audits:
            raise VerificationError("unexpected Stage 4C E2E job/audit counts")
        audit_columns = [item[1] for item in connection.execute(
            "PRAGMA table_info(emotion_analysis_audits)"
        )]
        outcome_index = audit_columns.index("outcome")
        if audits[0][outcome_index] != expected_outcome:
            raise VerificationError("unexpected Stage 4C E2E audit outcome")
        serialized = repr({"jobs": jobs, "audits": audits})
        leaked = [marker for marker in forbidden_markers if marker and marker in serialized]
        if leaked:
            raise VerificationError("forbidden Stage 4C marker found in analysis metadata tables")
    finally:
        connection.close()
```

The CLI accepts `--database`, repeated `--forbid`, `--expected-jobs`, `--expected-audits`, and `--expected-outcome`. It exits nonzero on failure and prints only safe summaries, never the leaked value.

- [ ] **Step 4: Run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_verify_stage4c_e2e_database.py -q
```

Expected: all verifier tests PASS.

---

### Task 3: Independent-Process Playwright Composition

**Files:**
- Modify: `frontend/playwright.config.ts:7-66`
- Modify: `frontend/e2e/emotion.spec.ts:1-33`

- [ ] **Step 1: Add the failing complete E2E flow**

Replace the deployment-disabled Stage 4C case with one test that:

```ts
const fakeProviderUrl = `http://127.0.0.1:${process.env.E2E_FAKE_DEEPSEEK_PORT ?? '18101'}`;

await page.goto('/');
await expect(page.getByText(/当前授权状态：unknown/)).toBeVisible();
await expect(page.getByText(/部署配置尚未开启/)).toHaveCount(0);

await page.getByRole('button', { name: '新建会话' }).click();
await page.getByLabel('输入消息').fill('今天只是普通的一天。');
await page.getByRole('button', { name: '发送' }).click();
await expect.poll(async () => (await page.request.get(`${fakeProviderUrl}/__test__/state`)).json())
  .toMatchObject({ request_count: 0 });

await page.getByRole('button', { name: '授权远程分析' }).click();
await page.getByRole('button', { name: '确认授权并允许发送' }).click();
await page.getByLabel('输入消息').fill('我今天很难受 token=e2e-analysis-secret');
await page.getByRole('button', { name: '发送' }).click();

await expect.poll(async () => {
  const response = await page.request.get('/api/emotion/analysis/audits');
  return (await response.json()).length;
}).toBe(1);

const providerState = await (await page.request.get(`${fakeProviderUrl}/__test__/state`)).json();
expect(providerState.request_count).toBe(1);
expect(JSON.stringify(providerState)).not.toContain('e2e-analysis-secret');
const analysisPayload = JSON.parse(providerState.requests[0].messages[1].content);
expect(analysisPayload.recent_messages.length).toBeLessThanOrEqual(6);
expect(analysisPayload.memories.length).toBeLessThanOrEqual(3);
expect(analysisPayload.input_characters).toBeLessThanOrEqual(8000);
```

Continue with audit/event/state range assertions, UI refresh, revoke, a post-revoke local distress turn containing `e2e-post-revoke-secret`, unchanged request/audit counts, and increased `concern`. Retain console/page/5xx collection.

- [ ] **Step 2: Run the E2E and verify it fails because deployment remains disabled**

```powershell
Set-Location frontend
npm run test:e2e -- emotion.spec.ts --grep "LLM-assisted emotion analysis"
```

Expected: FAIL before fake server/analysis configuration exists.

- [ ] **Step 3: Configure Playwright web servers**

In `playwright.config.ts`, allocate `fakeDeepSeekPort` from `E2E_FAKE_DEEPSEEK_PORT` defaulting to `18101`. Add a first web server:

```ts
{
  command: `${pythonCommand} -m uvicorn scripts.fake_deepseek_emotion_server:app --app-dir .. --host 127.0.0.1 --port ${fakeDeepSeekPort} --no-access-log`,
  url: `http://127.0.0.1:${fakeDeepSeekPort}/__test__/state`,
  reuseExistingServer: false,
  timeout: 20_000,
}
```

Add backend environment:

```ts
EMOTION_ANALYSIS_ENABLED: 'true',
EMOTION_ANALYSIS_PROVIDER: 'deepseek',
EMOTION_ANALYSIS_MODEL: 'stage4c-e2e-model',
EMOTION_ANALYSIS_MAX_RETRIES: '0',
DEEPSEEK_API_KEY: 'stage4c-e2e-token',
DEEPSEEK_BASE_URL: `http://127.0.0.1:${fakeDeepSeekPort}`,
```

Expose `E2E_FAKE_DEEPSEEK_PORT` to the test process through `process.env` and reset fake state at the start of the test.

- [ ] **Step 4: Run the focused E2E**

```powershell
Set-Location frontend
npm run test:e2e -- emotion.spec.ts --grep "LLM-assisted emotion analysis"
```

Expected: the complete grant/apply/revoke/local-fallback browser test PASS.

---

### Task 4: Playwright Database Verification and Cleanup

**Files:**
- Modify: `frontend/playwright.global-teardown.ts:1-10`
- Modify: `frontend/playwright.global-teardown.test.ts:1-19`

- [ ] **Step 1: Write failing teardown tests**

Refactor the exported unit to accept injected execution and assert it calls the verifier before cleanup:

```ts
const calls: string[] = [];
verifyAndRemoveE2EDatabase(databasePath, {
  runVerifier: () => { calls.push('verify'); },
  removeFile: (path) => { calls.push(`remove:${path}`); },
  exists: () => true,
});
expect(calls[0]).toBe('verify');
expect(calls).toEqual([
  'verify',
  `remove:${databasePath}`,
  `remove:${databasePath}-wal`,
  `remove:${databasePath}-shm`,
]);
```

Assert verifier failure is propagated and cleanup remains best effort in `finally` without masking the verification error.

- [ ] **Step 2: Run the frontend unit test and verify failure**

```powershell
Set-Location frontend
npm test -- playwright.global-teardown.test.ts
```

Expected: FAIL because `verifyAndRemoveE2EDatabase` is not defined.

- [ ] **Step 3: Implement verification invocation**

Use `execFileSync` rather than shell interpolation:

```ts
execFileSync(pythonCommand, [
  resolve(frontendDir, '..', 'scripts', 'verify_stage4c_e2e_database.py'),
  '--database', databasePath,
  '--expected-jobs', '1',
  '--expected-audits', '1',
  '--expected-outcome', 'applied',
  '--forbid', 'e2e-analysis-secret',
  '--forbid', 'e2e-post-revoke-secret',
  '--forbid', 'stage4c-e2e-token',
  '--forbid', '我今天很难受',
  '--forbid', '我需要帮助',
], { stdio: 'inherit' });
```

Then remove the database and sidecars with exact paths only. Keep the existing undefined-path no-op behavior.

- [ ] **Step 4: Run teardown tests and focused E2E**

```powershell
Set-Location frontend
npm test -- playwright.global-teardown.test.ts playwrightPython.test.ts
npm run test:e2e -- emotion.spec.ts --grep "LLM-assisted emotion analysis"
```

Expected: unit tests PASS; E2E and post-server database verification PASS; temporary DB/sidecars are removed.

---

### Task 5: Extend Direct Runtime Revocation Coverage

**Files:**
- Modify: `backend/tests/test_emotion_analysis_runtime.py:52-111`

- [ ] **Step 1: Write the additional runtime assertions**

After the first applied audit, capture state, revoke, send a second turn, and assert:

```python
before_revoke = client.get("/api/emotion/state").json()
revoke = client.put(
    "/api/emotion/analysis/consent",
    json={
        "action": "revoke",
        "disclosure_version": "emotion-analysis-disclosure-v1",
    },
)
assert revoke.status_code == 200
second_chat = client.post(
    f"/api/sessions/{session['id']}/messages",
    json={"content": "我需要帮助 token=runtime-post-revoke-secret"},
)
assert second_chat.status_code == 200
assert len(provider.calls) == 1
after_revoke = client.get("/api/emotion/state").json()
assert after_revoke["vector"]["concern"] > before_revoke["vector"]["concern"]
assert len(client.get("/api/emotion/analysis/audits").json()) == 1
```

Extend database markers to include the second secret and text fragment.

- [ ] **Step 2: Run the runtime test**

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests\test_emotion_analysis_runtime.py -q
```

Expected: PASS if existing revocation isolation is correct; otherwise retain the failure as a confirmed defect for Task 7.

---

### Task 6: Optional Real DeepSeek Smoke

**Files:**
- Create: `scripts/smoke_real_emotion_analysis.py`
- Create: `backend/tests/test_smoke_real_emotion_analysis_script.py`

- [ ] **Step 1: Write failing script tests**

Test parsing and key gating without network:

```python
assert main(["--database", str(tmp_path / "smoke.db")], environ={}) == SKIPPED_EXIT_CODE
assert "SKIPPED" in capsys.readouterr().out
```

Inject a fake async provider/app factory for the success test and assert safe summary output contains `PASS`, `audit_outcome=applied`, and no fixture body, provider response, or key.

- [ ] **Step 2: Run script tests and verify failure**

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests\test_smoke_real_emotion_analysis_script.py -q
```

Expected: import failure because the script does not exist.

- [ ] **Step 3: Implement the opt-in smoke**

The script must:

```python
key = environ.get("DEEPSEEK_API_KEY", "").strip()
if not key:
    print("SKIPPED: DEEPSEEK_API_KEY is not set in this process environment")
    return SKIPPED_EXIT_CODE
```

Set a temporary `DATABASE_URL`, `LLM_PROVIDER=fake`, `EMOTION_ANALYSIS_ENABLED=true`, `EMOTION_ANALYSIS_PROVIDER=deepseek`, a user-supplied/default real model, timeout, token budget, and retries zero. Use `TestClient(create_app())`, grant consent, send only a synthetic fixture such as `虚构测试：最近考试压力较大，希望获得一些支持。`, poll for one terminal audit, assert state values are bounded and jobs/audits lack key/raw response fields, print a safe summary, and remove the temporary database plus sidecars.

Do not print the fixture, prompt, request, response, key, or database rows.

- [ ] **Step 4: Run offline script tests**

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests\test_smoke_real_emotion_analysis_script.py -q
```

Expected: all script tests PASS without network.

- [ ] **Step 5: Run real smoke only if an explicit key already exists**

First inspect only presence, not value:

```powershell
if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) { 'SKIP_NO_KEY' } else { 'KEY_PRESENT' }
```

If `KEY_PRESENT`, run:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_real_emotion_analysis.py --model deepseek-chat
```

Expected: `PASS` with safe metadata-only summary. If no key exists, record `SKIPPED (no explicit environment key)` in evidence. Never source a key from repository files or print it.

---

### Task 7: Security and Correctness Review, Then Confirmed Fixes

**Files:**
- Review: `backend/app/services/emotion_analysis_service.py`
- Review: `backend/app/services/emotion_analysis_dispatch.py`
- Review: `backend/app/services/emotion_analysis_scheduler.py`
- Review: `backend/app/repositories/emotion_analysis.py`
- Review: `backend/app/main.py`
- Review: `backend/app/services/credential_sanitizer.py`
- Review: `backend/app/services/emotion_analysis_input.py`
- Review: `backend/app/services/emotion_analysis_analyzer.py`
- Review: `backend/app/api/routes/emotion.py`
- Modify/Test: only files associated with confirmed findings.

- [ ] **Step 1: Run the mandatory code review workflow**

Invoke `/code-review` over Stage 4C task-owned changes. Require concrete failure scenarios for consent generation races, dispatch fence behavior, duplicate charging, shutdown cancellation, CAS/transaction consistency, transmission-time sanitization, persistence/log leakage, and provider-output handling.

Expected: a ranked finding list or explicit no-findings result.

- [ ] **Step 2: Verify every suspected finding**

For each finding, reproduce with a focused test. Reject findings that cannot produce an incorrect state, extra provider call, privacy leak, or broken shutdown under the documented contract.

- [ ] **Step 3: Fix only confirmed findings using TDD**

For each confirmed issue:

1. add the failing focused test;
2. run it and observe the expected failure;
3. apply the smallest Stage 4C fix;
4. rerun the focused test;
5. rerun `backend/tests/test_emotion_analysis_*.py` and the complete Stage 4C E2E.

Do not perform unrelated refactoring or Stage 4D work.

---

### Task 8: Full Verification

**Files:**
- No product files unless a verified failure requires a minimal fix.

- [ ] **Step 1: Run backend focused tests**

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests\test_emotion_analysis_analyzer.py tests\test_emotion_analysis_input.py tests\test_emotion_analysis_migration.py tests\test_emotion_analysis_repository.py tests\test_emotion_analysis_runtime.py tests\test_emotion_analysis_scheduler.py tests\test_emotion_analysis_service.py tests\test_api_emotion.py -q
```

Expected: all focused tests PASS.

- [ ] **Step 2: Run backend full suite**

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest -q
```

Expected: full suite PASS; record exact test count and duration.

- [ ] **Step 3: Run root script tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fake_deepseek_emotion_server.py tests\test_verify_stage4c_e2e_database.py -q
```

Expected: all script tests PASS.

- [ ] **Step 4: Run frontend unit tests**

```powershell
Set-Location frontend
npm test
```

Expected: all Vitest files/tests PASS; record exact counts.

- [ ] **Step 5: Run typecheck and production build**

```powershell
Set-Location frontend
npm run typecheck
npm run build
```

Expected: both commands exit zero.

- [ ] **Step 6: Run complete Playwright suite**

```powershell
Set-Location frontend
npm run test:e2e
```

Expected: all E2E tests PASS, the Stage 4C verifier reports safe counts, and no E2E database files remain.

- [ ] **Step 7: Run product runtime verification**

Invoke the scoped `AI桌宠:verify` skill to exercise the affected backend API behavior end to end, using the deterministic fake-provider path.

Expected: observed grant/apply/revoke/local-fallback behavior PASS.

- [ ] **Step 8: Check whitespace and change scope**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors. Record pre-existing unrelated/untracked changes separately; do not stage or commit.

---

### Task 9: Evidence and Project Status

**Files:**
- Create: `docs/stage4c-llm-emotion-analysis-consent.md`
- Modify: `README.md:1-5,40-52`
- Modify: `CLAUDE.md:3-4,69-83,114-143`

- [ ] **Step 1: Write the evidence report from observed results**

The report must include:

```markdown
# Stage 4C LLM-Assisted Emotion Analysis and Consent

> Verdict: VERIFIED PASS | BLOCKED
> Date: 2026-07-14

## Scope
## Automated browser and loopback-provider evidence
## Consent and revocation observations
## Privacy and metadata-only persistence checks
## Backend/runtime evidence
## Optional real DeepSeek smoke
## Security/correctness review
## Full verification commands and exact results
## Limitations and Stage 4D boundary
```

Use actual counts/durations and truthful PASS/SKIPPED/BLOCKED outcomes. Do not include any key, raw prompt, raw response, or sensitive fixture payload.

- [ ] **Step 2: Update project status only on VERIFIED PASS**

Update `CLAUDE.md` header/table/current-stage section to:

```text
阶段 4——情感系统（IMPLEMENTING；4A + 4B + 4C COMPLETED；NEXT: 4D ExpressionPlan/TTS Expression Design）
```

Update README summary and implemented scope to describe 4C explicit persistent consent, bounded/sanitized input, strict parsing, local constraints/fallback, metadata audit, and verification. Remove the stale statement that all of Stage 4 is unimplemented. State that Stage 4D and later visual/desktop integration are not implemented.

- [ ] **Step 3: Final consistency check**

Search README, CLAUDE, and Stage 4 docs for stale claims that 4C is only a design or that the entire emotion system is unimplemented. Confirm all completion claims point to the evidence report and preserve the fixed phase order.

- [ ] **Step 4: Final diff check without commit**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; all Stage 4C closure files visible; nothing staged or committed.
