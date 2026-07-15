# Stage 4C LLM-Assisted Emotion Analysis and Consent

> Verdict: **VERIFIED PASS**
> Date: 2026-07-14

## Scope

Stage 4C adds optional LLM-assisted emotion proposals behind explicit persistent consent. It uses an independently configured provider, minimized and credential-sanitized context, strict `emotion_analysis_v1` parsing, local policy constraints, CAS state updates, idempotent background jobs, and metadata-only audit records. Stage 4A local rules remain authoritative fallback behavior.

This evidence closes Stage 4C only. ExpressionPlan, emotion-to-TTS parameter mapping, Live2D, desktop-shell integration, and character assets remain outside this milestone.

## Automated browser and loopback-provider evidence

The Playwright application uses the standard production `DeepSeekProvider`, configured only for the acceptance run to call a loopback-only deterministic OpenAI-compatible server at `127.0.0.1`. This exercises browser → React → FastAPI → background scheduler → DeepSeek HTTP adapter → strict parser → local policy/CAS → SQLite → UI without external transmission or API fees.

Observed complete browser flow:

- Before grant: chat succeeded and loopback provider request count remained `0`.
- After two-step grant: one assistant message produced exactly one provider request.
- The provider-side recorded request did not contain the synthetic credential marker.
- Payload limits remained at most 6 recent messages, 3 active memories, and 8,000 content characters.
- One audit reached `applied`; one `llm_assisted` event was observable; all state dimensions remained in `[0, 1]`.
- After revoke: another local-distress turn increased local concern while provider request count and analysis audit count remained unchanged.
- No browser console error, page error, or HTTP 5xx occurred.

Final full Playwright result:

```text
9 passed (15.1s)
PASS: Stage 4C E2E analysis tables are metadata-only
      jobs=1, audits=1, outcome=applied
```

## Consent and revocation observations

Security/correctness review found and fixed consent-mutation race conditions:

1. A queued job could previously acquire the dispatch lock before a waiting revoke request and transmit. Consent mutation is now registered as pending before waiting for the lock, and queued dispatch treats pending mutation as denied.
2. An in-flight provider result could previously be applied while a revoke request was pending but not yet persisted. The post-provider gate now rejects pending consent mutation as well as generation/status mismatch.
3. Cancellation while a consent mutation waited for the dispatch lock could leave the pending counter stuck and disable future analysis. Lock acquisition cancellation now rolls back the pending registration.

Deterministic regression observations:

```text
queued job after pending revoke: provider calls remained 1
in-flight result after pending revoke: applied=false, audit=revoked, llm_assisted events=0
cancelled waiting consent mutation: future dispatch allowed=true
```

Focused final result:

```text
3 consent-race regressions passed
17 complete service + consent API tests passed
```

## Privacy and metadata-only persistence checks

Both independent-process Playwright teardown and TestClient runtime verification inspect only:

- `emotion_analysis_jobs`
- `emotion_analysis_audits`

The checks verified that these tables contain no synthetic secret marker, original message fragment, test bearer token, raw prompt, or raw provider response. Product `messages` storage was intentionally excluded because chat content is designed to persist there.

The E2E verifier also checks exact counts and terminal outcome before deleting the temporary database and `-wal`/`-shm` sidecars. Explicit `E2E_DATABASE_URL` overrides must be absolute SQLite file URLs so verification cannot be silently bypassed.

## Backend/runtime evidence

The backend lifespan/runtime test uses an injected recording provider and verifies:

- grant produces one provider call and an applied constrained event;
- visible credentials are sanitized before transmission;
- revoke followed by a local distress turn leaves provider calls unchanged;
- Stage 4A local concern still changes after revoke;
- analysis persistence contains no raw fixture, key, prompt, or response.

The DeepSeek HTTP adapter also now bypasses system/environment proxy routing only for exact loopback hosts (`127.0.0.1`, `localhost`, `::1`). Remote DeepSeek endpoints retain configured proxy behavior. This fixed a Windows environment where localhost was otherwise routed through a proxy and returned HTTP 502.

## Real DeepSeek smoke

An explicit process environment key was available. The opt-in smoke used:

- model: `deepseek-chat`;
- a temporary SQLite database;
- a synthetic, non-sensitive Chinese support request;
- retries disabled;
- no raw request, provider response, fixture text, or key in the smoke summary.

The first diagnostic request returned HTTP 200 but demonstrated that the system prompt did not enumerate the exact nested schema fields. The prompt was tightened to list exact top-level and `proposed_delta` fields, finite-number requirements, schema version, and source-ID restriction. Parser tests remained strict; no permissive parsing was added.

Final real smoke result:

```text
PASS: Stage 4C real DeepSeek smoke
      audit_outcome=applied
      bounded_state=true
      metadata_only=true
```

## Security/correctness review

The review covered consent generation and revoke/regrant races, dispatch fencing, duplicate charging, scheduler shutdown, CAS/transaction consistency, transmission-time sanitization, persistence/log leakage, loopback HTTP behavior, and E2E teardown verification.

Confirmed findings and outcomes:

| Finding | Severity | Outcome |
|---|---:|---|
| Pending revoke could be overtaken by queued provider dispatch | High | Fixed with pending consent-mutation gate and deterministic regression |
| In-flight result could apply while revoke was pending | Medium | Fixed with post-provider pending gate |
| Cancelled pending consent mutation could permanently block analysis | Medium | Fixed with cancellation-safe counter rollback |
| Total character budget of 1 could be exceeded by the required two-message current turn | Medium | Fixed in config and input builder; total must be at least 2 |
| Emotion E2E depended on prior global version | Medium | Fixed with explicit reset and relative version assertions |
| Custom E2E database URL could bypass privacy verifier | Medium | Fixed with SQLite URL path derivation and non-SQLite fail-fast |

Final independent read-only re-review reported no remaining reproducible correctness, security, or privacy problem in these fixes.

## Full verification commands and results

### Backend

```powershell
python -m pytest backend\tests -q
```

```text
506 passed in 29.08s
```

### Root scripts and acceptance helpers

```powershell
python -m pytest tests -q
```

```text
39 passed in 3.19s
```

### Frontend unit tests

```powershell
npm --prefix frontend test
```

```text
21 files passed
175 tests passed
Duration 15.76s
```

### TypeScript and production build

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

```text
typecheck PASS
vite v8.0.16
37 modules transformed
built in 206ms
```

### Browser E2E

```powershell
npm --prefix frontend run test:e2e
```

```text
9 passed (15.1s)
Stage 4C metadata-only verifier PASS
```

### Diff integrity

```powershell
git diff --check
```

Result: PASS; no whitespace errors. Git emitted existing Windows LF→CRLF conversion warnings only.

## Limitations and Stage 4D boundary

Stage 4C does not implement:

- ExpressionPlan or message-bound multimodal expression planning;
- emotion-aware TTS rate, pitch, style, or voice selection;
- Live2D or other character animation;
- a desktop shell, always-on microphone, or automatic spoken interruption;
- licensed character images, protected voice models, or other character assets;
- claims that the character has real consciousness or human emotion.

The next minimum task is Stage 4D ExpressionPlan/TTS expression design. It must preserve Stage 4C consent, local constraints, privacy, and failure-isolation guarantees.
