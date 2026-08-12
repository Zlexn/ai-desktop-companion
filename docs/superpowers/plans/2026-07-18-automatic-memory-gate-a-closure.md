# Automatic Memory Gate A Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining Gate A automatic-memory path by centralizing transient canonical-hash deduplication in the local Governor, adding lifespan-owned shadow-job scheduling and provider composition, enforcing exclusive chat modes, exposing consent/job/audit diagnostics, and proving no active memory can change.

**Architecture:** The existing additive schema, metadata-only repository, extractor, Governor preflight/postflight checks, consent fence, and job service remain the foundation. The Governor becomes the sole owner of current-response transient deduplication; `ChatService` selects exactly one post-reply memory branch; a lifespan-owned `InProcessMemoryJobScheduler` reserves jobs synchronously and processes them outside the chat request. FastAPI owns shared chat and optional extractor providers, coordinates recovery and shutdown, and exposes metadata-only automation APIs.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLite, asyncio, existing `LLMProvider` adapters, pytest, pytest-asyncio, HTTPX TestClient, Uvicorn.

---

## 0. Execution contract, supersession, and file structure

This plan supersedes conflicting scheduler, lifecycle, mode-routing, and acceptance instructions in the older plan at `<project-root>\docs\superpowers\plans\2026-07-16-automatic-memory-gate-a-shadow-mode.md`. The frozen contracts in the approved July 18 closure specification remain authoritative:

- `MEMORY_AUTOMATION_MODE` permits only `off`, `candidate_confirmation`, and `shadow_auto`; configuration rejects `auto_active`.
- `MEMORY_EXTRACTOR_ROUTE` permits only `none`, `local`, `fake`, and `remote`.
- Every shadow job uses `turn_id == assistant_message.id` and schema version `memory-shadow-schema-v1`.
- Gate A never creates, updates, archives, deletes, confirms, dismisses, or otherwise changes rows in active-memory storage.
- Job and audit persistence/API responses remain metadata-only.
- The current repository is already dirty. Do not stage, commit, amend, push, reset, restore, clean, stash, or delete unrelated work.

Run backend commands from:

```powershell
Set-Location "<project-root>\backend"
```

Use the repository virtual environment if it exists; otherwise use the active Python interpreter that already has the project dependencies installed. Every task ends with a status/diff checkpoint, never a commit.

### Planned file changes

- Modify: `<project-root>\backend\app\services\memory_governor.py` — make canonical hash the only transient deduplication key and retain the first proposal in extractor order.
- Modify: `<project-root>\backend\app\services\memory_extractor.py` — remove all provider/local extractor pre-deduplication.
- Create: `<project-root>\backend\app\services\memory_job_scheduler.py` — non-blocking idempotent scheduling, startup recovery enqueueing, and controlled shutdown.
- Modify: `<project-root>\backend\app\services\chat_service.py` — exclusive `off | candidate_confirmation | shadow_auto` post-reply route.
- Modify: `<project-root>\backend\app\providers\factory.py` — selected remote memory-extractor factory and credentials-available predicate.
- Modify: `<project-root>\backend\app\api\dependencies.py` — shared lifespan chat-provider dependency, automation repository/fence/scheduler dependencies, and ChatService injection.
- Modify: `<project-root>\backend\app\api\routes\memories.py` — consent mutation plus bounded job/audit list APIs.
- Modify: `<project-root>\backend\app\main.py` — shared provider ownership, memory scheduler composition, recovery, and ordered shutdown.
- Modify: `<project-root>\backend\tests\test_memory_governor.py` — canonical-hash deduplication tests.
- Modify: `<project-root>\backend\tests\test_memory_extractor.py` — prove parser/local extractor preserve duplicate transient proposals for Governor handling.
- Create: `<project-root>\backend\tests\test_memory_job_scheduler.py` — scheduler reservation, duplicate, recovery, failure, and shutdown tests.
- Modify: `<project-root>\backend\tests\test_chat_memory_candidates.py` — mutually exclusive mode-routing tests.
- Modify: `<project-root>\backend\tests\test_api_memory_automation.py` — HTTP consent/job/audit safety, ordering, and pagination tests.
- Modify: `<project-root>\backend\tests\test_api_chat.py` — shared chat-provider and lifespan ownership tests.
- Modify: `<project-root>\backend\tests\test_provider_factory.py` — remote extractor factory tests.
- Modify: `<project-root>\backend\tests\conftest.py` — isolate every Gate A environment variable in API tests.
- Modify: `<project-root>\backend\tests\test_memory_job_service.py` — extend aggregate-count coverage for duplicate canonical hashes; reuse existing full-table snapshots rather than duplicating them.
- Create: `<project-root>\docs\automatic-memory-gate-a-acceptance-2026-07-18.md` — evidence-only acceptance record populated after actual commands run.

---

### Task 1: Centralize transient canonical-hash deduplication in `MemoryGovernor`

**Files:**
- Modify: `<project-root>\backend\app\services\memory_governor.py`
- Modify: `<project-root>\backend\app\services\memory_extractor.py`
- Modify: `<project-root>\backend\tests\test_memory_governor.py`
- Modify: `<project-root>\backend\tests\test_memory_extractor.py`
- Modify: `<project-root>\backend\tests\test_memory_job_service.py`

- [ ] **Step 1: Add the failing canonical-hash collision test to the Governor suite**

  Add this test to `test_memory_governor.py`. It proves that equal canonical hashes are deduplicated by the Governor after normalization, the first result survives, and later proposals receive a fixed metadata-only rejection code.

  ```python
  def test_governor_deduplicates_current_response_by_canonical_hash_in_first_seen_order(
      governor,
  ):
      first = proposal(
          subject="DRINK PREF",
          content="I LIKE COFFEE",
          confidence=0.91,
          source_message_ids=("user-1",),
      )
      duplicate = proposal(
          subject=" ＤＲＩＮＫ   ＰＲＥＦ ",
          content=" Ｉ   ＬＩＫＥ  ＣＯＦＦＥＥ ",
          confidence=0.42,
          source_message_ids=("user-1", "assistant-1"),
      )
      distinct = proposal(
          subject="运动偏好",
          content="用户喜欢游泳",
          confidence=0.88,
      )

      results = governor.evaluate_many(
          proposals=[first, duplicate, distinct],
          user_text="我喜欢黑咖啡，也喜欢游泳",
          user_message_id="user-1",
          assistant_message_id="assistant-1",
      )

      assert [
          (result.decision, result.reason_code)
          for result in results
      ] == [
          (MemoryGovernorDecision.CREATE, "eligible_shadow_create"),
          (MemoryGovernorDecision.REJECT, "duplicate_canonical_hash"),
          (MemoryGovernorDecision.CREATE, "eligible_shadow_create"),
      ]
      assert results[0].canonical_key is not None
      assert results[1].canonical_key is None
      assert results[2].canonical_key is not None
  ```

- [ ] **Step 2: Add the failing extractor-preservation tests**

  Add these tests to `test_memory_extractor.py`. Use the existing strict JSON fixture helper and current-turn message fixture constructors.

  ```python
  @pytest.mark.asyncio
  async def test_provider_extractor_preserves_duplicate_proposals_for_governor_handling():
      duplicate = proposal_document()
      provider = RecordingProvider(
          response_document([duplicate, duplicate])
      )
      extractor = ProviderMemoryExtractor(provider, settings())

      result = await extractor.extract(
          user_message=user_message(),
          assistant_message=assistant_message(),
      )

      assert [proposal.content for proposal in result.proposals] == [
          "用户喜欢黑咖啡",
          "用户喜欢黑咖啡",
      ]
  ```

  ```python
  @pytest.mark.asyncio
  async def test_local_extractor_preserves_repeated_current_turn_matches_for_governor():
      extractor = LocalMemoryExtractor(settings())
      current_user = user_message("我喜欢黑咖啡。我喜欢黑咖啡。")

      result = await extractor.extract(
          user_message=current_user,
          assistant_message=assistant_message(),
      )

      assert [proposal.content for proposal in result.proposals] == [
          "用户喜欢黑咖啡",
          "用户喜欢黑咖啡",
      ]
  ```

  Replace the existing provider test `test_provider_extractor_deduplicates_normalized_proposals_preserving_first` with `test_provider_extractor_preserves_duplicate_proposals_for_governor_handling`, and replace the existing local/fake tests named `test_local_extractor_deduplicates_repeated_matching_clauses` and `test_fake_provider_deduplicates_repeated_matching_clauses` so they expect two proposals in original order. Do not leave the old one-proposal assertions in place; those assertions encode the superseded extractor-owned policy.

  Add this complete test to `test_memory_job_service.py` immediately after the existing post-extraction rejection test:

  ```python
  @pytest.mark.asyncio
  async def test_duplicate_canonical_hash_is_counted_without_persisting_content(
      tmp_path: Path,
  ) -> None:
      with _environment(tmp_path, route=MemoryExtractorRoute.LOCAL) as env:
          database_url, ids, _, automation, messages, governor, extractor = env
          extractor.proposals = [
              MemoryGovernorProposal(
                  memory_type=MemoryType.PREFERENCE,
                  subject="DRINK PREF",
                  content="I LIKE COFFEE",
                  canonical_key_hint="first-remote-hint",
                  confidence=0.91,
                  source_message_ids=(ids["user_message_id"],),
              ),
              MemoryGovernorProposal(
                  memory_type=MemoryType.PREFERENCE,
                  subject=" ＤＲＩＮＫ   ＰＲＥＦ ",
                  content=" Ｉ   ＬＩＫＥ  ＣＯＦＦＥＥ ",
                  canonical_key_hint="different-remote-hint",
                  confidence=0.42,
                  source_message_ids=(
                      ids["user_message_id"],
                      ids["assistant_message_id"],
                  ),
              ),
          ]
          before = _memory_snapshot(database_url)
          job = _reserve(automation, ids, route=MemoryExtractorRoute.LOCAL)

          await _service(
              automation=automation,
              messages=messages,
              extractor=extractor,
              governor=governor,
              route=MemoryExtractorRoute.LOCAL,
          ).process(job.id)
          audit = _audit(automation, job.id)

      assert audit.proposal_count == 2
      assert audit.accepted_count == 1
      assert audit.rejected_count == 1
      assert audit.reason_counts == {
          "duplicate_canonical_hash": 1,
          "eligible_shadow_create": 1,
      }
      assert "I LIKE COFFEE" not in _database_text(database_url)
      assert _memory_snapshot(database_url) == before
  ```

- [ ] **Step 3: Run the focused tests and confirm RED**

  Run:

  ```powershell
  python -m pytest tests/test_memory_governor.py::test_governor_deduplicates_current_response_by_canonical_hash_in_first_seen_order tests/test_memory_extractor.py::test_provider_extractor_preserves_duplicate_proposals_for_governor_handling tests/test_memory_extractor.py::test_local_extractor_preserves_repeated_current_turn_matches_for_governor -q
  ```

  Expected: FAIL. The Governor currently marks the duplicate as `eligible_shadow_create`, while the provider/local extractors currently remove one or both duplicate proposals before the Governor can classify them.

