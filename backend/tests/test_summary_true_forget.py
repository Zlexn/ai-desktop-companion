from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import Settings
from app.domain.models import ChatRole, MemorySource, MemoryType
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.memories import MemoryRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.repositories.summary_automation import SummaryAutomationRepository
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.memory_forget_service import MemoryForgetService
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.session_summary_service import (
    SummaryJobReservationService,
    build_summary_processing_policy,
)
from app.services.summary_dispatch import SummaryProcessingFence
from app.services.summary_job_service import SummaryJobService
from app.services.summary_rebuild import SummaryRebuildService


_NOW = datetime(2026, 7, 23, tzinfo=UTC)


def _settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        session_summary_provider="fake",
        session_summary_trigger_turn_count=1,
        session_summary_max_input_turns=3,
        session_summary_max_input_messages=6,
        summary_rebuild_min_safe_turns=1,
    )


async def _seed_derived_summary(
    database_url: str,
    *,
    include_safe_turn: bool = False,
) -> dict[str, str]:
    settings = _settings(database_url)
    references = MemorySourceReferenceService(b"t" * 32)
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("true forget")
        user = MessageRepository(connection).add(
            session.id,
            ChatRole.USER,
            "SECRET_SENTINEL",
        )
        assistant, turn = ChatTurnRepository(connection).append_assistant_turn(
            session_id=session.id,
            user_message_id=user.id,
            content="You said SECRET_SENTINEL",
            metadata={},
        )
        final_turn = turn
        if include_safe_turn:
            safe_user = MessageRepository(connection).add(
                session.id,
                ChatRole.USER,
                "SAFE_REMAINING_TURN",
            )
            _, final_turn = ChatTurnRepository(connection).append_assistant_turn(
                session_id=session.id,
                user_message_id=safe_user.id,
                content="safe remaining reply",
                metadata={},
            )
        memory = MemoryRepository(
            connection,
            source_references=references,
        ).create(
            content="private derived memory",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=session.id,
            importance=3,
            confidence=0.9,
        )[0]
        version = VersionedMemoryRepository(connection).get_current_version(memory.id)
        assert version is not None
        connection.execute(
            """
            INSERT INTO memory_evidence (
                evidence_id, memory_id, memory_version_id,
                source_session_id, source_message_id,
                source_session_reference_hash, source_message_reference_hash,
                source_available, source_deleted_at, relation, observed_at,
                extractor_kind, extractor_provider, extractor_model,
                confidence, created_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, 1, NULL,
                'supports', ?, 'manual', NULL, NULL, 0.9, ?
            )
            """,
            (
                f"true-forget-evidence-{memory.id}",
                memory.id,
                version.id,
                session.id,
                user.id,
                references.session_hash(session.id),
                references.message_hash(user.id),
                _NOW.isoformat(),
                _NOW.isoformat(),
            ),
        )
        connection.commit()
        automation = SummaryAutomationRepository(connection)
        policy = build_summary_processing_policy(settings)
        authority = automation.get_processing_authority()
        automation.mutate_processing(
            action="enable_local",
            expected_generation=authority.generation,
            policy=policy,
        )
        reservation = SummaryJobReservationService(
            connection,
            settings=settings,
        ).reserve_for_turn(session.id, final_turn.id)
        assert reservation is not None
        job = reservation[0]

    result = await SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
    ).process(job.id)
    assert result.status.value == "succeeded"
    with managed_connection(database_url) as connection:
        summary = connection.execute(
            "SELECT id FROM session_summaries WHERE session_id=?",
            (session.id,),
        ).fetchone()
        assert summary is not None
    return {
        "session_id": session.id,
        "user_id": user.id,
        "assistant_id": assistant.id,
        "memory_id": memory.id,
        "summary_id": str(summary["id"]),
    }


def _forget(connection, memory_id: str, *, fault_injector=None):
    return MemoryForgetService(
        connection,
        versioned=VersionedMemoryRepository(connection),
        source_references=MemorySourceReferenceService(b"t" * 32),
        fault_injector=fault_injector,
    ).forget_memory(memory_id)


