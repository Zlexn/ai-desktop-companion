# Automatic Memory Gate B Acceptance Record

**Date:** 2026-07-21  
**Status:** COMPLETE  
**Scope:** Automatic-memory enhancement Gate B only; Gate C, Persona, relationship projection, summary injection, Electron, Live2D, and private assets remain out of scope.

## Environment and isolation

- Repository: `<project-root>`
- Python: `3.12.6`
- Node.js: `v22.22.3`
- npm: `10.9.8`
- The primary working tree was already dirty and remained unstaged. No commit, push, stage, reset, restore, clean, or stash operation was performed.
- Every new acceptance test uses pytest `tmp_path` for SQLite and the HMAC source-reference key.
- `ANTHROPIC_API_KEY` and `DEEPSEEK_API_KEY` are cleared in smoke setup. Test-only in-process Provider doubles are injected where a remote-route consent boundary is exercised.
- No Anthropic, DeepSeek, or other real cloud memory extraction was contacted.

## Acceptance claim matrix

| Gate B completion claim | Evidence | Result |
|---|---|---|
| No exact write grant means zero extractor/send and zero active mutation | `backend/tests/test_gate_b_http_smoke.py::test_no_write_grant_blocks_extractor_and_active_mutation`; dispatcher fence tests | PASS |
| Remote consent and write consent cannot substitute for one another | `test_no_write_grant_blocks_extractor_and_active_mutation`; `test_remote_write_grant_without_remote_consent_sends_nothing`; consent API tests | PASS |
| create/support/supersede/conflict have version/Evidence/activity evidence | `test_local_exact_write_grant_commits_version_evidence_and_activity`; `test_fake_http_create_support_supersede_and_conflict_evidence`; commit-service tests | PASS |
| Open-conflict identities do not enter deterministic chat or emotion memory input | `test_open_conflict_is_absent_from_chat_and_emotion_provider_inputs`; repository/embedding eligibility tests | PASS |
| True forget removes readable payload and embedding, retains tombstone, and prevents revival | `test_true_forget_is_unreadable_and_same_fact_does_not_revive`; `test_gate_b_privacy_contract.py`; forget-service tests | PASS |
| Queued/in-flight/retry/recovery work cannot revive after revoke/delete | `test_memory_write_dispatch.py`, `test_memory_job_service.py`, `test_memory_forget_service.py`, `test_session_deletion_coordinator.py`, and recovery repository tests | PASS |
| Stale automatic work cannot overwrite user edits | CAS rollback tests in `test_versioned_memory_commit.py` and `test_versioned_memory_mutation.py`; stale auto-create undo regression | PASS |
| Gate A shadow mode remains metadata-only and active-zero-mutation | `test_shadow_auto_http_remains_metadata_only`; HTTP mode matrix | PASS |
| Stage 1–4 backend and affected frontend regressions pass | Full backend/frontend commands below | PASS |
| Privacy contract excludes keys, digests, internal hashes, raw outputs, prompts, reasoning, and deleted payloads | `backend/tests/test_gate_b_privacy_contract.py`; API/frontend privacy tests | PASS |
| Independent review has no unresolved high/critical finding | Final independent review | PASS |

## Reproducible HTTP smoke

Command:

```powershell
python -W error -m pytest backend/tests/test_gate_b_http_smoke.py backend/tests/test_gate_b_privacy_contract.py -q
```

Result: exit 0; **12 passed** in 2.80 seconds.

The modules also passed separately before the final diff-text assertion was added: HTTP smoke **7 passed** in 1.45 seconds; privacy contract **4 passed** in 0.39 seconds. The final privacy module alone passed **5 tests** in 0.48 seconds.

The named TestClient smokes drive actual FastAPI session, chat, consent, memory, history, Evidence, conflict, forget, job, and audit routes. They verify:

- remote consent alone: Provider calls `0`, active/version/Evidence/activity counts all `0`, terminal outcome `skipped_no_write_consent`;
- write grant alone on remote route: Provider calls `0`, active memory count `0`, terminal outcome `skipped_no_consent`;
- local exact write grant: non-empty session/assistant/job IDs, `completed_with_decisions`, one automatic memory, one version, one supports Evidence, one activity;
- injected fake Provider decision sequence: exactly one each of `committed_create`, `committed_support`, `committed_supersede`, and `conflict_recorded`; open conflict present; supports/corrects/contradicts relations present; four activities;
- true forget: sentinel absent from history, Evidence, selected SQLite durable surfaces, and logs; tombstone retained; repeated same fact produces `skipped_tombstone` and no active revival;
- open conflicts: both sentinel payloads absent from captured fake chat Provider input and consented emotion-analysis Provider input;
- `shadow_auto`: terminal `shadow_recorded`, with zero active memory, version, Evidence, or activity mutation.

## Automated privacy contract

Command:

```powershell
python -W error -m pytest backend/tests/test_gate_b_privacy_contract.py -q
```

Result: exit 0; **5 passed** in 0.48 seconds.

The contract verifies:

- API JSON omits canonical/subject/content hashes, HMAC references, remote authority fingerprint, prompt, raw response, hidden reasoning, Authorization, and API-key fields;
- metadata-only tables are explicitly allowlisted and do not contain content/subject/prompt/raw-response columns;
- a true-forget sentinel is absent from list/archive/history/Evidence/audit API responses, selected raw SQLite rows, and captured logs;
- raw HMAC key bytes, key hex, candidate provenance digests, and derived test digests are absent from public API output and logs; key/digest markers are absent from `.env.example` and the complete bounded Git review surface, including untracked Gate B source/test/docs files;
- `SecretRedactionFilter` removes both a raw secret and digest from structured logging arguments.

Focused rendered UI privacy check:

```powershell
npm --prefix frontend test -- --run src/components/MemoryPanel.test.tsx src/components/MemoryHistoryDetails.test.tsx
```

Result: exit 0; **2 files, 14 tests passed**. Redacted history renders only the fixed `内容已忘记` label; no stale payload is rendered.

## Warning-strict Gate B verification

Command:

```powershell
python -W error -m pytest backend/tests/test_versioned_memory_migration.py backend/tests/test_memory_source_reference.py backend/tests/test_versioned_memory_repository.py backend/tests/test_versioned_memory_mutation.py backend/tests/test_memory_commit_policy.py backend/tests/test_versioned_memory_commit.py backend/tests/test_memory_write_dispatch.py backend/tests/test_memory_forget_service.py backend/tests/test_session_deletion_coordinator.py backend/tests/test_memory_summary_barrier.py backend/tests/test_memory_conflict_resolution.py backend/tests/test_api_memory_gate_b.py backend/tests/test_gate_b_http_smoke.py backend/tests/test_gate_b_privacy_contract.py -q
```

Result: exit 0; **149 passed** in 11.80 seconds; warnings-as-errors produced no warning failure.

## Concurrency, recovery, and Gate A matrix

Command:

```powershell
python -W error -m pytest backend/tests/test_memory_write_dispatch.py backend/tests/test_memory_forget_service.py backend/tests/test_session_deletion_coordinator.py backend/tests/test_versioned_memory_commit.py backend/tests/test_versioned_memory_mutation.py backend/tests/test_memory_automation_repository.py backend/tests/test_chat_memory_candidates.py -q
```

Result: exit 0; **93 passed** in 4.81 seconds.

This covers queued/pending revoke before extraction, in-flight response discard, pre-commit authority recheck, frozen generation mismatch, deletion generation, true-forget rollback checkpoints, delayed embedding suppression, session deletion terminalization, stale post-delete commit, running-job recovery, incompatible mode recovery, stale-head CAS rollback, and the `off`/`candidate_confirmation`/`shadow_auto`/`auto_active` HTTP mode matrix.

## Full regression and build

Backend:

```powershell
python -W error -m pytest backend/tests -q
```

Result: exit 0; **1137 passed** in 59.57 seconds.

Frontend:

```powershell
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Results:

- Vitest: exit 0; **30 files, 246 tests passed** in 23.84 seconds.
- TypeScript project build/typecheck: exit 0.
- Vite production build: exit 0; 48 modules transformed.

Python source compile:

```powershell
python -m compileall -q backend/app
```

Result: exit 0.

Diff hygiene:

```powershell
git diff --check
```

Result: exit 0; only Windows LF-to-CRLF advisory messages were emitted.

## Privacy and scope notes

- The initial independent review returned `BLOCKED` with four findings: stale pre-extraction target overwrite, candidate provenance loss after session deletion, candidate-only forget without a durable anti-revival identity, and an incomplete tracked-only Git privacy scan. A later focused re-review found one additional subjectless-candidate variant and requested persisted-material privacy evidence. The final implementation snapshots eligible target heads before extraction and advances that baseline only through the same batch's own committed results, retains candidate session provenance as HMAC-only data, creates exact/subject/content-only tombstones before candidate redaction, and checks actual persisted key/digest material across tracked plus bounded untracked Gate B files. All findings were resolved before the final `APPROVED` verdict.
- `.env.example` documents the separate write-consent endpoint and stores only a local key **path**, never key material.
- API keys remain backend environment settings and are absent from frontend source/types.
- User images, videos, voice references, and other private assets were not read, copied, uploaded, tested, snapshotted, or bundled.
- Summary source barriers were verified, but Gate B still does not inject summaries or let summaries drive memory writes.
- No Persona artifact, relationship projection, Gate C UI, Electron shell, Live2D, or asset work was performed.

## Unverified limits

- Real Anthropic and DeepSeek memory extraction were intentionally **not run**. Fake/local and in-process Provider results are not cloud-provider evidence.
- This acceptance does not claim production latency, long-duration desktop stability, voice quality, desktop rendering, or packaged Windows deployment.
- Gate C remains blocked pending a separate design/plan cycle and explicit user continuation after Gate B completion.

## Independent review

Final verdict: **APPROVED**.

The reviewer independently verified the two last blockers and their direct interactions against the dirty primary tree:

- valid subjectless candidates receive content-only tombstones before redaction, and an automatic proposal with a different subject but the same normalized content is rejected as `skipped_tombstone` with zero active revival;
- the privacy contract derives provenance through `MemoryRepository`, reads the actual persisted digest, and checks that exact key/digest material against tracked changes plus bounded in-scope untracked files.

Independent read-only verification passed **68 affected tests** under warnings-as-errors. No unresolved medium/high correctness, privacy, security, or acceptance-integrity finding remains. Real Anthropic/DeepSeek extraction was intentionally not run and is not claimed as evidence.
