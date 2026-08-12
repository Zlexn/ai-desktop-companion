# Gate A Closure Acceptance Record

**Date:** 2026-07-19  
**Status:** COMPLETE  
**Scope:** Automatic-memory enhancement Gate A closure only.

## Baseline and review

- Read: `CLAUDE.md`, `docs/superpowers/specs/2026-07-18-automatic-memory-gate-a-closure-design.md`, and `docs/superpowers/plans/2026-07-18-automatic-memory-gate-a-closure.md`.
- Baseline `git status --short` was already dirty and had no staged files. No files were staged, committed, reset, restored, cleaned, or stashed during this acceptance.
- Independent focused review of the current uncommitted Gate A diff against `93078aaa4507852c924ea37d75f7844d8972db11`: no confirmed high- or critical-severity correctness, privacy, or security findings.
- Final post-simplification review initially found one medium-severity logging privacy regression: secrets in a format template were not redacted when structured arguments were present. A failing regression test reproduced it; the filter now redacts both `record.msg` and string argument values while preserving Uvicorn's structured argument shape. The same independent reviewer re-ran the reproduction and returned `VERDICT: APPROVED`, with no remaining correctness, privacy, security, or Gate A contract blockers.

## Final behavior-preserving cleanup

The four-angle reuse, simplification, efficiency, and abstraction-level review produced a small set of same-behavior cleanups:

- Consent deployment capability now reuses `memory_extractor_provider_is_configured()` instead of duplicating selected-provider credential logic in the HTTP route.
- Logging redaction reuses `sanitize_error_text()`, skips work when no secrets are configured, and replaces an existing `SecretRedactionFilter` instead of accumulating filters across repeated app-factory lifecycles.
- `MemoryGovernor.evaluate_many()` computes the per-turn policy once and passes the immutable result to proposal evaluation; proposal validation, canonical identity reservation, ordering, and accepted-budget semantics are unchanged.
- Purpose, disclosure version, and disclosed fields now have one production-code source in `memory_extraction_contract.py`.

Larger recommendations were deliberately deferred because they would change interfaces, connection/concurrency behavior, or extend beyond low-risk Gate A cleanup: a shared emotion/memory consent fence, a separate memory runtime object, reservation/connection lifetime redesign, repository `RETURNING` APIs, batch message lookup, bounded recovery workers, and embedding-provider lifecycle changes.

## Focused tests

Command (from the repository root, with repository root and `backend` on `PYTHONPATH`):

```powershell
python -W error -m pytest backend/tests/test_config.py backend/tests/test_memory_automation_migration.py backend/tests/test_memory_automation_repository.py backend/tests/test_memory_governor.py backend/tests/test_memory_extractor.py backend/tests/test_memory_job_service.py backend/tests/test_memory_job_scheduler.py backend/tests/test_api_memory_automation.py backend/tests/test_chat_memory_candidates.py backend/tests/test_api_chat.py backend/tests/test_provider_factory.py backend/tests/test_logging.py -q
```

Result: exit 0; **430 passed** in 9.68 seconds; no warnings were emitted.

The initial warning-as-error invocation exposed an unset `pytest-asyncio` fixture-loop scope. `backend/pyproject.toml` now explicitly sets `asyncio_default_fixture_loop_scope = "function"`; the command above confirms the warning check is clean.

Focused consent, non-mutation, rollback-mode, and migration evidence:

```powershell
python -m pytest backend/tests/test_api_chat.py::test_remote_shadow_without_selected_credential_skips_without_provider_factory backend/tests/test_memory_job_service.py::test_remote_requires_exact_persisted_consent_without_sending backend/tests/test_chat_memory_candidates.py backend/tests/test_memory_automation_migration.py::test_init_db_adds_gate_a_tables_without_changing_legacy_memories -q -rA
```

Result: exit 0; **16 passed**. This includes configured-provider/no-exact-consent zero-call coverage, remote missing-credential `skipped_no_extractor`, exclusive `candidate_confirmation` and `off` behavior, `shadow_auto` routing, active/pending/dismissed/archived memory-row preservation, and additive-schema migration preservation.

## Full backend regression

Command:

```powershell
python -m pytest backend/tests -q
```

Result: exit 0; **966 passed** in 25.39 seconds; no skipped tests or warnings were reported.

A first attempt with only `backend` on `PYTHONPATH` collected no full suite because `tests/test_cosyvoice_text.py` imports the repository-root `scripts` package. Re-running with both repository root and `backend` on `PYTHONPATH` produced the passing result above. No real external-provider test was represented as cloud evidence.

## HTTP smoke: fake chat and remote route without credentials

Real Uvicorn configuration:

```text
DATABASE_URL=sqlite:///./gate-a-task7-remote-no-key-smoke.db
LLM_PROVIDER=fake
MEMORY_AUTOMATION_MODE=shadow_auto
MEMORY_EXTRACTOR_ROUTE=remote
MEMORY_EXTRACTOR_PROVIDER=anthropic
ANTHROPIC_API_KEY unset
DEEPSEEK_API_KEY unset
```