@pytest.mark.asyncio
async def test_true_forget_closes_turn_and_physically_redacts_derived_summary(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'summary-true-forget.db'}"
    ids = await _seed_derived_summary(database_url)

    with managed_connection(database_url) as connection:
        result = _forget(connection, ids["memory_id"])

        excluded = {
            str(row["source_message_id"])
            for row in connection.execute(
                "SELECT source_message_id FROM memory_summary_source_exclusions"
            ).fetchall()
        }
        assert {ids["user_id"], ids["assistant_id"]} <= excluded
        summary = connection.execute(
            "SELECT summary_text, payload_state, redaction_reason_code "
            "FROM session_summaries WHERE id=?",
            (ids["summary_id"],),
        ).fetchone()
        assert tuple(summary) == (
            None,
            "redacted",
            "memory_true_forget",
        )
        suppression = connection.execute(
            "SELECT generation, state FROM summary_source_suppressions "
            "WHERE session_id=?",
            (ids["session_id"],),
        ).fetchone()
        assert tuple(suppression) == (1, "suppressed")
        assert result.summary_barrier_generation == 1
        raw_payloads = "\n".join(
            str(value)
            for row in connection.execute(
                "SELECT summary_text FROM session_summaries"
            ).fetchall()
            for value in row
        )
        assert "SECRET_SENTINEL" not in raw_payloads
        payload_audit = connection.execute(
            "SELECT action, payload_state, reason_code "
            "FROM summary_payload_audits WHERE summary_id=? "
            "ORDER BY created_at DESC LIMIT 1",
            (ids["summary_id"],),
        ).fetchone()
        assert tuple(payload_audit) == (
            "redacted",
            "redacted",
            "memory_true_forget",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "checkpoint",
    [
        "summary_exclusions",
        "summary_barrier",
        "summary_payloads",
        "summary_suppressions",
        "summary_revalidation",
    ],
)
async def test_true_forget_summary_invalidation_fault_rolls_back_every_surface(
    tmp_path: Path,
    checkpoint: str,
) -> None:
    database_url = f"sqlite:///{tmp_path / f'rollback-{checkpoint}.db'}"
    ids = await _seed_derived_summary(database_url)

    def fail(name: str) -> None:
        if name == checkpoint:
            raise RuntimeError("fault")

    with managed_connection(database_url) as connection:
        with pytest.raises(RuntimeError, match="fault"):
            _forget(
                connection,
                ids["memory_id"],
                fault_injector=fail,
            )

        summary = connection.execute(
            "SELECT summary_text, payload_state, observed_memory_summary_barrier "
            "FROM session_summaries WHERE id=?",
            (ids["summary_id"],),
        ).fetchone()
        assert summary["summary_text"] is not None
        assert tuple(summary)[1:] == ("active", 0)
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_summary_source_exclusions"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT generation FROM memory_summary_barrier"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM summary_source_suppressions"
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_true_forget_revalidates_safe_exact_and_redacts_unmappable_legacy(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'revalidate-safe.db'}"
    forgotten = await _seed_derived_summary(database_url)
    safe = await _seed_derived_summary(database_url)
    with managed_connection(database_url) as connection:
        connection.execute(
            """
            INSERT INTO session_summaries (
                id, session_id, summary_text, source, message_count,
                metadata_json, created_at, updated_at,
                observed_memory_summary_barrier, payload_state,
                provenance_state
            ) VALUES (
                'legacy-unmappable', ?, 'LEGACY_PRIVATE_PAYLOAD', 'manual', 0,
                '{}', ?, ?, 0, 'active', 'legacy_unverified'
            )
            """,
            (
                safe["session_id"],
                _NOW.isoformat(),
                _NOW.isoformat(),
            ),
        )
        connection.commit()
        _forget(connection, forgotten["memory_id"])

        safe_summary = connection.execute(
            "SELECT summary_text, payload_state, "
            "observed_memory_summary_barrier FROM session_summaries WHERE id=?",
            (safe["summary_id"],),
        ).fetchone()
        assert safe_summary["summary_text"] is not None
        assert tuple(safe_summary)[1:] == ("active", 1)
        legacy = connection.execute(
            "SELECT summary_text, payload_state, redaction_reason_code "
            "FROM session_summaries WHERE id='legacy-unmappable'"
        ).fetchone()
        assert tuple(legacy) == (
            None,
            "redacted",
            "memory_true_forget",
        )
        safe_audit = connection.execute(
            "SELECT action, payload_state, reason_code "
            "FROM summary_payload_audits WHERE summary_id=? "
            "ORDER BY created_at DESC LIMIT 1",
            (safe["summary_id"],),
        ).fetchone()
        assert tuple(safe_audit) == (
            "revalidated",
            "active",
            "memory_true_forget_safe_revalidation",
        )