- [ ] **Step 4: Replace extractor-side deduplication with Governor-owned canonical-hash deduplication**

  In `memory_extractor.py`, delete these extractor deduplication symbols completely:

  ```python
  def _normalize_dedup_text(value: str) -> str:
  ```

  ```python
  def _proposal_dedup_key(
      proposal: MemoryGovernorProposal,
  ) -> tuple[MemoryType, str, str, float, tuple[str, ...]]:
  ```

  ```python
  def _deduplicate_proposals(
      proposals: list[MemoryGovernorProposal],
  ) -> list[MemoryGovernorProposal]:
  ```

  Remove the `unicodedata` import if no other code in the file uses it.

  Replace the final statement of `ProviderMemoryExtractor._parse_response()` with:

  ```python
  return proposals
  ```

  In `_extract_local_proposals()`, remove the `seen` declaration and remove this entire conditional block:

  ```python
  key = _proposal_dedup_key(proposal)
  if key in seen:
      break
  ```

  Remove this statement from the local extractor:

  ```python
  seen.add(key)
  ```

  In `memory_governor.py`, replace the entire `evaluate_many()` method with this implementation:

  ```python
  def evaluate_many(
      self,
      *,
      proposals: list[MemoryGovernorProposal],
      user_text: str,
      user_message_id: str,
      assistant_message_id: str,
  ) -> list[MemoryGovernorResult]:
      results: list[MemoryGovernorResult] = []
      accepted_characters = 0
      accepted_proposals = 0
      accepted_canonical_hashes: set[str] = set()

      for candidate in proposals:
          result = self.evaluate(
              proposal=candidate,
              user_text=user_text,
              user_message_id=user_message_id,
              assistant_message_id=assistant_message_id,
          )
          if result.decision is not MemoryGovernorDecision.CREATE:
              results.append(result)
              continue

          assert result.canonical_key is not None
          if result.canonical_key in accepted_canonical_hashes:
              results.append(
                  _rejection(
                      "duplicate_canonical_hash",
                      confidence=result.confidence,
                  )
              )
              continue

          if accepted_proposals >= self._max_proposals:
              results.append(
                  _rejection(
                      "proposal_budget_exceeded",
                      confidence=result.confidence,
                  )
              )
              continue

          content_characters = len(candidate.content)
          if accepted_characters + content_characters > self._max_total_characters:
              results.append(
                  _rejection(
                      "turn_character_budget_exceeded",
                      confidence=result.confidence,
                  )
              )
              continue

          accepted_canonical_hashes.add(result.canonical_key)
          accepted_proposals += 1
          accepted_characters += content_characters
          results.append(result)

      return results
  ```

  This is intentionally current-response-only: `accepted_canonical_hashes` is local to one `evaluate_many()` invocation, is not persisted, and does not query `MemoryRepository`.

- [ ] **Step 5: Run focused regression tests and perform a no-commit checkpoint**

  Run:

  ```powershell
  python -m pytest tests/test_memory_governor.py tests/test_memory_extractor.py tests/test_memory_job_service.py -q
  ```

  Expected: PASS. Existing job-service aggregate counts treat `duplicate_canonical_hash` as a rejected proposal and persist only count maps, never proposal text or canonical hashes.

  Then run:

  ```powershell
  git status --short
  git diff --check
  git diff -- app/services/memory_governor.py app/services/memory_extractor.py tests/test_memory_governor.py tests/test_memory_extractor.py tests/test_memory_job_service.py
  ```

  Expected: `git diff --check` exits with code `0`. Do not run `git add` or `git commit`.

---

### Task 2: Add a lifespan-owned idempotent `MemoryJobScheduler`

**Files:**
- Create: `<project-root>\backend\app\services\memory_job_scheduler.py`
- Create: `<project-root>\backend\tests\test_memory_job_scheduler.py`

- [ ] **Step 1: Write the failing non-blocking reservation and duplicate-scheduling test**

  Create `test_memory_job_scheduler.py` with this test support and test. The callbacks model the repository transaction and worker boundaries without sharing a SQLite connection.

  ```python
  import asyncio
  from dataclasses import dataclass

  import pytest

  from app.domain.models import (
      MemoryAutomationMode,
      MemoryExtractorRoute,
      MemoryJob,
      MemoryJobStatus,
  )
  from app.services.memory_job_scheduler import InProcessMemoryJobScheduler


  @dataclass
  class Reservation:
      job: MemoryJob
      created: bool


  def make_job(job_id: str, assistant_message_id: str) -> MemoryJob:
      from datetime import UTC, datetime
      from app.domain.models import MemoryAutomationMode, MemoryExtractorRoute

      return MemoryJob(
          id=job_id,
          turn_id=assistant_message_id,
          schema_version="memory-shadow-schema-v1",
          session_id="session-1",
          user_message_id="user-1",
          assistant_message_id=assistant_message_id,
          mode=MemoryAutomationMode.SHADOW_AUTO,
          extractor_route=MemoryExtractorRoute.FAKE,
          status=MemoryJobStatus.PENDING,
          attempt_count=0,
          outcome=None,
          error_category=None,
          governor_version="memory-governor-rules-v1",
          consent_generation=None,
          created_at=datetime(2026, 7, 18, tzinfo=UTC),
          started_at=None,
          finished_at=None,
      )


  @pytest.mark.asyncio
  async def test_schedule_reserves_once_returns_before_worker_completion_and_deduplicates():
      release = asyncio.Event()
      started = asyncio.Event()
      reserve_calls: list[tuple[str, str, str]] = []
      worker_calls: list[str] = []
      first_job = make_job("job-1", "assistant-1")

      def reserve_job(**kwargs):
          reserve_calls.append(
              (
                  kwargs["session_id"],
                  kwargs["user_message_id"],
                  kwargs["assistant_message_id"],
              )
          )
          return first_job, len(reserve_calls) == 1

      async def run_job(job_id: str) -> None:
          worker_calls.append(job_id)
          started.set()
          await release.wait()

      scheduler = InProcessMemoryJobScheduler(
          reserve_job=reserve_job,
          run_job=run_job,
          recover_job_ids=lambda: [],
          cancel_job=lambda job_id: None,
          mode=MemoryAutomationMode.SHADOW_AUTO,
          route=MemoryExtractorRoute.FAKE,
      )

      assert scheduler.schedule(
          session_id="session-1",
          user_message_id="user-1",
          assistant_message_id="assistant-1",
      )
      assert not scheduler.schedule(
          session_id="session-1",
          user_message_id="user-1",
          assistant_message_id="assistant-1",
      )

      await asyncio.wait_for(started.wait(), timeout=1)
      assert worker_calls == ["job-1"]
      assert reserve_calls == [
          ("session-1", "user-1", "assistant-1"),
          ("session-1", "user-1", "assistant-1"),
      ]

      release.set()
      await scheduler.shutdown()

      assert worker_calls == ["job-1"]
  ```

- [ ] **Step 2: Write the failing recovery and cancellation tests**

  Add these tests to the same file.

  ```python
  @pytest.mark.asyncio
  async def test_recover_enqueues_existing_pending_ids_in_repository_order():
      started: list[str] = []

      async def run_job(job_id: str) -> None:
          started.append(job_id)

      scheduler = InProcessMemoryJobScheduler(
          reserve_job=lambda **kwargs: (_ for _ in ()).throw(
              AssertionError("recovery must not reserve a second job")
          ),
          run_job=run_job,
          recover_job_ids=lambda: ["job-early", "job-late"],
          cancel_job=lambda job_id: None,
          mode=MemoryAutomationMode.SHADOW_AUTO,
          route=MemoryExtractorRoute.LOCAL,
      )

      assert await scheduler.recover() == 2
      await scheduler.shutdown()

      assert started == ["job-early", "job-late"]
  ```

  ```python
  @pytest.mark.asyncio
  async def test_shutdown_cancel_records_each_running_job_once():
      release = asyncio.Event()
      cancelled: list[str] = []
      job = make_job("job-1", "assistant-1")

      async def run_job(job_id: str) -> None:
          await release.wait()

      scheduler = InProcessMemoryJobScheduler(
          reserve_job=lambda **kwargs: (job, True),
          run_job=run_job,
          recover_job_ids=lambda: [],
          cancel_job=cancelled.append,
          mode=MemoryAutomationMode.SHADOW_AUTO,
          route=MemoryExtractorRoute.FAKE,
      )
      assert scheduler.schedule(
          session_id="session-1",
          user_message_id="user-1",
          assistant_message_id="assistant-1",
      )

      await scheduler.shutdown(cancel=True)

      assert cancelled == ["job-1"]
      assert not scheduler.schedule(
          session_id="session-1",
          user_message_id="user-2",
          assistant_message_id="assistant-2",
      )
  ```

  Add these complete tests before implementation:

  ```python
  @pytest.mark.asyncio
  async def test_worker_exception_is_consumed_without_loop_exception_leak():
      loop = asyncio.get_running_loop()
      leaked: list[dict[str, object]] = []
      previous = loop.get_exception_handler()
      loop.set_exception_handler(lambda _loop, context: leaked.append(context))
      job = make_job("job-1", "assistant-1")

      async def run_job(_job_id: str) -> None:
          raise RuntimeError("SECRET_SENTINEL")

      try:
          scheduler = InProcessMemoryJobScheduler(
              reserve_job=lambda **kwargs: (job, True),
              run_job=run_job,
              recover_job_ids=lambda: [],
              cancel_job=lambda job_id: None,
              mode=MemoryAutomationMode.SHADOW_AUTO,
              route=MemoryExtractorRoute.FAKE,
          )
          assert scheduler.schedule(
              session_id="session-1",
              user_message_id="user-1",
              assistant_message_id="assistant-1",
          )
          await scheduler.shutdown()
          await asyncio.sleep(0)
      finally:
          loop.set_exception_handler(previous)

      assert all("SECRET_SENTINEL" not in str(item) for item in leaked)
  ```

  ```python
  @pytest.mark.asyncio
  async def test_recovery_and_schedule_share_one_active_runner_per_job_id():
      release = asyncio.Event()
      started = asyncio.Event()
      worker_calls: list[str] = []
      job = make_job("job-1", "assistant-1")

      async def run_job(job_id: str) -> None:
          worker_calls.append(job_id)
          started.set()
          await release.wait()

      scheduler = InProcessMemoryJobScheduler(
          reserve_job=lambda **kwargs: (job, True),
          run_job=run_job,
          recover_job_ids=lambda: ["job-1"],
          cancel_job=lambda job_id: None,
          mode=MemoryAutomationMode.SHADOW_AUTO,
          route=MemoryExtractorRoute.FAKE,
      )

      assert await scheduler.recover() == 1
      await started.wait()
      assert scheduler.schedule(
          session_id="session-1",
          user_message_id="user-1",
          assistant_message_id="assistant-1",
      )
      await asyncio.sleep(0)
      assert worker_calls == ["job-1"]

      release.set()
      await scheduler.shutdown()
  ```

  Add `test_shutdown_cancel_only_terminalizes_tasks_cancelled_by_shutdown`: reserve `job-finished` and `job-blocked`, let the first worker return and `await asyncio.sleep(0)` so its done callback runs, keep the second worker waiting, call `shutdown(cancel=True)`, and assert the cancellation callback receives only `job-blocked`. This covers the completion/cancellation race and prevents a successful terminal job from being relabeled.

