from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
import inspect
import logging
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from app.domain.models import (
    ChatRole,
    MemoryAutomationMode,
    MemoryExtractionConsentStatus,
    MemoryExtractorRoute,
    MemoryGovernorProposal,
    MemoryJobAuditOutcome,
    MemoryJobStatus,
    MemoryType,
)
from app.repositories.memory_automation import MemoryAutomationRepository
from app.repositories.messages import MessageRepository
from app.repositories.sqlite import managed_connection
from app.services.memory_extraction_dispatch import (
    MEMORY_EXTRACTION_DISCLOSED_FIELDS,
    MEMORY_EXTRACTION_DISCLOSURE_VERSION,
    MEMORY_EXTRACTION_PURPOSE,
    MemoryExtractionDispatchFence,
)
from app.services.memory_extractor import (
    MEMORY_EXTRACTION_SCHEMA_VERSION,
    MemoryExtractionInvalidOutputError,
    MemoryExtractionResult,
)
from app.services.memory_governor import MEMORY_GOVERNOR_VERSION, MemoryGovernor
from app.services.memory_job_service import MemoryJobService


_NOW = "2026-07-16T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _forbid_memory_repository_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.repositories.memories as memories_module

    def forbidden_memory_repository(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("MemoryRepository must not be constructed by MemoryJobService")

    monkeypatch.setattr(
        memories_module,
        "MemoryRepository",
        forbidden_memory_repository,
    )


class RecordingExtractor:
    def __init__(
        self,
        *,
        proposals: list[MemoryGovernorProposal] | None = None,
        error: Exception | None = None,
        provider: str = "fixture-provider",
        model: str = "fixture-model",
        automation: MemoryAutomationRepository | None = None,
        connection: sqlite3.Connection | None = None,
        block: bool = False,
    ) -> None:
        self.proposals = proposals or []
        self.error = error
        self.provider = provider
        self.model = model
        self.automation = automation
        self.connection = connection
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        if not block:
            self.release.set()

    async def extract(self, *, user_message: Any, assistant_message: Any) -> MemoryExtractionResult:
        self.calls += 1
        if self.automation is not None:
            assert self.automation._transaction_depth == 0
        if self.connection is not None:
            assert self.connection.in_transaction is False
        self.started.set()
        await self.release.wait()
        if self.error is not None:
            raise self.error
        return MemoryExtractionResult(
            proposals=self.proposals,
            provider=self.provider,
            model=self.model,
            elapsed_ms=999_999,
        )


class AutomationSpy:
    def __init__(self, repository: MemoryAutomationRepository) -> None:
        self.repository = repository
        self.consent_reads = 0
        self.first_consent_read = asyncio.Event()

    def get_consent(self, *args: Any, **kwargs: Any) -> Any:
        self.consent_reads += 1
        self.first_consent_read.set()
        return self.repository.get_consent(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.repository, name)


class RecordingGovernor:
    def __init__(self, governor: MemoryGovernor) -> None:
        self.governor = governor
        self.preflight_calls = 0
        self.evaluate_many_calls = 0

    def preflight_turn(self, **kwargs: Any) -> Any:
        self.preflight_calls += 1
        return self.governor.preflight_turn(**kwargs)

    def evaluate_many(self, **kwargs: Any) -> Any:
        self.evaluate_many_calls += 1
        return self.governor.evaluate_many(**kwargs)


def _governor() -> MemoryGovernor:
    return MemoryGovernor(
        max_proposals=5,
        max_proposal_characters=500,
        max_total_characters=1_000,
    )


def _proposal(
    *,
    user_id: str,
    assistant_id: str | None = None,
    content: str = "TRANSIENT_PROPOSAL_SENTINEL",
    source_ids: tuple[str, ...] | None = None,
) -> MemoryGovernorProposal:
    return MemoryGovernorProposal(
        memory_type=MemoryType.PREFERENCE,
        subject="饮品偏好",
        content=content,
        canonical_key_hint="TRANSIENT_CANONICAL_KEY_SENTINEL",
        confidence=0.91,
        source_message_ids=source_ids or (
            (user_id, assistant_id) if assistant_id is not None else (user_id,)
        ),
    )


def _seed_database(database_url: str, *, user_text: str = "我喜欢乌龙茶。") -> dict[str, str]:
    ids = {
        "session_id": "session-1",
        "other_session_id": "session-2",
        "user_message_id": "user-1",
        "assistant_message_id": "assistant-1",
    }
    with managed_connection(database_url) as connection:
        connection.executemany(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (
                (ids["session_id"], "one", _NOW, _NOW),
                (ids["other_session_id"], "two", _NOW, _NOW),
            ),
        )
        connection.executemany(
            """
            INSERT INTO messages (id, session_id, role, content, metadata_json, created_at)
            VALUES (?, ?, ?, ?, '{}', ?)
            """,
            (
                (
                    ids["user_message_id"],
                    ids["session_id"],
                    "user",
                    user_text,
                    "2026-07-16T00:00:01+00:00",
                ),
                (
                    ids["assistant_message_id"],
                    ids["session_id"],
                    "assistant",
                    "好的。",
                    "2026-07-16T00:00:02+00:00",
                ),
            ),
        )
        for index, status in enumerate(("active", "pending", "dismissed", "archived")):
            connection.execute(
                """
                INSERT INTO memories (
                    id, content, memory_type, source, source_session_id,
                    importance, confidence, status, metadata_json, created_at, updated_at
                ) VALUES (?, ?, 'other', 'manual', ?, 3, 0.8, ?, ?, ?, ?)
                """,
                (
                    f"memory-{status}",
                    f"legacy {status}",
                    ids["session_id"],
                    status,
                    f'{{"fixture":{index}}}',
                    _NOW,
                    _NOW,
                ),
            )
        connection.commit()
    return ids


def _memory_snapshot(database_url: str) -> list[tuple[object, ...]]:
    with managed_connection(database_url) as observation:
        rows = observation.execute(
            """
            SELECT id, content, source, status, metadata_json, updated_at
            FROM memories
            ORDER BY id
            """
        ).fetchall()
        return [tuple(row) for row in rows]


def _database_text(database_url: str) -> str:
    with managed_connection(database_url) as observation:
        names = [
            row[0]
            for row in observation.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
            if not str(row[0]).startswith("sqlite_")
        ]
        return "\n".join(
            str(value)
            for table in names
            for row in observation.execute(f"SELECT * FROM {table}").fetchall()
            for value in row
        )


def _reserve(
    automation: MemoryAutomationRepository,
    ids: dict[str, str],
    *,
    route: MemoryExtractorRoute,
    turn_id: str | None = None,
    session_id: str | None = None,
) -> Any:
    return automation.reserve_job(
        turn_id=turn_id or ids["assistant_message_id"],
        schema_version=MEMORY_EXTRACTION_SCHEMA_VERSION,
        session_id=session_id or ids["session_id"],
        user_message_id=ids["user_message_id"],
        assistant_message_id=ids["assistant_message_id"],
        mode=MemoryAutomationMode.SHADOW_AUTO,
        extractor_route=route,
        governor_version=MEMORY_GOVERNOR_VERSION,
    )[0]


def _grant(
    automation: MemoryAutomationRepository,
    *,
    status: MemoryExtractionConsentStatus = MemoryExtractionConsentStatus.GRANTED,
    purpose: str = MEMORY_EXTRACTION_PURPOSE,
    provider: str = "anthropic",
    disclosure_version: str = MEMORY_EXTRACTION_DISCLOSURE_VERSION,
    fields: tuple[str, ...] = MEMORY_EXTRACTION_DISCLOSED_FIELDS,
) -> Any:
    return automation.set_consent(
        status=status,
        purpose=purpose,
        provider=provider,
        disclosure_version=disclosure_version,
        disclosed_fields=fields,
    )


def _service(
    *,
    automation: Any,
    messages: MessageRepository,
    extractor: Any,
    governor: Any,
    route: MemoryExtractorRoute,
    fence: MemoryExtractionDispatchFence | None = None,
) -> MemoryJobService:
    return MemoryJobService(
        automation=automation,
        messages=messages,
        extractor=extractor,
        governor=governor,
        route=route,
        provider_name="anthropic",
        dispatch_fence=fence or MemoryExtractionDispatchFence(),
    )


@contextmanager
def _environment(
    tmp_path: Path,
    *,
    route: MemoryExtractorRoute,
    user_text: str = "我喜欢乌龙茶。",
    extractor_factory: Any = RecordingExtractor,
) -> Iterator[tuple[str, dict[str, str], sqlite3.Connection, MemoryAutomationRepository, MessageRepository, Any, Any]]:
    database_url = f"sqlite:///{tmp_path / (route.value + '.db')}"
    ids = _seed_database(database_url, user_text=user_text)
    with managed_connection(database_url) as connection:
        automation = MemoryAutomationRepository(connection)
        messages = MessageRepository(connection)
        governor = RecordingGovernor(_governor())
        extractor = extractor_factory(automation=automation, connection=connection)
        yield database_url, ids, connection, automation, messages, governor, extractor


def _audit(automation: MemoryAutomationRepository, job_id: str) -> Any:
    return next(item for item in automation.list_audits(limit=100) if item.job_id == job_id)


def test_service_has_no_memory_repository_dependency() -> None:
    import app.services.memory_job_service as service_module

    parameters = inspect.signature(MemoryJobService.__init__).parameters
    assert "memories" not in parameters
    assert "MemoryRepository" not in inspect.getsource(service_module)
    assert MEMORY_EXTRACTION_PURPOSE == "extract durable memory proposals from the current completed turn"
    assert MEMORY_EXTRACTION_DISCLOSURE_VERSION == "memory-extraction-disclosure-v1"
    assert MEMORY_EXTRACTION_DISCLOSED_FIELDS == ("user_message", "assistant_message")


@pytest.mark.asyncio
@pytest.mark.parametrize("route", (MemoryExtractorRoute.NONE, MemoryExtractorRoute.REMOTE))
async def test_none_or_missing_extractor_succeeds_as_skipped_no_extractor(
    tmp_path: Path,
    route: MemoryExtractorRoute,
) -> None:
    database_url = f"sqlite:///{tmp_path / (route.value + '-none.db')}"
    ids = _seed_database(database_url)
    before = _memory_snapshot(database_url)
    with managed_connection(database_url) as connection:
        automation = MemoryAutomationRepository(connection)
        spy = AutomationSpy(automation)
        job = _reserve(automation, ids, route=route)
        result = await _service(
            automation=spy,
            messages=MessageRepository(connection),
            extractor=None,
            governor=RecordingGovernor(_governor()),
            route=route,
        ).process(job.id)
        audit = _audit(automation, job.id)

    assert result.status is MemoryJobStatus.SUCCEEDED
    assert result.outcome is MemoryJobAuditOutcome.SKIPPED_NO_EXTRACTOR
    assert result.attempt_count == 1
    assert audit.provider is None and audit.model is None
    assert audit.proposal_count == 0
    assert spy.consent_reads == 0
    assert _memory_snapshot(database_url) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("route", (MemoryExtractorRoute.LOCAL, MemoryExtractorRoute.FAKE))
async def test_local_and_fake_ignore_remote_consent_and_record_metadata_only_shadow(
    tmp_path: Path,
    route: MemoryExtractorRoute,
) -> None:
    with _environment(tmp_path, route=route) as env:
        database_url, ids, _, automation, messages, governor, extractor = env
        spy = AutomationSpy(automation)
        extractor.proposals = [_proposal(user_id=ids["user_message_id"])]
        before = _memory_snapshot(database_url)
        job = _reserve(automation, ids, route=route)

        result = await _service(
            automation=spy,
            messages=messages,
            extractor=extractor,
            governor=governor,
            route=route,
        ).process(job.id)
        audit = _audit(automation, job.id)

    assert result.status is MemoryJobStatus.SUCCEEDED
    assert result.outcome is MemoryJobAuditOutcome.SHADOW_RECORDED
    assert result.attempt_count == 1
    assert extractor.calls == 1
    assert spy.consent_reads == 0
    assert audit.decision_counts == {"create": 1}
    assert audit.reason_counts == {"eligible_shadow_create": 1}
    assert audit.proposal_count == audit.accepted_count == 1
    assert audit.rejected_count == 0
    assert audit.provider == "fixture-provider"
    assert audit.model == "fixture-model"
    assert "TRANSIENT_PROPOSAL_SENTINEL" not in _database_text(database_url)
    assert "TRANSIENT_CANONICAL_KEY_SENTINEL" not in _database_text(database_url)
    assert _memory_snapshot(database_url) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "consent",
    (
        None,
        {"status": MemoryExtractionConsentStatus.DECLINED},
        {"status": MemoryExtractionConsentStatus.REVOKED},
        {"purpose": "wrong purpose"},
        {"provider": "wrong-provider"},
        {"disclosure_version": "wrong-version"},
        {"fields": ("user_message",)},
        {"fields": ("assistant_message", "user_message")},
    ),
)
async def test_remote_requires_exact_persisted_consent_without_sending(
    tmp_path: Path,
    consent: dict[str, object] | None,
) -> None:
    with _environment(tmp_path, route=MemoryExtractorRoute.REMOTE) as env:
        database_url, ids, _, automation, messages, governor, extractor = env
        if consent is None:
            initial = automation.get_consent()
            assert initial.purpose is None
            assert initial.provider is None
            assert initial.disclosure_version is None
            assert initial.disclosed_fields == ()
        else:
            _grant(automation, **consent)
        before = _memory_snapshot(database_url)
        job = _reserve(automation, ids, route=MemoryExtractorRoute.REMOTE)
        result = await _service(
            automation=automation,
            messages=messages,
            extractor=extractor,
            governor=governor,
            route=MemoryExtractorRoute.REMOTE,
        ).process(job.id)
        audit = _audit(automation, job.id)

    assert result.status is MemoryJobStatus.SUCCEEDED
    assert result.outcome is MemoryJobAuditOutcome.SKIPPED_NO_CONSENT
    assert extractor.calls == 0
    assert audit.proposal_count == 0
    assert audit.provider is None and audit.model is None
    assert _memory_snapshot(database_url) == before