@pytest.mark.asyncio
async def test_true_forget_invalidates_bound_rebuild_before_provider_construction(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'rebuild-after-forget.db'}"
    ids = await _seed_derived_summary(database_url)
    settings = _settings(database_url)
    from app.services.summary_invalidation import SummaryInvalidationService

    suppressed = SummaryInvalidationService(database_url).redact_summary(
        ids["summary_id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    rebuild = SummaryRebuildService(database_url, settings=settings)
    permit = rebuild.authorize(
        summary_id=ids["summary_id"],
        expected_suppression_generation=suppressed.generation,
    )
    job, _ = rebuild.reserve(permit.permit_id)

    with managed_connection(database_url) as connection:
        _forget(connection, ids["memory_id"])

    constructed = 0

    class NeverProvider:
        async def generate(self, messages, options):
            raise AssertionError("provider must not be called")

        async def aclose(self) -> None:
            return None

    def factory():
        nonlocal constructed
        constructed += 1
        return NeverProvider()

    result = await SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
        fake_provider_factory=factory,
    ).process(job.id)

    assert result.status.value == "skipped"
    assert result.reason_code == "discarded_barrier_changed"
    assert constructed == 0
    with managed_connection(database_url) as connection:
        suppression = connection.execute(
            "SELECT state, rebuild_permit_id, bound_job_id, "
            "authorized_summary_id FROM summary_source_suppressions "
            "WHERE session_id=?",
            (ids["session_id"],),
        ).fetchone()
        assert tuple(suppression) == ("suppressed", None, None, None)


@pytest.mark.asyncio
async def test_true_forget_rebuild_uses_only_safe_remaining_complete_turns(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'safe-rebuild-after-forget.db'}"
    settings = _settings(database_url)
    ids = await _seed_derived_summary(
        database_url,
        include_safe_turn=True,
    )
    with managed_connection(database_url) as connection:
        _forget(connection, ids["memory_id"])
        combined = connection.execute(
            "SELECT id FROM session_summaries WHERE session_id=?",
            (ids["session_id"],),
        ).fetchone()
        assert combined is not None
        combined_id = str(combined["id"])

    rebuild = SummaryRebuildService(database_url, settings=settings)
    with managed_connection(database_url) as connection:
        suppression = connection.execute(
            "SELECT generation FROM summary_source_suppressions "
            "WHERE session_id=? AND source_set_hash=("
            "SELECT source_set_hash FROM session_summaries WHERE id=?)",
            (ids["session_id"], combined_id),
        ).fetchone()
        assert suppression is not None
    permit = rebuild.authorize(
        summary_id=combined_id,
        expected_suppression_generation=int(suppression["generation"]),
    )
    job, _ = rebuild.reserve(permit.permit_id)
    with managed_connection(database_url) as connection:
        sources = connection.execute(
            "SELECT source.message_id, message.content "
            "FROM summary_job_sources AS source "
            "JOIN messages AS message ON message.id=source.message_id "
            "WHERE source.job_id=? ORDER BY source.source_order",
            (job.id,),
        ).fetchall()
        contents = [str(row["content"]) for row in sources]
        assert contents == ["SAFE_REMAINING_TURN", "safe remaining reply"]
        assert all("SECRET_SENTINEL" not in content for content in contents)