Uvicorn served `app.main:app` on `127.0.0.1:8017`. A session and fake chat turn completed; polling used a 10-second monotonic deadline and 100 ms interval.

- Assistant message ID: `5a9da769-714e-42f7-ab9b-e5e96b3a8eb1`
- Job ID/status/outcome: `08e2d17f-774e-4ccc-82c2-662ba33b559e` / `succeeded` / `skipped_no_extractor`
- Audit ID/outcome: `f6e9c059-991a-438a-a0a5-d65f6ca3ac44` / `skipped_no_extractor`
- Bounded poll: terminal job found before deadline.
- Job/audit API metadata check: passed; no `content`, `prompt`, `response`, `user_text`, `assistant_text`, `proposal`, `authorization`, or `api_key` response field.
- `memories` before/after: 0 rows / 0 rows; unchanged.
- Database inspection: 1 job and 1 audit.

No remote provider was configured and no cloud extraction was attempted. After inspection, the confirmed smoke database path was deleted.

## Local extraction smoke

A fresh real Uvicorn instance served `app.main:app` on `127.0.0.1:8018` with the same fake chat provider and `MEMORY_EXTRACTOR_ROUTE=local`.

- Assistant message ID: `8ca99c97-4070-42bc-87e5-92ad7175b189`
- Job ID/status/outcome: `9c07266e-9f1b-42bb-93c8-d6fa07113967` / `succeeded` / `shadow_recorded`
- Audit ID/outcome: `9c3997bd-06fa-4634-aee2-f90e492a66bd` / `shadow_recorded`
- Bounded poll: terminal job found before the 10-second deadline.
- Job/audit API metadata check: passed with the same forbidden-field set.
- `memories` before/after: 0 rows / 0 rows; unchanged.
- Database inspection: 1 job and 1 audit.

After inspection, the confirmed local smoke database path was deleted. No remote consent was granted and no real cloud extraction occurred.

## Runtime defect corrected during acceptance

The first real-Uvicorn attempt reached application startup but requests timed out because `SecretRedactionFilter` converted Uvicorn access log formatting arguments into a preformatted message and cleared `record.args`. Uvicorn's access formatter requires its five original arguments. A regression test was written first and failed, then `SecretRedactionFilter` was changed to redact string values in `record.args` while preserving argument shape. The test passed:

```powershell
python -m pytest backend/tests/test_logging.py -q
```

Result: exit 0; **3 passed**. The coverage preserves Uvicorn's structured access-log argument shape, redacts secrets in both message templates and formatting arguments, and proves repeated app logging configuration leaves one redaction filter per target logger.

## Privacy, dependency, scope, and secret checks

Commands and results:

```powershell
Select-String -Path backend/app/services/memory_job_service.py -Pattern "MemoryRepository"
```

Result: no matches. `MemoryJobService` has no active-memory repository dependency.

```powershell
Select-String -Path backend/app/services/memory_governor.py,backend/app/services/memory_extractor.py,backend/app/services/memory_job_scheduler.py,backend/app/api/routes/memories.py -Pattern "anthropic|httpx|Authorization|api_key|prompt|raw response"
```

Result: five reviewed matches only: Governor API-key detection identifiers and route-level configuration checks for selected provider credentials. No provider SDK/HTTPX import or raw job/audit body exposure was found in these layers.

```powershell
Select-String -Path backend/app/services/chat_service.py -Pattern "auto_active"
```

Result: no matches; ChatService has no `auto_active` branch.

```powershell
Get-ChildItem backend/app,backend/tests,docs -Recurse -File -Include *.py,*.md | Select-String -Pattern 'sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16,}'
```

Result: 12 matches reviewed. All are deliberate redaction-test sentinels or historical design-plan examples; no production credential was found.

```powershell
git diff --check
git diff --name-only
```

Result: `git diff --check` exit 0 with line-ending advisory messages only. The reviewed changed-file list contains existing Gate A backend/config/test work, the Gate A plan/spec, this acceptance record, and unrelated pre-existing workspace items. It contains no Gate B/C implementation, frontend status UI, Electron, Live2D, visual asset, voice-cloning, summary-injection, Persona, relationship, Evidence, or tombstone implementation changes.

## Limits and unverified scope

- Real Anthropic and DeepSeek extraction: **not run**. This acceptance intentionally used fake chat, local extraction, fake/test doubles, a configured-provider/no-exact-consent zero-call integration test, and a remote route with credentials absent. No real cloud extractor was contacted.
- Gate B/C, frontend Gate A status UI, Electron shell, Live2D, private image import, and voice cloning remain unimplemented and out of scope.
- The Gate A rollback evidence is automated integration coverage: `candidate_confirmation` creates only a pending candidate and zero shadow jobs; `off` creates neither. Gate A automation tables remain additive and migration preservation passed.
- The acceptance smoke database files and temporary Uvicorn logs created by this run were inspected and deleted. No other files were deleted.