@pytest.mark.asyncio
async def test_remote_matching_grant_calls_once_and_records_only_aggregate_metadata(
    tmp_path: Path,
) -> None:
    with _environment(tmp_path, route=MemoryExtractorRoute.REMOTE) as env:
        database_url, ids, _, automation, messages, governor, extractor = env
        grant = _grant(automation)
        extractor.proposals = [
            _proposal(user_id=ids["user_message_id"], content="REMOTE_TRANSIENT_SENTINEL")
        ]
        before = _memory_snapshot(database_url)
        job = _reserve(automation, ids, route=MemoryExtractorRoute.REMOTE)
        result = await _service(
            automation=automation,
            messages=messages,
            extractor=extractor,
            governor=governor,
            route=MemoryExtractorRoute.REMOTE,
        ).process(job.id)
        audit = _audit(automation, job.id)

    assert result.outcome is MemoryJobAuditOutcome.SHADOW_RECORDED
    assert extractor.calls == 1
    assert audit.consent_generation == grant.generation
    assert audit.decision_counts == {"create": 1}
    assert audit.reason_counts == {"eligible_shadow_create": 1}
    assert audit.provider == "fixture-provider"
    assert audit.model == "fixture-model"
    assert "REMOTE_TRANSIENT_SENTINEL" not in _database_text(database_url)
    assert _memory_snapshot(database_url) == before