- [ ] **Step 3: Run scheduler tests and confirm RED**

  Run:

  ```powershell
  python -m pytest tests/test_memory_job_scheduler.py -q
  ```

  Expected: collection FAIL with:

  ```text
  ModuleNotFoundError: No module named 'app.services.memory_job_scheduler'
  ```

- [ ] **Step 4: Implement the scheduler protocol and in-process scheduler**

  Create `memory_job_scheduler.py` with this implementation.

  ```python
  from __future__ import annotations

  import asyncio
  from collections.abc import Awaitable, Callable
  from typing import Protocol

  from app.domain.models import (
      MemoryAutomationMode,
      MemoryExtractorRoute,
      MemoryJob,
  )


  from app.services.memory_extractor import MEMORY_EXTRACTION_SCHEMA_VERSION
  from app.services.memory_governor import MEMORY_GOVERNOR_VERSION


  class MemoryJobScheduler(Protocol):
      def schedule(
          self,
          *,
          session_id: str,
          user_message_id: str,
          assistant_message_id: str,
      ) -> bool: ...


  class NoOpMemoryJobScheduler:
      def schedule(
          self,
          *,
          session_id: str,
          user_message_id: str,
          assistant_message_id: str,
      ) -> bool:
          return False


  class InProcessMemoryJobScheduler:
      def __init__(
          self,
          *,
          reserve_job: Callable[..., tuple[MemoryJob, bool]],
          run_job: Callable[[str], Awaitable[None]],
          recover_job_ids: Callable[[], list[str]],
          cancel_job: Callable[[str], None],
          mode: MemoryAutomationMode,
          route: MemoryExtractorRoute,
      ) -> None:
          if mode is not MemoryAutomationMode.SHADOW_AUTO:
              raise ValueError("memory job scheduler requires shadow_auto mode")

          self._reserve_job = reserve_job
          self._run_job = run_job
          self._recover_job_ids = recover_job_ids
          self._cancel_job = cancel_job
          self._route = route
          self._accepting = True
          self._tasks: dict[str, asyncio.Task[None]] = {}

      def schedule(
          self,
          *,
          session_id: str,
          user_message_id: str,
          assistant_message_id: str,
      ) -> bool:
          if not self._accepting:
              return False

          job, created = self._reserve_job(
              turn_id=assistant_message_id,
              schema_version=MEMORY_EXTRACTION_SCHEMA_VERSION,
              session_id=session_id,
              user_message_id=user_message_id,
              assistant_message_id=assistant_message_id,
              mode=MemoryAutomationMode.SHADOW_AUTO,
              extractor_route=self._route,
              governor_version=MEMORY_GOVERNOR_VERSION,
          )
          if not created:
              return False

          self._start(job.id)
          return True

      async def recover(self) -> int:
          if not self._accepting:
              return 0

          job_ids = self._recover_job_ids()
          started = 0
          for job_id in job_ids:
              started += int(self._start(job_id))
          return started

      async def shutdown(self, *, cancel: bool = False) -> None:
          self._accepting = False
          tasks = list(self._tasks.items())

          cancelled_job_ids: list[str] = []
          if cancel:
              for job_id, task in tasks:
                  if not task.done():
                      task.cancel()
                      cancelled_job_ids.append(job_id)

          if tasks:
              await asyncio.gather(
                  *(task for _, task in tasks),
                  return_exceptions=True,
              )

          for job_id in cancelled_job_ids:
              self._cancel_job(job_id)

      def _start(self, job_id: str) -> bool:
          active = self._tasks.get(job_id)
          if active is not None and not active.done():
              return False

          task = asyncio.create_task(
              self._run_job(job_id),
              name=f"memory-job-{job_id}",
          )
          self._tasks[job_id] = task
          task.add_done_callback(
              lambda completed, completed_job_id=job_id: self._consume_task(
                  completed_job_id,
                  completed,
              )
          )
          return True

      def _consume_task(self, job_id: str, task: asyncio.Task[None]) -> None:
          if self._tasks.get(job_id) is task:
              self._tasks.pop(job_id, None)
          if task.cancelled():
              return
          try:
              task.exception()
          except asyncio.CancelledError:
              return
  ```

  `MemoryJobScheduler.schedule()` intentionally returns immediately after the short `reserve_job()` transaction. It does not load messages, run the Governor, call an extractor, access active memory, or await a provider.

- [ ] **Step 5: Run scheduler tests and perform a no-commit checkpoint**

  Run:

  ```powershell
  python -m pytest tests/test_memory_job_scheduler.py -q
  ```

  Expected: PASS.

  Then run:

  ```powershell
  git status --short
  git diff --check
  git diff -- app/services/memory_job_scheduler.py tests/test_memory_job_scheduler.py
  ```

  Expected: only the intended new scheduler source and test appear for this task. Do not stage or commit.

---

### Task 3: Route `ChatService` through exactly one memory automation mode

**Files:**
- Modify: `<project-root>\backend\app\services\chat_service.py`
- Modify: `<project-root>\backend\tests\test_chat_memory_candidates.py`
- Modify: `<project-root>\backend\tests\test_chat_service.py`

- [ ] **Step 1: Add service-level failing mutually exclusive route tests**

  Add `from dataclasses import replace` to `test_chat_service.py`, then add this recording scheduler and parameterized test using the existing repository constructors directly. This avoids relying on a fixture factory that does not exist in the current suite.

  ```python
  class RecordingMemoryJobScheduler:
      def __init__(self, *, fail: bool = False) -> None:
          self.fail = fail
          self.calls: list[tuple[str, str, str]] = []

      def schedule(
          self,
          *,
          session_id: str,
          user_message_id: str,
          assistant_message_id: str,
      ) -> bool:
          if self.fail:
              raise RuntimeError("scheduler failure")
          self.calls.append(
              (session_id, user_message_id, assistant_message_id)
          )
          return True
  ```

  ```python
  @pytest.mark.asyncio
  @pytest.mark.parametrize(
      ("mode", "expected_pending", "expected_scheduler_calls"),
      [
          ("off", 0, 0),
          ("candidate_confirmation", 1, 0),
          ("shadow_auto", 0, 1),
      ],
  )
  async def test_completed_turn_uses_exactly_one_memory_mode_branch(
      tmp_path: Path,
      mode: str,
      expected_pending: int,
      expected_scheduler_calls: int,
  ) -> None:
      database_url = f"sqlite:///{tmp_path / f'{mode}.db'}"
      with managed_connection(database_url) as connection:
          sessions = SessionRepository(connection)
          messages = MessageRepository(connection)
          memories = MemoryRepository(connection)
          session = sessions.create(mode)
          settings = Settings(
              llm_model="test-model",
              memory_automation_mode=mode,
              memory_candidates_enabled=True,
          )
          scheduler = RecordingMemoryJobScheduler()
          service = ChatService(
              sessions,
              messages,
              ContextBuilder(messages, 12),
              default_prompt_renderer(),
              FakeProvider(),
              settings,
              memory_candidates=MemoryCandidateService(
                  memories,
                  settings,
              ),
              memory_job_scheduler=scheduler,
          )

          reply = await service.send_message(
              session.id,
              "我喜欢红茶。",
          )

          assert len(memories.list(status=MemoryStatus.PENDING)) == expected_pending
          assert len(scheduler.calls) == expected_scheduler_calls
          if scheduler.calls:
              scheduled_session, user_id, assistant_id = scheduler.calls[0]
              stored = messages.list(session.id)
              assert scheduled_session == session.id
              assert user_id == stored[0].id
              assert assistant_id == reply.assistant_message_id == stored[1].id
  ```

  Keep `test_chat_memory_candidates.py` as the HTTP regression suite: its existing default candidate test must continue to pass, and Task 5 will add lifespan-backed `off` and `shadow_auto` HTTP assertions.

- [ ] **Step 2: Add the failing best-effort scheduling test**

  Add this test to `test_chat_service.py`.

  ```python
  @pytest.mark.asyncio
  async def test_shadow_scheduler_failure_does_not_rollback_persisted_reply(
      tmp_path: Path,
  ) -> None:
      database_url = f"sqlite:///{tmp_path / 'shadow-scheduler-failure.db'}"
      with managed_connection(database_url) as connection:
          sessions = SessionRepository(connection)
          messages = MessageRepository(connection)
          session = sessions.create("shadow scheduler failure")
          service = ChatService(
              sessions,
              messages,
              ContextBuilder(messages, 12),
              default_prompt_renderer(),
              FakeProvider(),
              Settings(
                  llm_model="test-model",
                  memory_automation_mode="shadow_auto",
              ),
              memory_job_scheduler=RecordingMemoryJobScheduler(fail=True),
          )

          reply = await service.send_message(session.id, "我喜欢红茶。")

          stored = messages.list(session.id)
          assert reply.assistant_message_id == stored[-1].id
          assert [message.role for message in stored] == [
              ChatRole.USER,
              ChatRole.ASSISTANT,
          ]
  ```

- [ ] **Step 3: Run chat-memory tests and confirm RED**

  Run:

  ```powershell
  python -m pytest tests/test_chat_service.py::test_completed_turn_uses_exactly_one_memory_mode_branch tests/test_chat_service.py::test_shadow_scheduler_failure_does_not_rollback_persisted_reply tests/test_chat_memory_candidates.py -q
  ```

  Expected: FAIL because `ChatService.__init__()` does not accept `memory_job_scheduler`, and the current candidate path runs whenever a candidate service is provided regardless of automation mode.

- [ ] **Step 4: Inject the scheduler and replace the unconditional candidate block**

  Add this import in `chat_service.py`:

  ```python
  from app.services.memory_job_scheduler import MemoryJobScheduler
  ```

  Add this optional constructor parameter immediately after `memory_candidates`:

  ```python
  memory_job_scheduler: MemoryJobScheduler | None = None,
  ```

  Assign it in the constructor:

  ```python
  self._memory_job_scheduler = memory_job_scheduler
  ```

  Replace the existing unconditional `if self._memory_candidates is not None:` block with this exclusive mode branch:

  ```python
  if self._settings.memory_automation_mode == "candidate_confirmation":
      if self._memory_candidates is not None:
          try:
              await self._memory_candidates.create_candidates_from_user_text(
                  session_id=session_id,
                  user_text=clean_text,
              )
          except Exception:
              pass
  elif self._settings.memory_automation_mode == "shadow_auto":
      if self._memory_job_scheduler is not None:
          try:
              self._memory_job_scheduler.schedule(
                  session_id=session_id,
                  user_message_id=user_message.id,
                  assistant_message_id=assistant_message.id,
              )
          except Exception:
              pass
  ```

  Keep this branch after assistant-message persistence and expression-plan creation. Keep summary and emotion scheduling in their existing relative order. Do not add an `auto_active` branch and do not schedule any shadow work in `off`.