@pytest.mark.asyncio
async def test_invalid_output_is_sanitized_failed_and_does_not_change_memories(
    tmp_path: Path,
) -> None:
    def factory(**kwargs: Any) -> RecordingExtractor:
        return RecordingExtractor(
            error=MemoryExtractionInvalidOutputError("RAW_INVALID_JSON_SENTINEL"),
            **kwargs,
        )

    with _environment(
        tmp_path,
        route=MemoryExtractorRoute.LOCAL,
        extractor_factory=factory,
    ) as env:
        database_url, ids, _, automation, messages, governor, extractor = env
        before = _memory_snapshot(database_url)
        job = _reserve(automation, ids, route=MemoryExtractorRoute.LOCAL)
        result = await _service(
            automation=automation,
            messages=messages,
            extractor=extractor,
            governor=governor,
            route=MemoryExtractorRoute.LOCAL,
        ).process(job.id)
        audit = _audit(automation, job.id)

    assert result.status is MemoryJobStatus.FAILED
    assert result.outcome is MemoryJobAuditOutcome.INVALID_OUTPUT
    assert result.error_category == "invalid_output"
    assert audit.outcome is MemoryJobAuditOutcome.INVALID_OUTPUT
    assert "RAW_INVALID_JSON_SENTINEL" not in _database_text(database_url)
    assert _memory_snapshot(database_url) == before