- [ ] **Step 5: Run chat regressions and perform a no-commit checkpoint**

  Run:

  ```powershell
  python -m pytest tests/test_chat_memory_candidates.py tests/test_chat_service.py tests/test_memory_candidate_service.py -q
  ```

  Expected: PASS. Candidate-confirmation mode creates only legacy pending candidates; shadow mode schedules only a shadow job; off creates neither.

  Then run:

  ```powershell
  git status --short
  git diff --check
  git diff -- app/services/chat_service.py tests/test_chat_memory_candidates.py tests/test_chat_service.py
  ```

  Expected: `git diff --check` exits `0`. Do not stage or commit.

---

### Task 4: Add remote memory-provider factory and FastAPI dependencies

**Files:**
- Modify: `<project-root>\backend\app\providers\factory.py`
- Modify: `<project-root>\backend\app\api\dependencies.py`
- Modify: `<project-root>\backend\tests\test_provider_factory.py`
- Modify: `<project-root>\backend\tests\test_api_chat.py`

- [ ] **Step 1: Add failing provider-factory tests**

  Add these imports to `test_provider_factory.py`:

  ```python
  from app.providers.factory import (
      create_emotion_analysis_provider,
      create_memory_extractor_provider,
      create_named_provider,
      create_provider,
      memory_extractor_provider_is_configured,
  )
  ```

  Replace the existing one-line factory import with this block. Then add these tests; construct `Settings` directly because this file has no `settings` fixture.

  ```python
  def test_memory_extractor_provider_uses_memory_specific_deepseek_limits(
      monkeypatch,
  ):
      captured: dict[str, object] = {}

      def fake_create_named_provider(
          selected_settings,
          provider_name,
          *,
          deepseek_max_tokens,
          deepseek_timeout_seconds,
          deepseek_max_retries,
      ):
          captured["settings"] = selected_settings
          captured["provider_name"] = provider_name
          captured["max_tokens"] = deepseek_max_tokens
          captured["timeout_seconds"] = deepseek_timeout_seconds
          captured["max_retries"] = deepseek_max_retries
          return object()

      monkeypatch.setattr(
          "app.providers.factory.create_named_provider",
          fake_create_named_provider,
      )
      configured = Settings(
          deepseek_api_key="test-deepseek-key",
          memory_extractor_provider="deepseek",
          memory_extractor_model="memory-test-model",
          memory_extractor_max_tokens=512,
          memory_extractor_timeout_seconds=15.0,
          memory_extractor_max_retries=0,
      )

      create_memory_extractor_provider(configured)

      assert captured == {
          "settings": configured,
          "provider_name": "deepseek",
          "max_tokens": 512,
          "timeout_seconds": 15.0,
          "max_retries": 0,
      }
  ```

  ```python
  @pytest.mark.parametrize(
      ("provider_name", "anthropic_key", "deepseek_key", "expected"),
      [
          ("anthropic", None, None, False),
          ("anthropic", "test-anthropic-key", None, True),
          ("deepseek", None, None, False),
          ("deepseek", None, "test-deepseek-key", True),
      ],
  )
  def test_memory_extractor_provider_configuration_is_credential_specific(
      provider_name,
      anthropic_key,
      deepseek_key,
      expected,
  ):
      configured = Settings(
          memory_extractor_provider=provider_name,
          memory_extractor_model="memory-test-model",
          anthropic_api_key=anthropic_key,
          deepseek_api_key=deepseek_key,
      )

      assert memory_extractor_provider_is_configured(configured) is expected
  ```

- [ ] **Step 2: Record the shared-provider dependency test for Task 5**

  Do not add or run this test during the factory-only Task 4. Task 5 changes `get_llm_provider()` and the lifespan in one atomic GREEN step, then adds this direct dependency assertion using a minimal Starlette request:

  ```python
  from types import SimpleNamespace
  from starlette.requests import Request


  def test_get_llm_provider_returns_app_state_resource():
      provider = object()
      app = SimpleNamespace(state=SimpleNamespace(llm_provider=provider))
      request = Request(
          {
              "type": "http",
              "method": "GET",
              "scheme": "http",
              "path": "/",
              "headers": [],
              "server": ("testserver", 80),
              "client": ("testclient", 50000),
              "app": app,
          }
      )

      assert get_llm_provider(request) is provider
  ```

  Task 5 adds the actual `TestClient` assertion that two requests share one created provider and shutdown closes it once.

- [ ] **Step 3: Run factory/dependency tests and confirm RED**

  Run:

  ```powershell
  python -m pytest tests/test_provider_factory.py -q
  ```

  Expected: FAIL because `create_memory_extractor_provider` and `memory_extractor_provider_is_configured` do not exist.

- [ ] **Step 4: Add only the factory helpers**

  Append these functions to `factory.py`:

  ```python
  def memory_extractor_provider_is_configured(settings: Settings) -> bool:
      if settings.memory_extractor_provider == "anthropic":
          return bool(settings.anthropic_api_key)
      if settings.memory_extractor_provider == "deepseek":
          return bool(settings.deepseek_api_key)
      raise ValueError(
          "MEMORY_EXTRACTOR_PROVIDER must be one of: anthropic, deepseek"
      )


  def create_memory_extractor_provider(settings: Settings) -> LLMProvider:
      return create_named_provider(
          settings,
          settings.memory_extractor_provider,
          deepseek_max_tokens=settings.memory_extractor_max_tokens,
          deepseek_timeout_seconds=settings.memory_extractor_timeout_seconds,
          deepseek_max_retries=settings.memory_extractor_max_retries,
      )
  ```

- [ ] **Step 5: Run factory tests and perform a no-commit checkpoint**

  ```powershell
  python -m pytest tests/test_provider_factory.py -q
  ```

  Expected: PASS; no request dependency has changed yet, so the full API suite remains GREEN.

- [ ] **Step 6: Inspect the Task 4 diff**

  Run:

  ```powershell
  git status --short
  git diff --check
  git diff -- app/providers/factory.py tests/test_provider_factory.py
  ```

  Expected: no whitespace errors. Do not stage or commit.

---

### Task 5: Compose FastAPI lifespan, shadow recovery, and ordered shutdown

**Files:**
- Modify: `<project-root>\backend\app\api\dependencies.py`
- Modify: `<project-root>\backend\app\main.py`
- Modify: `<project-root>\backend\tests\conftest.py`
- Modify: `<project-root>\backend\tests\test_api_chat.py`
- Modify: `<project-root>\backend\tests\test_memory_job_scheduler.py`

- [ ] **Step 1: Isolate Gate A environment variables and add failing lifecycle tests**

  At the start of Task 5 Step 1, add the `test_get_llm_provider_returns_app_state_resource` test specified in Task 4 Step 2 to `test_api_chat.py`; it belongs to the same RED/GREEN batch as the lifespan implementation.

  Extend the environment cleanup tuple in `backend/tests/conftest.py` with every Gate A name before constructing `create_app()`:

  ```python
  "MEMORY_AUTOMATION_MODE",
  "MEMORY_EXTRACTOR_ROUTE",
  "MEMORY_EXTRACTOR_PROVIDER",
  "MEMORY_EXTRACTOR_MODEL",
  "MEMORY_EXTRACTOR_MAX_TOKENS",
  "MEMORY_EXTRACTOR_TIMEOUT_SECONDS",
  "MEMORY_EXTRACTOR_MAX_RETRIES",
  "MEMORY_EXTRACTOR_MAX_PROPOSALS",
  "MEMORY_EXTRACTOR_MAX_PROPOSAL_CHARACTERS",
  "MEMORY_EXTRACTOR_MAX_TOTAL_CHARACTERS",
  ```

  Also delete `ANTHROPIC_API_KEY` and `DEEPSEEK_API_KEY` in this fixture before setting `LLM_PROVIDER=fake`; individual tests that need a key must set it explicitly and clear `get_settings` before `create_app()`.

  Add a lifecycle test that monkeypatches recording provider/scheduler resources and verifies construction once and shutdown order. The test patches `app.main.get_settings` to return the explicit `Settings` object shown below; do not introduce new settings fixtures.

  ```python
  def test_lifespan_closes_memory_scheduler_before_memory_and_chat_providers(
      monkeypatch,
      tmp_path,
  ):
      events: list[str] = []
      settings = Settings(
          database_url=f"sqlite:///{tmp_path / 'lifespan-order.db'}",
          llm_provider="fake",
          llm_model="test-model",
          memory_automation_mode="shadow_auto",
          memory_extractor_route="remote",
          memory_extractor_provider="anthropic",
          memory_extractor_model="memory-test-model",
          anthropic_api_key="test-anthropic-key",
      )

      class ClosableProvider:
          async def generate(self, messages, options):
              raise AssertionError("test provider must not generate")

          async def aclose(self):
              events.append("chat_provider_close")

      class ClosableMemoryProvider:
          async def generate(self, messages, options):
              raise AssertionError("test provider must not generate")

          async def aclose(self):
              events.append("memory_provider_close")

      class RecordingScheduler:
          async def recover(self):
              return 0

          async def shutdown(self, *, cancel=False):
              events.append("memory_scheduler_shutdown")

      monkeypatch.setattr("app.main.get_settings", lambda: settings)
      monkeypatch.setattr(
          "app.main.InProcessMemoryJobScheduler",
          lambda **kwargs: RecordingScheduler(),
      )

      app = create_app(
          chat_provider_factory=ClosableProvider,
          memory_extractor_provider_factory=ClosableMemoryProvider,
      )

      with TestClient(app):
          assert app.state.llm_provider is not None

      assert events.index("memory_scheduler_shutdown") < events.index(
          "memory_provider_close"
      )
      assert events.index("memory_provider_close") < events.index(
          "chat_provider_close"
      )
  ```

  The explicit `Settings(...)` block above is complete; do not introduce additional fixtures for settings or database URLs.

  Then add this complete shared-provider test in `test_api_chat.py`:

  ```python
  def test_two_chat_requests_share_one_lifespan_provider_and_close_once(
      monkeypatch,
      tmp_path,
  ):
      calls = 0
      closes = 0

      class RecordingProvider:
          async def generate(self, messages, options):
              nonlocal calls
              calls += 1
              return LLMResponse(
                  text="recorded reply",
                  provider="recording",
                  model=options.model,
              )

          async def aclose(self):
              nonlocal closes
              closes += 1

      settings = Settings(
          database_url=f"sqlite:///{tmp_path / 'shared-chat-provider.db'}",
          llm_provider="fake",
          llm_model="test-model",
          memory_automation_mode="off",
      )
      monkeypatch.setattr("app.main.get_settings", lambda: settings)
      provider = RecordingProvider()
      app = create_app(chat_provider_factory=lambda: provider)

      with TestClient(app) as test_client:
          session = test_client.post(
              "/api/sessions",
              json={"title": "shared provider"},
          ).json()
          for content in ("first", "second"):
              response = test_client.post(
                  f"/api/sessions/{session['id']}/messages",
                  json={"content": content},
              )
              assert response.status_code == 200
          assert app.state.llm_provider is provider
          assert calls == 2
          assert closes == 0

      assert closes == 1
  ```