@pytest.mark.asyncio
async def test_provider_exception_never_persists_or_logs_raw_secret(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-provider-secret-SENTINEL_81d4"

    def factory(**kwargs: Any) -> RecordingExtractor:
        return RecordingExtractor(error=RuntimeError(f"provider exploded {secret}"), **kwargs)

    caplog.set_level(logging.DEBUG)
    with _environment(
        tmp_path,
        route=MemoryExtractorRoute.LOCAL,
        extractor_factory=factory,
    ) as env:
        database_url, ids, _, automation, messages, governor, extractor = env
        before = _memory_snapshot(database_url)
        job = _reserve(automation, ids, route=MemoryExtractorRoute.LOCAL)
        result = await _service(
            automation=automation,
            messages=messages,
            extractor=extractor,
            governor=governor,
            route=MemoryExtractorRoute.LOCAL,
        ).process(job.id)
        audit = _audit(automation, job.id)

    assert result.status is MemoryJobStatus.FAILED
    assert result.outcome is MemoryJobAuditOutcome.PROVIDER_ERROR
    assert result.error_category == "provider_error"
    assert audit.outcome is MemoryJobAuditOutcome.PROVIDER_ERROR
    assert secret not in _database_text(database_url)
    assert secret not in caplog.text
    assert _memory_snapshot(database_url) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route",
    (MemoryExtractorRoute.LOCAL, MemoryExtractorRoute.FAKE, MemoryExtractorRoute.REMOTE),
)
async def test_governor_preflight_precedes_consent_fence_and_all_extractors(
    tmp_path: Path,
    route: MemoryExtractorRoute,
) -> None:
    with _environment(
        tmp_path,
        route=route,
        user_text="不要记住。api_key=ABCDEFGHIJKL",
    ) as env:
        database_url, ids, _, automation, messages, governor, extractor = env
        if route is MemoryExtractorRoute.REMOTE:
            _grant(automation)
        spy = AutomationSpy(automation)
        before = _memory_snapshot(database_url)
        job = _reserve(automation, ids, route=route)
        result = await _service(
            automation=spy,
            messages=messages,
            extractor=extractor,
            governor=governor,
            route=route,
        ).process(job.id)
        audit = _audit(automation, job.id)

    assert result.outcome is MemoryJobAuditOutcome.SKIPPED_GOVERNOR_POLICY
    assert result.status is MemoryJobStatus.SUCCEEDED
    assert extractor.calls == 0
    assert spy.consent_reads == 0
    assert governor.evaluate_many_calls == 0
    assert audit.decision_counts == {}
    assert audit.reason_counts == {}
    assert audit.proposal_count == 0
    assert audit.redaction_count in (0, 1)
    assert audit.provider is None and audit.model is None
    assert _memory_snapshot(database_url) == before