- [ ] **Step 2: Add failing recovery and missing-credential behavior tests**

  Implement the repository-backed recovery test with the following concrete support in `test_api_chat.py`:

  ```python
  import json
  import time

  from app.domain.models import (
      MemoryAutomationMode,
      MemoryExtractionConsentStatus,
      MemoryExtractorRoute,
      MemoryJobAuditOutcome,
      MemoryJobStatus,
  )
  from app.repositories.memory_automation import MemoryAutomationRepository
  from app.repositories.sessions import SessionRepository
  from app.services.memory_extraction_dispatch import (
      MEMORY_EXTRACTION_DISCLOSED_FIELDS,
      MEMORY_EXTRACTION_DISCLOSURE_VERSION,
      MEMORY_EXTRACTION_PURPOSE,
  )
  from app.services.memory_extractor import MEMORY_EXTRACTION_SCHEMA_VERSION
  from app.services.memory_governor import MEMORY_GOVERNOR_VERSION
  ```

  ```python
  def configure_gate_a(
      monkeypatch,
      tmp_path: Path,
      *,
      name: str,
      mode: str,
      route: str,
      anthropic_api_key: str | None = None,
  ) -> str:
      database_url = f"sqlite:///{tmp_path / f'{name}.db'}"
      values = {
          "DATABASE_URL": database_url,
          "LLM_PROVIDER": "fake",
          "LLM_MODEL": "test-model",
          "MEMORY_AUTOMATION_MODE": mode,
          "MEMORY_EXTRACTOR_ROUTE": route,
          "MEMORY_EXTRACTOR_PROVIDER": "anthropic",
          "MEMORY_EXTRACTOR_MODEL": "memory-test-model",
          "MEMORY_CANDIDATES_ENABLED": "false",
          "SESSION_SUMMARY_PROVIDER": "fake",
          "EMOTION_ANALYSIS_ENABLED": "false",
      }
      for key, value in values.items():
          monkeypatch.setenv(key, value)
      if anthropic_api_key is None:
          monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
      else:
          monkeypatch.setenv("ANTHROPIC_API_KEY", anthropic_api_key)
      monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
      get_settings.cache_clear()
      return database_url
  ```

  ```python
  def seed_shadow_turn(
      database_url: str,
      *,
      title: str,
      created_at: str,
      mark_running: bool = False,
  ) -> tuple[str, str]:
      with managed_connection(database_url) as connection:
          sessions = SessionRepository(connection)
          messages = MessageRepository(connection)
          automation = MemoryAutomationRepository(connection)
          session = sessions.create(title)
          user = messages.add(session.id, ChatRole.USER, "我喜欢红茶。")
          assistant = messages.add(session.id, ChatRole.ASSISTANT, "知道了。")
          job, created = automation.reserve_job(
              turn_id=assistant.id,
              schema_version=MEMORY_EXTRACTION_SCHEMA_VERSION,
              session_id=session.id,
              user_message_id=user.id,
              assistant_message_id=assistant.id,
              mode=MemoryAutomationMode.SHADOW_AUTO,
              extractor_route=MemoryExtractorRoute.REMOTE,
              governor_version=MEMORY_GOVERNOR_VERSION,
          )
          assert created
          connection.execute(
              "UPDATE memory_jobs SET created_at = ? WHERE id = ?",
              (created_at, job.id),
          )
          connection.commit()
          if mark_running:
              automation.update_job_status(job.id, status=MemoryJobStatus.RUNNING)
          return job.id, user.id
  ```

  ```python
  class BlockingRemoteMemoryProvider:
      def __init__(self) -> None:
          self.started_user_ids: list[str] = []
          self.started = threading.Event()
          self.release = threading.Event()
          self.closed = 0

      async def generate(self, messages, options) -> LLMResponse:
          payload = json.loads(messages[1].content)
          self.started_user_ids.append(payload["user_message"]["id"])
          self.started.set()
          await asyncio.to_thread(self.release.wait)
          return LLMResponse(
              text=json.dumps(
                  {
                      "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
                      "proposals": [],
                  }
              ),
              provider="blocking-memory-provider",
              model=options.model,
          )

      async def aclose(self) -> None:
          self.closed += 1
  ```

  The recovery test seeds early-running, late-pending, and terminal jobs. Grant exact consent with the frozen purpose/provider/disclosure fields, complete the terminal job before startup, start the app with `memory_extractor_provider_factory=lambda: provider`, and assert the Provider observes both recovered user IDs without asserting that the late task cannot start concurrently. The scheduler intentionally creates one task per recovered job; repository order is verified by the `recover_incomplete_jobs()` unit test and by recording `_start(job_id)` invocation order in `test_memory_job_scheduler.py`, while the shared dispatch fence—not scheduler serialization—controls remote sends. Release the blocking Provider, wait with a two-second `time.monotonic()` deadline for both IDs, then assert exactly three job rows remain, early attempts equal 2, late attempts equal 1, terminal attempts equal 0, and the provider closed once. Never manually call a context manager's `__enter__()`.

  Add a separate route=`remote`, no-key integration test that sends one fake chat turn and polls the repository through this helper:

  ```python
  def only_terminal_job(database_url: str):
      with managed_connection(database_url) as connection:
          jobs = MemoryAutomationRepository(connection).list_jobs(limit=10)
          if len(jobs) != 1:
              return None
          return (
              jobs[0]
              if jobs[0].status
              in {
                  MemoryJobStatus.SUCCEEDED,
                  MemoryJobStatus.FAILED,
                  MemoryJobStatus.CANCELLED,
              }
              else None
          )
  ```

  Pass a `memory_extractor_provider_factory` that raises if invoked, prove it is never called without credentials, and assert the terminal job is `SUCCEEDED/skipped_no_extractor`.

  For the HTTP mode matrix, add a parameterized test in `test_chat_memory_candidates.py` with:

  ```python
  @pytest.mark.parametrize(
      ("mode", "route", "candidates_enabled", "expected_jobs", "expected_candidates"),
      [
          ("off", "none", True, 0, 0),
          ("candidate_confirmation", "none", True, 0, 1),
          ("candidate_confirmation", "none", False, 0, 0),
          ("shadow_auto", "fake", True, 1, 0),
      ],
  )
  ```

  Each case uses a fresh database and `create_app()`/`TestClient`, sends one message through `/api/sessions/{id}/messages`, polls `GET /api/memories/jobs` with a two-second monotonic deadline when a job is expected, and asserts pending-memory and job counts match the table. Seed one active, pending, dismissed, and archived memory before the turn; compare those seeded rows before/after exactly and only allow the one expected new pending candidate in candidate-confirmation mode. Clear `get_settings` before and after each app context. This single matrix proves `off`, legacy-disabled, candidate, shadow, and the four-status non-mutation composition boundary.

- [ ] **Step 3: Run lifespan tests and confirm RED**

  Run:

  ```powershell
  python -m pytest tests/test_api_chat.py tests/test_chat_memory_candidates.py tests/test_memory_job_scheduler.py -q
  ```

  Expected: FAIL because the existing lifespan has no shared chat provider, no memory scheduler, no memory provider resource, and no memory-job recovery composition.