@pytest.mark.asyncio
async def test_post_extraction_rejections_are_aggregate_shadow_metadata_only(
    tmp_path: Path,
) -> None:
    with _environment(tmp_path, route=MemoryExtractorRoute.LOCAL) as env:
        database_url, ids, _, automation, messages, governor, extractor = env
        extractor.proposals = [
            _proposal(
                user_id=ids["user_message_id"],
                source_ids=(ids["assistant_message_id"],),
                content="POST_REJECT_TRANSIENT_SENTINEL",
            )
        ]
        before = _memory_snapshot(database_url)
        job = _reserve(automation, ids, route=MemoryExtractorRoute.LOCAL)
        result = await _service(
            automation=automation,
            messages=messages,
            extractor=extractor,
            governor=governor,
            route=MemoryExtractorRoute.LOCAL,
        ).process(job.id)
        audit = _audit(automation, job.id)

    assert result.outcome is MemoryJobAuditOutcome.SHADOW_RECORDED
    assert audit.decision_counts == {"reject": 1}
    assert audit.reason_counts == {"invalid_source": 1}
    assert audit.proposal_count == audit.rejected_count == 1
    assert audit.accepted_count == 0
    assert "POST_REJECT_TRANSIENT_SENTINEL" not in _database_text(database_url)
    assert _memory_snapshot(database_url) == before


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