- [ ] **Step 4: Implement shared dependencies, provider ownership, scheduler composition, and ordered shutdown**

  First update `dependencies.py` atomically with the lifespan change. Add:

  ```python
  from app.repositories.memory_automation import MemoryAutomationRepository
  from app.services.memory_extraction_dispatch import MemoryExtractionDispatchFence
  from app.services.memory_job_scheduler import MemoryJobScheduler
  ```

  Replace `get_llm_provider()` with:

  ```python
  def get_llm_provider(request: Request) -> LLMProvider:
      return request.app.state.llm_provider
  ```

  Add `get_memory_automation_repository()`, `get_memory_extraction_dispatch_fence()`, and `get_memory_job_scheduler()` using the exact signatures from Task 6's route imports; inject the scheduler into `get_chat_service()` and pass `memory_job_scheduler=memory_job_scheduler` to `ChatService`. Do not add a request-scoped provider fallback.

  Add these exact dependency functions before `get_chat_service()`:

  ```python
  def get_memory_automation_repository(
      connection: sqlite3.Connection = Depends(get_connection),
  ) -> MemoryAutomationRepository:
      return MemoryAutomationRepository(connection)


  def get_memory_extraction_dispatch_fence(
      request: Request,
  ) -> MemoryExtractionDispatchFence:
      return request.app.state.memory_extraction_dispatch_fence


  def get_memory_job_scheduler(request: Request) -> MemoryJobScheduler:
      return request.app.state.memory_job_scheduler
  ```

  Add this parameter to `get_chat_service()` and pass it through:

  ```python
  memory_job_scheduler: MemoryJobScheduler = Depends(
      get_memory_job_scheduler
  ),
  ```

  Then add these imports to `main.py`:

  ```python
  from app.providers.factory import (
      create_emotion_analysis_provider,
      create_memory_extractor_provider,
      create_provider,
      memory_extractor_provider_is_configured,
  )
  from app.domain.models import (
      MemoryAutomationMode,
      MemoryExtractorRoute,
  )
  from app.repositories.memory_automation import MemoryAutomationRepository
  from app.services.memory_extraction_dispatch import (
      MemoryExtractionDispatchFence,
  )
  from app.services.memory_extractor import (
      LocalMemoryExtractor,
      MemoryExtractionFakeProvider,
      ProviderMemoryExtractor,
  )
  from app.services.memory_governor import (
      MEMORY_GOVERNOR_VERSION,
      MemoryGovernor,
  )
  from app.services.memory_job_scheduler import (
      InProcessMemoryJobScheduler,
  )
  from app.services.memory_job_service import MemoryJobService
  ```

  Add this capability guard above `create_app()`:

  ```python
  def validate_memory_automation_capability(settings) -> None:
      if settings.memory_automation_mode == "auto_active":
          raise ValueError(
              "MEMORY_AUTOMATION_MODE=auto_active is unavailable before Gate B"
          )
  ```

  At the start of `create_app()`, after obtaining settings, call:

  ```python
  validate_memory_automation_capability(settings)
  ```

  Add these optional factories to `create_app()` without changing existing callers:

  ```python
  def create_app(
      summary_provider_factory: Callable[[], SessionSummaryProvider] | None = None,
      emotion_analysis_provider_factory: Callable[[], LLMProvider | None] | None = None,
      chat_provider_factory: Callable[[], LLMProvider] | None = None,
      memory_extractor_provider_factory: Callable[[], LLMProvider | None] | None = None,
  ) -> FastAPI:
  ```

  Initialize every owned resource before entering one encompassing `try/finally`; all subsequent startup construction, including provider factories and scheduler recovery, must occur inside the `try`:

  ```python
  chat_provider: LLMProvider | None = None
  memory_provider: LLMProvider | None = None
  memory_scheduler: InProcessMemoryJobScheduler | None = None
  summary_provider: SessionSummaryProvider | None = None
  analysis_provider: LLMProvider | None = None
  summary_scheduler = None
  emotion_analysis_scheduler = None
  try:
      chat_provider = (
          chat_provider_factory()
          if chat_provider_factory is not None
          else create_provider(settings)
      )
      app.state.llm_provider = chat_provider
      # Construct schema, summary/emotion resources, memory fence/provider/scheduler,
      # call memory_scheduler.recover(), then yield — all inside this try.
      yield
  finally:
      # Apply the guarded shutdown order shown below.
  ```

  Do not place any owned-resource factory call before this `try`; otherwise partial startup bypasses cleanup.

  Before yielding from lifespan, create one fence:

  ```python
  memory_dispatch_fence = MemoryExtractionDispatchFence()
  app.state.memory_extraction_dispatch_fence = memory_dispatch_fence
  app.state.memory_job_scheduler = NoOpMemoryJobScheduler()
  memory_provider: LLMProvider | None = None
  memory_scheduler: InProcessMemoryJobScheduler | None = None
  ```

  For `shadow_auto`, construct the extractor by route:

  ```python
  if settings.memory_automation_mode == MemoryAutomationMode.SHADOW_AUTO.value:
      route = MemoryExtractorRoute(settings.memory_extractor_route)
      if route is MemoryExtractorRoute.LOCAL:
          extractor = LocalMemoryExtractor(settings)
      elif route is MemoryExtractorRoute.FAKE:
          extractor = ProviderMemoryExtractor(
              MemoryExtractionFakeProvider(settings),
              settings,
          )
      elif (
          route is MemoryExtractorRoute.REMOTE
          and memory_extractor_provider_is_configured(settings)
      ):
          memory_provider = (
              memory_extractor_provider_factory()
              if memory_extractor_provider_factory is not None
              else create_memory_extractor_provider(settings)
          )
          if memory_provider is None:
              extractor = None
          else:
              extractor = ProviderMemoryExtractor(memory_provider, settings)
      else:
          extractor = None

      governor = MemoryGovernor(
          max_proposals=settings.memory_extractor_max_proposals,
          max_proposal_characters=(
              settings.memory_extractor_max_proposal_characters
          ),
          max_total_characters=settings.memory_extractor_max_total_characters,
      )

      async def run_memory_job(job_id: str) -> None:
          with managed_connection(settings.database_url) as connection:
              service = MemoryJobService(
                  automation=MemoryAutomationRepository(connection),
                  messages=MessageRepository(connection),
                  extractor=extractor,
                  governor=governor,
                  route=route,
                  provider_name=settings.memory_extractor_provider,
                  dispatch_fence=memory_dispatch_fence,
              )
              await service.process(job_id)

      def reserve_memory_job(**kwargs):
          with managed_connection(settings.database_url) as connection:
              return MemoryAutomationRepository(connection).reserve_job(
                  **kwargs,
              )

      def recover_memory_job_ids() -> list[str]:
          with managed_connection(settings.database_url) as connection:
              return MemoryAutomationRepository(
                  connection
              ).recover_incomplete_jobs()

      def cancel_memory_job(job_id: str) -> None:
          with managed_connection(settings.database_url) as connection:
              MemoryAutomationRepository(connection).cancel_job(job_id)

      memory_scheduler = InProcessMemoryJobScheduler(
          reserve_job=reserve_memory_job,
          run_job=run_memory_job,
          recover_job_ids=recover_memory_job_ids,
          cancel_job=cancel_memory_job,
          mode=MemoryAutomationMode.SHADOW_AUTO,
          route=route,
      )
      app.state.memory_job_scheduler = memory_scheduler
      await memory_scheduler.recover()
  ```

  Replace the existing lifespan cleanup block with this ordered cleanup:

  ```python
  finally:
      if memory_scheduler is not None:
          await memory_scheduler.shutdown()
      if emotion_analysis_scheduler is not None:
          await emotion_analysis_scheduler.shutdown()
      if summary_scheduler is not None:
          await summary_scheduler.shutdown()
      if memory_provider is not None:
          await close_async_resource(memory_provider)
      if analysis_provider is not None:
          await close_async_resource(analysis_provider)
      if summary_provider is not None:
          await close_session_summary_provider(summary_provider)
      if chat_provider is not None:
          await close_async_resource(chat_provider)
  ```

  `NoOpMemoryJobScheduler` was already defined and tested in Task 2. Import it in `main.py`:

  ```python
  from app.services.memory_job_scheduler import NoOpMemoryJobScheduler
  ```

  Do not redefine the class in Task 5. For every non-`shadow_auto` mode, assign `app.state.memory_job_scheduler` to `NoOpMemoryJobScheduler()`; do not leave it as `None`. This keeps `get_chat_service()` total while `ChatService` still routes only the selected mode. The no-op object owns no task and needs no shutdown.

  Add a complete partial-startup cleanup test in `test_api_chat.py`:

  ```python
  def test_partial_lifespan_startup_closes_chat_provider_once(
      monkeypatch,
      tmp_path,
  ):
      closed = 0

      class ChatProvider:
          async def generate(self, messages, options):
              return LLMResponse(
                  text="reply",
                  provider="recording",
                  model=options.model,
              )

          async def aclose(self):
              nonlocal closed
              closed += 1

      settings = Settings(
          database_url=f"sqlite:///{tmp_path / 'partial-startup.db'}",
          llm_provider="fake",
          llm_model="test-model",
          memory_automation_mode="shadow_auto",
          memory_extractor_route="remote",
          memory_extractor_provider="anthropic",
          memory_extractor_model="memory-test-model",
          anthropic_api_key="test-anthropic-key",
      )
      monkeypatch.setattr("app.main.get_settings", lambda: settings)
      app = create_app(
          chat_provider_factory=ChatProvider,
          memory_extractor_provider_factory=lambda: (_ for _ in ()).throw(
              RuntimeError("memory provider startup failed")
          ),
      )

      with pytest.raises(RuntimeError, match="memory provider startup failed"):
          with TestClient(app):
              raise AssertionError("lifespan must fail before yielding")

      assert closed == 1
  ```

  This test forces provider/scheduler locals to be initialized before the encompassing `try/finally` and prevents leaks on partial startup.

  The scheduler shutdown occurs before its remote provider closes. The chat provider is created and closed once per application lifespan, not once per request. `none`, `local`, and `fake` routes do not create a remote memory provider.

- [ ] **Step 5: Run lifespan regressions and perform a no-commit checkpoint**

  Run:

  ```powershell
  python -m pytest tests/test_api_chat.py tests/test_chat_memory_candidates.py tests/test_memory_job_scheduler.py tests/test_provider_factory.py tests/test_memory_job_service.py -q
  ```

  Expected: PASS, with no unclosed `httpx.AsyncClient`, Anthropic client, destroyed task, or pending task warnings.

  Then run:

  ```powershell
  git status --short
  git diff --check
  git diff -- app/api/dependencies.py app/main.py tests/conftest.py tests/test_api_chat.py tests/test_chat_memory_candidates.py tests/test_memory_job_scheduler.py
  ```

  Expected: no diff whitespace errors. Do not stage or commit.

---

### Task 6: Add consent, job, and audit HTTP APIs with metadata-only responses

**Files:**
- Modify: `<project-root>\backend\app\api\routes\memories.py`
- Modify: `<project-root>\backend\tests\test_api_memory_automation.py`

- [ ] **Step 1: Add failing consent endpoint tests**

  Add HTTP tests using the existing `TestClient` fixture.

  ```python
  def test_get_memory_extraction_consent_defaults_to_unknown(client):
      response = client.get("/api/memories/extraction/consent")

      assert response.status_code == 200
      assert response.json() == {
          "scope_id": "default",
          "status": "unknown",
          "purpose": None,
          "provider": None,
          "disclosure_version": None,
          "disclosed_fields": [],
          "generation": 0,
          "deployment_route": "none",
          "deployment_provider": "anthropic",
          "deployment_configured": True,
          "created_at": response.json()["created_at"],
          "updated_at": response.json()["updated_at"],
      }
  ```

  ```python
  def test_put_memory_extraction_consent_grant_uses_configured_policy_identity(
      client,
  ):
      response = client.put(
          "/api/memories/extraction/consent",
          json={
              "action": "grant",
              "disclosure_version": "memory-extraction-disclosure-v1",
          },
      )

      payload = response.json()
      assert response.status_code == 200
      assert payload["status"] == "granted"
      assert payload["purpose"] == (
          "extract durable memory proposals from the current completed turn"
      )
      assert payload["provider"] == "anthropic"
      assert payload["disclosure_version"] == (
          "memory-extraction-disclosure-v1"
      )
      assert payload["disclosed_fields"] == [
          "user_message",
          "assistant_message",
      ]
      assert payload["generation"] == 1
  ```