@pytest.mark.asyncio
async def test_terminal_job_is_returned_without_second_extraction_or_audit(
    tmp_path: Path,
) -> None:
    with _environment(tmp_path, route=MemoryExtractorRoute.LOCAL) as env:
        _, ids, _, automation, messages, governor, extractor = env
        job = _reserve(automation, ids, route=MemoryExtractorRoute.LOCAL)
        service = _service(
            automation=automation,
            messages=messages,
            extractor=extractor,
            governor=governor,
            route=MemoryExtractorRoute.LOCAL,
        )
        first = await service.process(job.id)
        second = await service.process(job.id)
        audit_count = len(
            [audit for audit in automation.list_audits(limit=100) if audit.job_id == job.id]
        )

    assert first == second
    assert second.attempt_count == 1
    assert extractor.calls == 1
    assert audit_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ("wrong_session", "wrong_role", "wrong_turn_id", "missing"))
async def test_invalid_persisted_job_input_fails_from_pending_without_raw_text(
    tmp_path: Path,
    corruption: str,
) -> None:
    database_url = f"sqlite:///{tmp_path / ('invalid-' + corruption + '.db')}"
    ids = _seed_database(database_url, user_text="RAW_USER_TEXT_SENTINEL")
    before = _memory_snapshot(database_url)
    with managed_connection(database_url) as connection:
        automation = MemoryAutomationRepository(connection)
        job = _reserve(
            automation,
            ids,
            route=MemoryExtractorRoute.LOCAL,
            turn_id="wrong-turn" if corruption == "wrong_turn_id" else None,
        )
        if corruption == "wrong_session":
            connection.execute(
                "UPDATE messages SET session_id = ? WHERE id = ?",
                (ids["other_session_id"], ids["user_message_id"]),
            )
            connection.commit()
        elif corruption == "wrong_role":
            connection.execute(
                "UPDATE messages SET role = 'assistant' WHERE id = ?",
                (ids["user_message_id"],),
            )
            connection.commit()
        elif corruption == "missing":
            connection.execute(
                "DELETE FROM messages WHERE id = ?",
                (ids["user_message_id"],),
            )
            connection.commit()

        extractor = RecordingExtractor(automation=automation, connection=connection)
        result = await _service(
            automation=automation,
            messages=MessageRepository(connection),
            extractor=extractor,
            governor=RecordingGovernor(_governor()),
            route=MemoryExtractorRoute.LOCAL,
        ).process(job.id)
        audit = _audit(automation, job.id)
        persisted_job_data = "\n".join(
            str(value)
            for table in ("memory_jobs", "memory_job_audits")
            for row in connection.execute(f"SELECT * FROM {table}").fetchall()
            for value in row
        )

    assert result.status is MemoryJobStatus.FAILED
    assert result.outcome is MemoryJobAuditOutcome.FAILED
    assert result.error_category == "invalid_job_input"
    assert result.attempt_count == 0
    assert result.started_at is None
    assert audit.provider is None and audit.model is None
    assert extractor.calls == 0
    assert "RAW_USER_TEXT_SENTINEL" not in persisted_job_data
    assert _memory_snapshot(database_url) == before


@pytest.mark.asyncio
async def test_priority_fence_lets_queued_revoke_beat_unsent_remote_work(
    tmp_path: Path,
) -> None:
    with _environment(tmp_path, route=MemoryExtractorRoute.REMOTE) as env:
        database_url, ids, _, automation, messages, governor, extractor = env
        grant = _grant(automation)
        spy = AutomationSpy(automation)
        fence = MemoryExtractionDispatchFence()
        before = _memory_snapshot(database_url)
        job = _reserve(automation, ids, route=MemoryExtractorRoute.REMOTE)
        service = _service(
            automation=spy,
            messages=messages,
            extractor=extractor,
            governor=governor,
            route=MemoryExtractorRoute.REMOTE,
            fence=fence,
        )

        async with fence.hold() as held:
            assert held is True
            task = asyncio.create_task(service.process(job.id))
            await spy.first_consent_read.wait()
            mutation = fence.begin_consent_mutation()

        async with mutation:
            revoked = _grant(
                automation,
                status=MemoryExtractionConsentStatus.REVOKED,
            )
        result = await task
        audit = _audit(automation, job.id)

    assert grant.generation + 1 == revoked.generation
    assert revoked.status is MemoryExtractionConsentStatus.REVOKED
    assert extractor.calls == 0
    assert result.outcome is MemoryJobAuditOutcome.SKIPPED_CONSENT_CHANGED
    assert audit.proposal_count == 0
    assert _memory_snapshot(database_url) == before


@pytest.mark.asyncio
async def test_pending_revoke_discards_in_flight_response_before_governor_evaluation(
    tmp_path: Path,
) -> None:
    def factory(**kwargs: Any) -> RecordingExtractor:
        return RecordingExtractor(block=True, **kwargs)

    with _environment(
        tmp_path,
        route=MemoryExtractorRoute.REMOTE,
        extractor_factory=factory,
    ) as env:
        database_url, ids, _, automation, messages, governor, extractor = env
        grant = _grant(automation)
        extractor.proposals = [
            _proposal(user_id=ids["user_message_id"], content="IN_FLIGHT_SECRET_SENTINEL")
        ]
        fence = MemoryExtractionDispatchFence()
        before = _memory_snapshot(database_url)
        job = _reserve(automation, ids, route=MemoryExtractorRoute.REMOTE)
        service = _service(
            automation=automation,
            messages=messages,
            extractor=extractor,
            governor=governor,
            route=MemoryExtractorRoute.REMOTE,
            fence=fence,
        )

        task = asyncio.create_task(service.process(job.id))
        await extractor.started.wait()
        mutation = fence.begin_consent_mutation()
        revoke_task = asyncio.create_task(mutation.__aenter__())
        assert fence.has_pending_consent_mutation() is True
        extractor.release.set()
        result = await task
        await revoke_task
        try:
            revoked = _grant(
                automation,
                status=MemoryExtractionConsentStatus.REVOKED,
            )
        finally:
            await mutation.__aexit__(None, None, None)
        audit = _audit(automation, job.id)

    assert extractor.calls == 1
    assert governor.evaluate_many_calls == 0
    assert result.status is MemoryJobStatus.SUCCEEDED
    assert result.outcome is MemoryJobAuditOutcome.SKIPPED_CONSENT_CHANGED
    assert audit.proposal_count == 0
    assert audit.decision_counts == audit.reason_counts == {}
    assert audit.provider is None and audit.model is None
    assert grant.generation + 1 == revoked.generation
    assert revoked.status is MemoryExtractionConsentStatus.REVOKED
    assert "IN_FLIGHT_SECRET_SENTINEL" not in _database_text(database_url)
    assert _memory_snapshot(database_url) == before