- [ ] **Step 2: Add failing bounded list and privacy tests**

  Add these imports to `test_api_memory_automation.py`:

  ```python
  from app.core.config import get_settings
  from app.repositories.memory_automation import MemoryAutomationRepository
  from app.repositories.sqlite import managed_connection
  ```

  Add a local seed helper that opens the same database URL used by `client`:

  ```python
  def seed_completed_memory_jobs(count: int = 3) -> None:
      settings = get_settings()
      with managed_connection(settings.database_url) as connection:
          sessions = SessionRepository(connection)
          messages = MessageRepository(connection)
          automation = MemoryAutomationRepository(connection)
          session = sessions.create("automation api seed")
          for index in range(count):
              user = messages.add(
                  session.id,
                  ChatRole.USER,
                  f"user seed {index}",
              )
              assistant = messages.add(
                  session.id,
                  ChatRole.ASSISTANT,
                  f"assistant seed {index}",
              )
              job, created = automation.reserve_job(
                  turn_id=assistant.id,
                  schema_version="memory-shadow-schema-v1",
                  session_id=session.id,
                  user_message_id=user.id,
                  assistant_message_id=assistant.id,
                  mode=MemoryAutomationMode.SHADOW_AUTO,
                  extractor_route=MemoryExtractorRoute.LOCAL,
                  governor_version="memory-governor-rules-v1",
              )
              assert created
              automation.update_job_status(
                  job.id,
                  status=MemoryJobStatus.RUNNING,
              )
              automation.complete_job_with_audit(
                  job.id,
                  status=MemoryJobStatus.SUCCEEDED,
                  outcome=MemoryJobAuditOutcome.SHADOW_RECORDED,
                  decision_counts={},
                  reason_counts={},
                  proposal_count=0,
                  accepted_count=0,
                  rejected_count=0,
                  redaction_count=0,
                  provider="local",
                  model="memory-local-rules-v1",
                  elapsed_ms=1,
                  consent_generation=None,
              )
  ```

  Import `SessionRepository` and `MessageRepository` alongside the already imported domain enums. Then add this test; it does not depend on nonexistent fixtures.

  ```python
  def test_memory_job_and_audit_lists_are_bounded_sorted_and_metadata_only(
      client,
  ):
      seed_completed_memory_jobs(3)
      jobs_response = client.get("/api/memories/jobs?limit=2")
      audits_response = client.get("/api/memories/jobs/audits?limit=2")

      assert jobs_response.status_code == 200
      assert audits_response.status_code == 200
      assert len(jobs_response.json()) == 2
      assert len(audits_response.json()) == 2
      assert jobs_response.json()[0]["created_at"] >= jobs_response.json()[1][
          "created_at"
      ]
      assert audits_response.json()[0]["created_at"] >= audits_response.json()[1][
          "created_at"
      ]

      forbidden_keys = {
          "content",
          "prompt",
          "response",
          "user_text",
          "assistant_text",
          "proposal",
          "authorization",
          "api_key",
      }
      for payload in (
          jobs_response.json(),
          audits_response.json(),
      ):
          assert forbidden_keys.isdisjoint(
              key
              for item in payload
              for key in item
          )
  ```

  Add exact input-limit assertions:

  ```python
  @pytest.mark.parametrize("path", [
      "/api/memories/jobs?limit=0",
      "/api/memories/jobs?limit=101",
      "/api/memories/jobs/audits?limit=0",
      "/api/memories/jobs/audits?limit=101",
  ])
  def test_memory_automation_list_limits_are_strict(client, path):
      assert client.get(path).status_code == 422
  ```

  Add this route-level integration test after the bounded list tests. It uses the real lifespan fence, not a test double:

  ```python
  import asyncio
  import json
  import threading
  import time
  from pathlib import Path

  from app.main import create_app
  from app.providers.base import LLMResponse
  from app.services.memory_extractor import MEMORY_EXTRACTION_SCHEMA_VERSION


  class BlockingConsentFenceProvider:
      def __init__(self) -> None:
          self.started = threading.Event()
          self.release = threading.Event()
          self.calls = 0

      async def generate(self, messages, options) -> LLMResponse:
          self.calls += 1
          self.started.set()
          await asyncio.to_thread(self.release.wait)
          disclosed = json.loads(messages[1].content)
          return LLMResponse(
              text=json.dumps(
                  {
                      "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
                      "proposals": [
                          {
                              "memory_type": "preference",
                              "subject": "drink",
                              "content": "SECRET_SENTINEL_SHOULD_NOT_PERSIST",
                              "canonical_key_hint": None,
                              "confidence": 0.9,
                              "source_message_ids": [
                                  disclosed["user_message"]["id"]
                              ],
                          }
                      ],
                  }
              ),
              provider="blocking-test-provider",
              model=options.model,
          )

      async def aclose(self) -> None:
          return None
  ```

  ```python
  def test_revoke_route_shares_lifespan_fence_with_inflight_remote_job(
      monkeypatch,
      tmp_path: Path,
  ) -> None:
      database_url = f"sqlite:///{tmp_path / 'route-fence.db'}"
      for name, value in {
          "DATABASE_URL": database_url,
          "LLM_PROVIDER": "fake",
          "LLM_MODEL": "test-model",
          "MEMORY_AUTOMATION_MODE": "shadow_auto",
          "MEMORY_EXTRACTOR_ROUTE": "remote",
          "MEMORY_EXTRACTOR_PROVIDER": "anthropic",
          "MEMORY_EXTRACTOR_MODEL": "memory-test-model",
          "ANTHROPIC_API_KEY": "test-anthropic-key",
          "MEMORY_CANDIDATES_ENABLED": "false",
          "EMOTION_ANALYSIS_ENABLED": "false",
          "SESSION_SUMMARY_PROVIDER": "fake",
      }.items():
          monkeypatch.setenv(name, value)
      get_settings.cache_clear()
      provider = BlockingConsentFenceProvider()
      app = create_app(memory_extractor_provider_factory=lambda: provider)

      with TestClient(app) as test_client:
          grant = test_client.put(
              "/api/memories/extraction/consent",
              json={
                  "action": "grant",
                  "disclosure_version": "memory-extraction-disclosure-v1",
              },
          )
          assert grant.status_code == 200
          session = test_client.post(
              "/api/sessions",
              json={"title": "fence"},
          ).json()
          chat = test_client.post(
              f"/api/sessions/{session['id']}/messages",
              json={"content": "我喜欢红茶。"},
          )
          assert chat.status_code == 200
          assert provider.started.wait(timeout=1)

          result: dict[str, object] = {}

          def revoke() -> None:
              result["response"] = test_client.put(
                  "/api/memories/extraction/consent",
                  json={
                      "action": "revoke",
                      "disclosure_version": "memory-extraction-disclosure-v1",
                  },
              )

          revoker = threading.Thread(target=revoke)
          revoker.start()
          deadline = time.monotonic() + 2
          while not app.state.memory_extraction_dispatch_fence.has_pending_consent_mutation():
              if time.monotonic() >= deadline:
                  raise AssertionError("revoke did not reach the lifespan fence")
              time.sleep(0.01)
          provider.release.set()
          revoker.join(timeout=2)
          assert not revoker.is_alive()
          assert result["response"].status_code == 200

          deadline = time.monotonic() + 2
          while True:
              jobs = test_client.get("/api/memories/jobs").json()
              if jobs and jobs[0]["status"] in {
                  "succeeded",
                  "failed",
                  "cancelled",
              }:
                  break
              if time.monotonic() >= deadline:
                  raise AssertionError("memory job did not terminate")
              time.sleep(0.01)
          audits = test_client.get("/api/memories/jobs/audits").json()

      assert provider.calls == 1
      assert jobs[0]["outcome"] == "skipped_consent_changed"
      assert audits[0]["outcome"] == "skipped_consent_changed"
      assert audits[0]["proposal_count"] == 0
      assert "SECRET_SENTINEL_SHOULD_NOT_PERSIST" not in repr(jobs)
      assert "SECRET_SENTINEL_SHOULD_NOT_PERSIST" not in repr(audits)
      get_settings.cache_clear()
  ```

  This proves the HTTP consent mutation and background remote dispatch share the same app-state fence.

- [ ] **Step 3: Run API tests and confirm RED**

  Run:

  ```powershell
  python -m pytest tests/test_api_memory_automation.py -q
  ```

  Expected: FAIL with HTTP `404` responses for `/api/memories/extraction/consent`, `/api/memories/jobs`, and `/api/memories/jobs/audits`.

- [ ] **Step 4: Add endpoint constants, response converters, and static route handlers**

  Add these imports to `memories.py`:

  ```python
  from app.api.dependencies import (
      get_memory_automation_repository,
      get_memory_extraction_dispatch_fence,
  )
  from app.core.config import Settings, get_settings
  from app.domain.models import (
      MemoryExtractionConsent,
      MemoryExtractionConsentStatus,
      MemoryJob,
      MemoryJobAudit,
  )
  from app.domain.schemas import (
      MemoryExtractionConsentResponse,
      MemoryJobAuditResponse,
      MemoryJobResponse,
      UpdateMemoryExtractionConsentRequest,
  )
  from app.repositories.memory_automation import MemoryAutomationRepository
  from app.services.memory_extraction_dispatch import (
      MEMORY_EXTRACTION_DISCLOSED_FIELDS,
      MEMORY_EXTRACTION_DISCLOSURE_VERSION,
      MEMORY_EXTRACTION_PURPOSE,
      MemoryExtractionDispatchFence,
  )
  ```

  Add these exact response helpers above route decorators:

  ```python
  def _consent_response(
      consent: MemoryExtractionConsent,
      settings: Settings,
  ) -> MemoryExtractionConsentResponse:
      deployment_configured = (
          settings.memory_extractor_route != "remote"
          or (
              settings.memory_extractor_provider == "anthropic"
              and bool(settings.anthropic_api_key)
          )
          or (
              settings.memory_extractor_provider == "deepseek"
              and bool(settings.deepseek_api_key)
          )
      )
      return MemoryExtractionConsentResponse(
          scope_id=consent.scope_id,
          status=consent.status.value,
          purpose=consent.purpose,
          provider=consent.provider,
          disclosure_version=consent.disclosure_version,
          disclosed_fields=list(consent.disclosed_fields),
          generation=consent.generation,
          deployment_route=settings.memory_extractor_route,
          deployment_provider=settings.memory_extractor_provider,
          deployment_configured=deployment_configured,
          created_at=consent.created_at,
          updated_at=consent.updated_at,
      )


  def _memory_job_response(job: MemoryJob) -> MemoryJobResponse:
      return MemoryJobResponse.model_validate(job, from_attributes=True)


  def _memory_job_audit_response(
      audit: MemoryJobAudit,
  ) -> MemoryJobAuditResponse:
      return MemoryJobAuditResponse.model_validate(audit, from_attributes=True)
  ```

  Insert these static routes before `@router.get("")` and before every `/{memory_id}` route:

  ```python
  @router.get(
      "/extraction/consent",
      response_model=MemoryExtractionConsentResponse,
  )
  def get_memory_extraction_consent(
      settings: Settings = Depends(get_settings),
      automation: MemoryAutomationRepository = Depends(
          get_memory_automation_repository
      ),
  ) -> MemoryExtractionConsentResponse:
      return _consent_response(automation.get_consent(), settings)


  @router.put(
      "/extraction/consent",
      response_model=MemoryExtractionConsentResponse,
  )
  async def update_memory_extraction_consent(
      request: UpdateMemoryExtractionConsentRequest,
      settings: Settings = Depends(get_settings),
      automation: MemoryAutomationRepository = Depends(
          get_memory_automation_repository
      ),
      fence: MemoryExtractionDispatchFence = Depends(
          get_memory_extraction_dispatch_fence
      ),
  ) -> MemoryExtractionConsentResponse:
      statuses = {
          "grant": MemoryExtractionConsentStatus.GRANTED,
          "decline": MemoryExtractionConsentStatus.DECLINED,
          "revoke": MemoryExtractionConsentStatus.REVOKED,
      }
      mutation = fence.begin_consent_mutation()
      async with mutation:
          consent = automation.set_consent(
              status=statuses[request.action],
              purpose=MEMORY_EXTRACTION_PURPOSE,
              provider=settings.memory_extractor_provider,
              disclosure_version=MEMORY_EXTRACTION_DISCLOSURE_VERSION,
              disclosed_fields=MEMORY_EXTRACTION_DISCLOSED_FIELDS,
          )
      return _consent_response(consent, settings)


  @router.get("/jobs", response_model=list[MemoryJobResponse])
  def list_memory_jobs(
      limit: int = Query(default=20, ge=1, le=100),
      automation: MemoryAutomationRepository = Depends(
          get_memory_automation_repository
      ),
  ) -> list[MemoryJobResponse]:
      return [
          _memory_job_response(job)
          for job in automation.list_jobs(limit=limit)
      ]


  @router.get("/jobs/audits", response_model=list[MemoryJobAuditResponse])
  def list_memory_job_audits(
      limit: int = Query(default=20, ge=1, le=100),
      automation: MemoryAutomationRepository = Depends(
          get_memory_automation_repository
      ),
  ) -> list[MemoryJobAuditResponse]:
      return [
          _memory_job_audit_response(audit)
          for audit in automation.list_audits(limit=limit)
      ]
  ```

  The request body cannot select provider, purpose, disclosed fields, mode, route, or job IDs. Consent mutation changes only consent metadata and generation; it never changes existing jobs or active-memory rows.