@pytest.mark.asyncio
async def test_changed_generation_or_authority_discards_response_even_without_pending_marker(
    tmp_path: Path,
) -> None:
    def factory(**kwargs: Any) -> RecordingExtractor:
        return RecordingExtractor(block=True, **kwargs)

    with _environment(
        tmp_path,
        route=MemoryExtractorRoute.REMOTE,
        extractor_factory=factory,
    ) as env:
        database_url, ids, _, automation, messages, governor, extractor = env
        grant = _grant(automation)
        before = _memory_snapshot(database_url)
        job = _reserve(automation, ids, route=MemoryExtractorRoute.REMOTE)
        task = asyncio.create_task(
            _service(
                automation=automation,
                messages=messages,
                extractor=extractor,
                governor=governor,
                route=MemoryExtractorRoute.REMOTE,
            ).process(job.id)
        )
        await extractor.started.wait()
        with managed_connection(database_url) as other_connection:
            changed = _grant(
                MemoryAutomationRepository(other_connection),
                purpose="changed authority",
            )
        extractor.release.set()
        result = await task
        audit = _audit(automation, job.id)

    assert changed.generation == grant.generation + 1
    assert result.outcome is MemoryJobAuditOutcome.SKIPPED_CONSENT_CHANGED
    assert governor.evaluate_many_calls == 0
    assert audit.proposal_count == 0
    assert _memory_snapshot(database_url) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("route", (MemoryExtractorRoute.LOCAL, MemoryExtractorRoute.REMOTE))
async def test_cancellation_terminalizes_once_and_reraises_without_changing_memories(
    tmp_path: Path,
    route: MemoryExtractorRoute,
) -> None:
    def factory(**kwargs: Any) -> RecordingExtractor:
        return RecordingExtractor(block=True, **kwargs)

    with _environment(
        tmp_path,
        route=route,
        extractor_factory=factory,
    ) as env:
        database_url, ids, _, automation, messages, governor, extractor = env
        if route is MemoryExtractorRoute.REMOTE:
            _grant(automation)
        before = _memory_snapshot(database_url)
        job = _reserve(automation, ids, route=route)
        service = _service(
            automation=automation,
            messages=messages,
            extractor=extractor,
            governor=governor,
            route=route,
        )
        task = asyncio.create_task(service.process(job.id))
        await extractor.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        persisted = automation.require_job(job.id)
        audits = [
            audit
            for audit in automation.list_audits(limit=100)
            if audit.job_id == job.id
        ]
        repeated = await service.process(job.id)

    assert persisted.status is MemoryJobStatus.CANCELLED
    assert persisted.outcome is MemoryJobAuditOutcome.CANCELLED
    assert persisted.error_category == "interrupted"
    assert persisted.attempt_count == 1
    assert repeated == persisted
    assert extractor.calls == 1
    assert len(audits) == 1
    assert audits[0].outcome is MemoryJobAuditOutcome.CANCELLED
    assert audits[0].provider is None and audits[0].model is None
    assert audits[0].proposal_count == 0
    assert _memory_snapshot(database_url) == before