- [ ] **Step 5: Run API regressions and perform a no-commit checkpoint**

  Run:

  ```powershell
  python -m pytest tests/test_api_memory_automation.py tests/test_api_memories.py tests/test_memory_job_service.py -q
  ```

  Expected: PASS. Existing memory CRUD, candidate confirmation, archive, audit-event, and relevance behavior remains unchanged.

  Then run:

  ```powershell
  git status --short
  git diff --check
  git diff -- app/api/routes/memories.py tests/test_api_memory_automation.py
  ```

  Expected: no diff whitespace errors. Do not stage or commit.

---

### Task 7: Run focused, full, smoke, and security acceptance with evidence-only documentation

**Files:**
- Create: `<project-root>\docs\automatic-memory-gate-a-acceptance-2026-07-18.md`
- Modify only for actual defects found: files listed in Tasks 1–6.

- [ ] **Step 1: Run the focused Gate A test suite**

  Run from the repository root:

  ```powershell
  Set-Location "<project-root>"
  python -m pytest backend/tests/test_config.py backend/tests/test_memory_automation_migration.py backend/tests/test_memory_automation_repository.py backend/tests/test_memory_governor.py backend/tests/test_memory_extractor.py backend/tests/test_memory_job_service.py backend/tests/test_memory_job_scheduler.py backend/tests/test_api_memory_automation.py backend/tests/test_chat_memory_candidates.py backend/tests/test_api_chat.py backend/tests/test_provider_factory.py -q
  ```

  Expected: PASS with no failed tests and no warnings about unclosed network clients, destroyed pending tasks, or unawaited coroutines.

- [ ] **Step 2: Run the complete backend regression suite**

  Run:

  ```powershell
  python -m pytest backend/tests -q
  ```

  Expected: PASS. If an external-provider test is skipped because no configured credential is present, record it as `SKIPPED` in the acceptance document; do not present a fake-provider test as real-provider evidence.

- [ ] **Step 3: Confirm the existing full-table non-mutation matrix**

  `test_memory_job_service.py` already defines `_memory_snapshot()` using a second observation connection, seeds active/pending/dismissed/archived rows, and compares exact rows across success, preflight/postflight rejection, invalid output, provider failure, cancellation, and consent races. Do not duplicate those unit tests. Task 5's HTTP mode matrix adds the required composition-level four-status proof before lifespan implementation.

  Run:

  ```powershell
  python -m pytest backend/tests/test_chat_memory_candidates.py backend/tests/test_memory_job_service.py -q
  ```

  Expected: PASS. The scheduler and job service dependency graph contains no `MemoryRepository` parameter or import.

- [ ] **Step 4: Run the local HTTP smoke sequence without remote consent**

  Start the server in one PowerShell terminal:

  ```powershell
  Set-Location "<project-root>"
  $env:DATABASE_URL="sqlite:///./gate-a-smoke.db"
  $env:LLM_PROVIDER="fake"
  $env:MEMORY_AUTOMATION_MODE="shadow_auto"
  $env:MEMORY_EXTRACTOR_ROUTE="remote"
  $env:MEMORY_EXTRACTOR_PROVIDER="anthropic"
  Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
  python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
  ```

  In a second terminal, create a session, send a fake chat turn, then query consent/jobs/audits:

  ```powershell
  $session = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/sessions" -ContentType "application/json" -Body '{"title":"Gate A smoke"}'
  $chat = Invoke-RestMethod -Method Post -Uri ("http://127.0.0.1:8000/api/sessions/" + $session.id + "/messages") -ContentType "application/json" -Body '{"content":"我喜欢黑咖啡"}'
  Use a bounded polling loop instead of a fixed sleep:

  ```powershell
  $deadline = (Get-Date).AddSeconds(10)
  do {
      $jobs = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/memories/jobs"
      $job = $jobs | Where-Object { $_.assistant_message_id -eq $chat.assistant_message_id } | Select-Object -First 1
      if ($null -ne $job -and $job.status -in @("succeeded", "failed", "cancelled")) { break }
      Start-Sleep -Milliseconds 100
  } while ((Get-Date) -lt $deadline)
  if ($null -eq $job -or $job.status -notin @("succeeded", "failed", "cancelled")) {
      throw "Gate A smoke job did not reach a terminal state"
  }
  $audits = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/memories/jobs/audits"
  $job | ConvertTo-Json -Depth 6
  $audits | ConvertTo-Json -Depth 6
  ```
  ```

  Expected observations:

  ```text
  Chat response succeeds.
  Exactly one job has assistant_message_id equal to chat.assistant_message_id.
  The terminal job status is succeeded.
  With missing credentials, the terminal outcome is skipped_no_extractor.
  No remote Provider object is constructed and no network call occurs.
  The API output has no conversation body, proposal body, prompt, response, or credential field.
  ```

  Next, restart with a test-only configured key but do not grant consent. Use a recording Provider factory in an automated integration test rather than a real cloud client, and assert `SUCCEEDED/skipped_no_consent` plus zero `generate()` calls. This separately verifies the no-credentials and no-consent truth-table branches.

  Stop the Uvicorn process. Inspect and record the smoke database before deletion, then remove only `gate-a-smoke.db` and any SQLite `-wal`/`-shm` siblings created by this smoke step after confirming their paths. Restart with a fresh smoke database and:

  ```powershell
  $env:MEMORY_EXTRACTOR_ROUTE="local"
  ```

  Expected: a terminal `shadow_recorded` or `skipped_governor_policy` job is allowed, but the active `memories` table remains unchanged. Do not grant remote consent and do not make a real cloud provider call during this smoke check.

  Finally run rollback tests with two additional isolated databases:

  - `candidate_confirmation`: one successful turn creates a pending candidate and zero shadow jobs.
  - `off`: one successful turn creates neither pending candidates nor shadow jobs.

  Keep the additive automation tables intact and prove any previously created Gate A job remains readable directly from SQLite after restarting with a fallback mode. Do not drop tables as part of rollback.

- [ ] **Step 5: Run security and scope scans**

  Run:

  ```powershell
  Set-Location "<project-root>"
  git diff --check
  git diff --name-only
  ```

  Run these read-only source scans:

  ```powershell
  Select-String -Path "backend/app/services/memory_job_service.py" -Pattern "MemoryRepository"
  Select-String -Path "backend/app/services/memory_governor.py","backend/app/services/memory_extractor.py","backend/app/services/memory_job_scheduler.py","backend/app/api/routes/memories.py" -Pattern "anthropic|httpx|Authorization|api_key|prompt|raw response"
  Select-String -Path "backend/app/services/chat_service.py" -Pattern "auto_active"
  ```

  Expected:

  ```text
  MemoryJobService has no MemoryRepository reference.
  Memory service and memory API layers have no provider-SDK or HTTPX import.
  No job/audit API response exposes raw text or credentials.
  ChatService has no auto_active branch.
  git diff --check exits 0.
  ```

  Verify the changed file list does not include frontend, Electron, voice, Live2D, user asset, summary injection, Persona, relationship, Evidence, tombstone, or Gate B/C implementation files.

- [ ] **Step 6: Create the evidence-only acceptance record and perform the final no-commit checkpoint**

  Do not create this document from a placeholder template. Construct it from command output only, with these required headings and concrete content rules:

  ```markdown
  # Gate A Closure Acceptance Record

  **Date:** 2026-07-18
  **Status:** PASS, FAIL, or PARTIAL selected from observed gates
  **Scope:** Gate A closure only

  ## Focused tests
  Record the exact command, exit code, passed/failed/skipped counts, and warnings.

  ## Full backend regression
  Record the exact command, exit code, passed/failed/skipped counts, and external-provider skips.

  ## HTTP smoke
  Record database path, configuration, assistant message ID, job ID/status/outcome, audit ID/outcome, bounded polling result, API forbidden-field scan, and before/after memories-table comparison.

  ## Local extraction smoke
  Record configuration, job/audit outcome, and before/after memories-table comparison.

  ## Privacy and dependency checks
  Record each search command and whether it matched; include the reviewed changed-file list and `git diff --check` exit code.

  ## Limits and unverified scope
  State whether real Anthropic/DeepSeek extraction ran. Explicitly state Gate B/C, frontend status UI, Electron, Live2D, private image import, and voice cloning remain unimplemented.
  ```

  If any required result is unavailable, write `NOT RUN` with the reason and set status to `PARTIAL` or `FAIL`; never leave a marker for later replacement.

  ```powershell
  git status --short
  git diff --check
  git diff -- backend/app backend/tests docs/automatic-memory-gate-a-acceptance-2026-07-18.md
  ```

  Expected: `git diff --check` exits `0`; only Gate A source, test, and acceptance evidence changes are present; no files are staged; no commit is created.

---

## Gate A completion criteria

Gate A is complete only when actual evidence establishes all of these conditions:

1. Canonical-hash deduplication occurs only in `MemoryGovernor`, is limited to one extractor response, retains first-seen order, and removes all extractor-side pre-deduplication.
2. One `(assistant_message.id, memory-shadow-schema-v1)` job exists per completed shadow turn, and duplicate schedules do not create concurrent duplicate executions.
3. Startup atomically changes `running` jobs to `pending` and re-enqueues pending IDs in `created_at, id` order without creating new jobs or rerunning terminal jobs.
4. Scheduler shutdown stops new work, waits by default, and cancellation produces exactly one `CANCELLED/cancelled` terminal record per unfinished job.
5. `ChatService` executes exactly one of the `off`, `candidate_confirmation`, and `shadow_auto` paths after assistant persistence.
6. Scheduler/extractor failures do not invalidate the persisted assistant reply.
7. `none`, `local`, and `fake` routes do not create remote extractor clients; remote missing credentials produces `SUCCEEDED/skipped_no_extractor`.
8. Remote extraction requires a current exact persisted grant and respects the pre-send/after-response generation fence.
9. The chat provider and remote extractor provider are lifespan-owned, shared where applicable, and each closes exactly once after dependent schedulers stop.
10. Consent/job/audit APIs use strict inputs, bounded stable lists, and metadata-only outputs.
11. Before/after memory-table snapshots are byte-identical for every shadow-job outcome.
12. Focused tests, full backend tests, local HTTP smoke, privacy/dependency scans, and `git diff --check` all have recorded real results.
13. No code is staged or committed unless the user later explicitly requests a commit.

### Critical Files for Implementation
- `<project-root>\backend\app\services\memory_governor.py`
- `<project-root>\backend\app\services\memory_job_scheduler.py`
- `<project-root>\backend\app\services\chat_service.py`
- `<project-root>\backend\app\main.py`
- `<project-root>\backend\app\api\routes\memories.py`