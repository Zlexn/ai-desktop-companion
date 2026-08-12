from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.domain.models import ChatRole
from app.domain.session_summary import (
    SummaryJobKind,
    SummaryJobStatus,
    SummarySuppressionState,
)
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.repositories.summary_automation import SummaryAutomationRepository
from app.services.session_summary_service import (
    SummaryJobReservationService,
    build_summary_processing_policy,
)
from app.services.summary_invalidation import SummaryInvalidationService
from app.services.summary_job_service import SummaryJobService
from app.services.summary_rebuild import SummaryRebuildService
from app.services.summary_dispatch import SummaryProcessingFence
from app.services.session_summary_provider import (
    SessionSummaryProviderResult,
)


def _settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        session_summary_provider="fake",
        session_summary_trigger_turn_count=1,
        session_summary_max_input_turns=3,
        session_summary_max_input_messages=6,
        session_summary_max_input_characters=10_000,
        summary_rebuild_min_safe_turns=1,
    )


async def _generated_summary(database_url: str, *, turn_count: int = 1):
    settings = _settings(database_url)
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("summary")
        turns = []
        for index in range(turn_count):
            user = MessageRepository(connection).add(
                session.id,
                ChatRole.USER,
                f"safe user source {index}",
            )
            _, turn = ChatTurnRepository(connection).append_assistant_turn(
                session_id=session.id,
                user_message_id=user.id,
                content=f"safe assistant source {index}",
                metadata={},
            )
            turns.append(turn)
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
        ).reserve_for_turn(session.id, turns[-1].id)
        assert reservation is not None
        job = reservation[0]
    result = await SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
    ).process(job.id)
    with managed_connection(database_url) as connection:
        summary = connection.execute(
            "SELECT * FROM session_summaries WHERE session_id=?",
            (session.id,),
        ).fetchone()
        assert summary is not None
        return settings, result, dict(summary)


@pytest.mark.asyncio
async def test_session_deletion_cascades_exact_summary_and_suppression(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'session-cascade.db'}"
    settings, _, summary = await _generated_summary(database_url)
    suppressed = SummaryInvalidationService(database_url).redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    rebuild = SummaryRebuildService(database_url, settings=settings)
    permit = rebuild.authorize(
        summary_id=summary["id"],
        expected_suppression_generation=suppressed.generation,
    )
    rebuild.reserve(permit.permit_id)

    with managed_connection(database_url) as connection:
        assert SessionRepository(connection).delete(summary["session_id"]) is True
        assert connection.execute(
            "SELECT COUNT(*) FROM session_summaries WHERE session_id=?",
            (summary["session_id"],),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM summary_source_suppressions WHERE session_id=?",
            (summary["session_id"],),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM summary_suppression_audits WHERE session_id=?",
            (summary["session_id"],),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM summary_jobs WHERE session_id=?",
            (summary["session_id"],),
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_direct_sql_cannot_redact_or_delete_exact_summary(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'direct-bypass.db'}"
    _, _, summary = await _generated_summary(database_url)

    with managed_connection(database_url) as connection:
        with pytest.raises(Exception, match="atomic service"):
            connection.execute(
                "UPDATE session_summaries SET summary_text=NULL, "
                "payload_state='redacted', redacted_at='now', "
                "redaction_reason_code='bypass' WHERE id=?",
                (summary["id"],),
            )
        connection.rollback()
        with pytest.raises(Exception, match="directly deleted"):
            connection.execute(
                "DELETE FROM session_summaries WHERE id=?",
                (summary["id"],),
            )
        connection.rollback()
        row = connection.execute(
            "SELECT summary_text, payload_state FROM session_summaries WHERE id=?",
            (summary["id"],),
        ).fetchone()
        assert row["summary_text"] is not None
        assert row["payload_state"] == "active"


@pytest.mark.asyncio
async def test_direct_sql_cannot_complete_or_delete_suppression(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'suppression-bypass.db'}"
    _, _, summary = await _generated_summary(database_url)
    SummaryInvalidationService(database_url).redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )

    with managed_connection(database_url) as connection:
        with pytest.raises(Exception, match="atomic service"):
            connection.execute(
                "UPDATE summary_source_suppressions "
                "SET generation=generation+1, state='rebuild_completed', "
                "reason_code='bypass', updated_at='now' "
                "WHERE session_id=? AND source_set_hash=?",
                (summary["session_id"], summary["source_set_hash"]),
            )
        connection.rollback()
        with pytest.raises(Exception, match="directly deleted"):
            connection.execute(
                "DELETE FROM summary_source_suppressions "
                "WHERE session_id=? AND source_set_hash=?",
                (summary["session_id"], summary["source_set_hash"]),
            )
        connection.rollback()
        row = connection.execute(
            "SELECT generation, state FROM summary_source_suppressions "
            "WHERE session_id=? AND source_set_hash=?",
            (summary["session_id"], summary["source_set_hash"]),
        ).fetchone()
        assert tuple(row) == (1, "suppressed")


@pytest.mark.asyncio
async def test_redaction_clears_all_active_exact_payloads_for_source_identity(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'identity-redaction.db'}"
    _, _, summary = await _generated_summary(database_url)
    duplicate_id = "same-source-active-before-redaction"
    with managed_connection(database_url) as connection:
        source = connection.execute(
            "SELECT * FROM session_summaries WHERE id=?",
            (summary["id"],),
        ).fetchone()
        connection.execute(
            "INSERT INTO session_summaries ("
            "id, session_id, summary_text, source, covered_message_start_id, "
            "covered_message_end_id, message_count, metadata_json, created_at, "
            "updated_at, observed_memory_summary_barrier, payload_state, "
            "source_set_hash, summarizer_schema_version, injection_schema_version, "
            "provenance_state) VALUES (?, ?, 'second private payload', 'manual', ?, ?, "
            "?, '{}', '9999', '9999', ?, 'active', ?, ?, ?, 'exact')",
            (
                duplicate_id,
                summary["session_id"],
                source["covered_message_start_id"],
                source["covered_message_end_id"],
                source["message_count"],
                source["observed_memory_summary_barrier"],
                summary["source_set_hash"],
                source["summarizer_schema_version"],
                source["injection_schema_version"],
            ),
        )
        for source_row in connection.execute(
            "SELECT chat_turn_id, message_id, turn_order, "
            "message_order_in_turn, source_order "
            "FROM session_summary_sources WHERE summary_id=? ORDER BY source_order",
            (summary["id"],),
        ).fetchall():
            connection.execute(
                "INSERT INTO session_summary_sources ("
                "summary_id, chat_turn_id, message_id, turn_order, "
                "message_order_in_turn, source_order) VALUES (?, ?, ?, ?, ?, ?)",
                (duplicate_id, *tuple(source_row)),
            )
        connection.commit()

    result = SummaryInvalidationService(database_url).redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )

    assert result.generation == 1
    with managed_connection(database_url) as connection:
        rows = connection.execute(
            "SELECT id, summary_text, payload_state FROM session_summaries "
            "WHERE id IN (?, ?) ORDER BY id",
            (summary["id"], duplicate_id),
        ).fetchall()
        assert len(rows) == 2
        assert all(tuple(row)[1:] == (None, "redacted") for row in rows)
        audits = connection.execute(
            "SELECT summary_id, action, payload_state FROM summary_payload_audits "
            "WHERE summary_id IN (?, ?) ORDER BY summary_id",
            (summary["id"], duplicate_id),
        ).fetchall()
        assert [tuple(row)[1:] for row in audits] == [
            ("redacted", "redacted"),
            ("redacted", "redacted"),
        ]


@pytest.mark.asyncio
async def test_existing_suppression_does_not_skip_second_active_payload_redaction(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'same-source-redaction.db'}"
    _, _, summary = await _generated_summary(database_url)
    invalidator = SummaryInvalidationService(database_url)
    first = invalidator.redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    with managed_connection(database_url) as connection:
        duplicate_id = "same-source-active"
        source = connection.execute(
            "SELECT * FROM session_summaries WHERE id=?",
            (summary["id"],),
        ).fetchone()
        connection.execute(
            "INSERT INTO session_summaries ("
            "id, session_id, summary_text, source, covered_message_start_id, "
            "covered_message_end_id, message_count, metadata_json, created_at, "
            "updated_at, observed_memory_summary_barrier, payload_state, "
            "source_set_hash, summarizer_schema_version, injection_schema_version, "
            "provenance_state) VALUES (?, ?, 'second private payload', 'manual', ?, ?, "
            "?, '{}', '9999', '9999', ?, 'active', ?, ?, ?, 'exact')",
            (
                duplicate_id,
                summary["session_id"],
                source["covered_message_start_id"],
                source["covered_message_end_id"],
                source["message_count"],
                source["observed_memory_summary_barrier"],
                summary["source_set_hash"],
                source["summarizer_schema_version"],
                source["injection_schema_version"],
            ),
        )
        for source_row in connection.execute(
            "SELECT chat_turn_id, message_id, turn_order, "
            "message_order_in_turn, source_order "
            "FROM session_summary_sources WHERE summary_id=? ORDER BY source_order",
            (summary["id"],),
        ).fetchall():
            connection.execute(
                "INSERT INTO session_summary_sources ("
                "summary_id, chat_turn_id, message_id, turn_order, "
                "message_order_in_turn, source_order) VALUES (?, ?, ?, ?, ?, ?)",
                (duplicate_id, *tuple(source_row)),
            )
        connection.commit()

    result = invalidator.redact_summary(
        duplicate_id,
        expected_suppression_generation=first.generation,
        confirmation="redact_summary_payload",
    )

    assert result.generation == first.generation + 1
    with managed_connection(database_url) as connection:
        row = connection.execute(
            "SELECT summary_text, payload_state FROM session_summaries WHERE id=?",
            (duplicate_id,),
        ).fetchone()
        assert tuple(row) == (None, "redacted")


@pytest.mark.asyncio
async def test_redaction_clears_payload_and_suppresses_exact_source_set(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'redact.db'}"
    _, _, summary = await _generated_summary(database_url)
    service = SummaryInvalidationService(database_url)

    result = service.redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )

    assert result.state is SummarySuppressionState.SUPPRESSED
    assert result.generation == 1
    with managed_connection(database_url) as connection:
        row = connection.execute(
            "SELECT * FROM session_summaries WHERE id=?",
            (summary["id"],),
        ).fetchone()
        assert row["summary_text"] is None
        assert row["payload_state"] == "redacted"
        assert row["redaction_reason_code"] == "user_privacy_redaction"
        suppression = connection.execute(
            "SELECT * FROM summary_source_suppressions WHERE session_id=? "
            "AND source_set_hash=?",
            (summary["session_id"], summary["source_set_hash"]),
        ).fetchone()
        assert suppression["state"] == "suppressed"
        assert suppression["generation"] == 1
        raw = "\n".join(
            str(tuple(item))
            for item in connection.execute(
                "SELECT * FROM session_summaries WHERE id=?",
                (summary["id"],),
            )
        )
        assert "safe user source" not in raw
        assert "safe assistant source" not in raw


@pytest.mark.asyncio
async def test_redaction_is_cas_guarded_and_idempotent_only_at_current_generation(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'redact-cas.db'}"
    _, _, summary = await _generated_summary(database_url)
    service = SummaryInvalidationService(database_url)

    service.redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    duplicate = service.redact_summary(
        summary["id"],
        expected_suppression_generation=1,
        confirmation="redact_summary_payload",
    )

    assert duplicate.generation == 1
    with pytest.raises(ValueError, match="generation"):
        service.redact_summary(
            summary["id"],
            expected_suppression_generation=0,
            confirmation="redact_summary_payload",
        )


@pytest.mark.asyncio
async def test_one_permit_binds_one_rebuild_job_and_retry_reuses_it(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'permit.db'}"
    settings, _, summary = await _generated_summary(database_url)
    invalidator = SummaryInvalidationService(database_url)
    suppressed = invalidator.redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    rebuild = SummaryRebuildService(database_url, settings=settings)

    permit = rebuild.authorize(
        summary_id=summary["id"],
        expected_suppression_generation=suppressed.generation,
    )
    first, created = rebuild.reserve(permit.permit_id)
    second, duplicate_created = rebuild.reserve(permit.permit_id)

    assert created is True
    assert duplicate_created is False
    assert first.id == second.id
    assert first.job_kind is SummaryJobKind.REBUILD
    assert first.source_summary_id == summary["id"]
    assert permit.authorized_summary_id == summary["id"]
    with managed_connection(database_url) as connection:
        row = connection.execute(
            "SELECT * FROM summary_source_suppressions WHERE rebuild_permit_id=?",
            (permit.permit_id,),
        ).fetchone()
        assert row["state"] == "rebuild_in_progress"
        assert row["bound_job_id"] == first.id


@pytest.mark.asyncio
async def test_permit_reservation_uses_the_authorized_summary_lineage(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'authorized-lineage.db'}"
    settings, _, summary = await _generated_summary(database_url)
    suppressed = SummaryInvalidationService(database_url).redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    rebuild = SummaryRebuildService(database_url, settings=settings)
    permit = rebuild.authorize(
        summary_id=summary["id"],
        expected_suppression_generation=suppressed.generation,
    )
    with managed_connection(database_url) as connection:
        source_summary = connection.execute(
            "SELECT * FROM session_summaries WHERE id=?",
            (summary["id"],),
        ).fetchone()
        newer_id = "newer-redacted-same-source"
        connection.execute(
            "INSERT INTO session_summaries ("
            "id, session_id, summary_text, source, covered_message_start_id, "
            "covered_message_end_id, message_count, metadata_json, created_at, "
            "updated_at, observed_memory_summary_barrier, payload_state, "
            "source_set_hash, summarizer_schema_version, injection_schema_version, "
            "provenance_state, redacted_at, redaction_reason_code) "
            "VALUES (?, ?, NULL, 'manual', ?, ?, ?, '{}', '9999', '9999', ?, "
            "'redacted', ?, ?, ?, 'exact', '9999', 'fixture')",
            (
                newer_id,
                summary["session_id"],
                source_summary["covered_message_start_id"],
                source_summary["covered_message_end_id"],
                source_summary["message_count"],
                source_summary["observed_memory_summary_barrier"],
                summary["source_set_hash"],
                source_summary["summarizer_schema_version"],
                source_summary["injection_schema_version"],
            ),
        )
        connection.commit()

    job, _ = rebuild.reserve(permit.permit_id)

    assert job.source_summary_id == summary["id"]
    assert job.source_summary_id != newer_id


@pytest.mark.asyncio
async def test_permit_cannot_be_used_for_another_source_set(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'permit-theft.db'}"
    settings, _, first_summary = await _generated_summary(database_url)
    invalidator = SummaryInvalidationService(database_url)
    suppressed = invalidator.redact_summary(
        first_summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    permit = SummaryRebuildService(database_url, settings=settings).authorize(
        summary_id=first_summary["id"],
        expected_suppression_generation=suppressed.generation,
    )

    with managed_connection(database_url) as connection:
        with pytest.raises(Exception, match="atomic service"):
            connection.execute(
                "UPDATE summary_source_suppressions SET source_set_hash=? "
                "WHERE rebuild_permit_id=?",
                ("f" * 64, permit.permit_id),
            )
        connection.rollback()

    job, created = SummaryRebuildService(
        database_url,
        settings=settings,
    ).reserve(permit.permit_id)
    assert created is True
    assert job.source_summary_id == first_summary["id"]


@pytest.mark.asyncio
async def test_cancel_invalidates_permit_and_old_payload_stays_null(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'cancel.db'}"
    settings, _, summary = await _generated_summary(database_url)
    invalidator = SummaryInvalidationService(database_url)
    suppressed = invalidator.redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    rebuild = SummaryRebuildService(database_url, settings=settings)
    permit = rebuild.authorize(
        summary_id=summary["id"],
        expected_suppression_generation=suppressed.generation,
    )
    job, _ = rebuild.reserve(permit.permit_id)

    cancelled = rebuild.cancel(
        permit.permit_id,
        expected_suppression_generation=permit.generation + 1,
    )

    assert cancelled.state is SummarySuppressionState.SUPPRESSED
    assert cancelled.generation == permit.generation + 2
    with managed_connection(database_url) as connection:
        assert connection.execute(
            "SELECT summary_text FROM session_summaries WHERE id=?",
            (summary["id"],),
        ).fetchone()[0] is None
        assert SummaryAutomationRepository(connection).require_job(job.id).status.value == "cancelled"


@pytest.mark.asyncio
async def test_rebuild_commit_creates_replacement_and_completes_suppression(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'rebuild-commit.db'}"
    settings, _, summary = await _generated_summary(database_url)
    invalidator = SummaryInvalidationService(database_url)
    suppressed = invalidator.redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    rebuild = SummaryRebuildService(database_url, settings=settings)
    permit = rebuild.authorize(
        summary_id=summary["id"],
        expected_suppression_generation=suppressed.generation,
    )
    job, _ = rebuild.reserve(permit.permit_id)

    result = await SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
    ).process(job.id)

    assert result.status.value == "succeeded", result.reason_code
    with managed_connection(database_url) as connection:
        rows = connection.execute(
            "SELECT id, summary_text, payload_state, replaces_summary_id "
            "FROM session_summaries WHERE session_id=? ORDER BY created_at, id",
            (summary["session_id"],),
        ).fetchall()
        old = next(row for row in rows if row["id"] == summary["id"])
        replacement = next(row for row in rows if row["id"] != summary["id"])
        assert old["summary_text"] is None
        assert old["payload_state"] == "redacted"
        assert replacement["summary_text"]
        assert replacement["replaces_summary_id"] == summary["id"]
        suppression = connection.execute(
            "SELECT state, generation, rebuild_permit_id, bound_job_id, "
            "authorized_summary_id FROM summary_source_suppressions "
            "WHERE session_id=? AND source_set_hash=?",
            (summary["session_id"], summary["source_set_hash"]),
        ).fetchone()
        assert tuple(suppression) == (
            "rebuild_completed",
            permit.generation + 2,
            None,
            None,
            None,
        )


@pytest.mark.asyncio
async def test_partial_safe_rebuild_completes_original_suppression(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'partial-safe.db'}"
    settings, _, summary = await _generated_summary(database_url, turn_count=2)
    suppressed = SummaryInvalidationService(database_url).redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    rebuild = SummaryRebuildService(database_url, settings=settings)
    permit = rebuild.authorize(
        summary_id=summary["id"],
        expected_suppression_generation=suppressed.generation,
    )
    with managed_connection(database_url) as connection:
        excluded_turn = connection.execute(
            "SELECT chat_turn_id FROM session_summary_sources WHERE summary_id=? "
            "ORDER BY source_order LIMIT 1",
            (summary["id"],),
        ).fetchone()[0]
        excluded_ids = connection.execute(
            "SELECT user_message_id, assistant_message_id FROM chat_turns WHERE id=?",
            (excluded_turn,),
        ).fetchone()
        connection.executemany(
            "INSERT INTO memory_summary_source_exclusions "
            "(source_message_id, reason_code, created_at) VALUES (?, 'forget', 'now')",
            ((message_id,) for message_id in excluded_ids),
        )
        connection.commit()

    job, _ = rebuild.reserve(permit.permit_id)
    assert job.source_set_hash != summary["source_set_hash"]
    result = await SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
    ).process(job.id)

    assert result.status.value == "succeeded", result.reason_code
    with managed_connection(database_url) as connection:
        replacement = connection.execute(
            "SELECT * FROM session_summaries WHERE replaces_summary_id=?",
            (summary["id"],),
        ).fetchone()
        assert replacement is not None
        assert replacement["source_set_hash"] == job.source_set_hash
        assert replacement["message_count"] == 2
        original = connection.execute(
            "SELECT summary_text, payload_state FROM session_summaries WHERE id=?",
            (summary["id"],),
        ).fetchone()
        assert tuple(original) == (None, "redacted")
        suppression = connection.execute(
            "SELECT source_set_hash, state, generation "
            "FROM summary_source_suppressions WHERE session_id=? "
            "AND source_set_hash=?",
            (summary["session_id"], summary["source_set_hash"]),
        ).fetchone()
        assert tuple(suppression) == (
            summary["source_set_hash"],
            "rebuild_completed",
            permit.generation + 2,
        )
        assert connection.execute(
            "SELECT 1 FROM summary_source_suppressions "
            "WHERE source_set_hash=?",
            (job.source_set_hash,),
        ).fetchone() is None


@pytest.mark.asyncio
async def test_redacted_in_progress_rebuild_is_discarded_before_provider_construction(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'pre-send-cancel.db'}"
    settings, _, summary = await _generated_summary(database_url)
    suppressed = SummaryInvalidationService(database_url).redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    rebuild = SummaryRebuildService(database_url, settings=settings)
    permit = rebuild.authorize(
        summary_id=summary["id"],
        expected_suppression_generation=suppressed.generation,
    )
    job, _ = rebuild.reserve(permit.permit_id)
    SummaryInvalidationService(database_url).redact_summary(
        summary["id"],
        expected_suppression_generation=permit.generation + 1,
        confirmation="redact_summary_payload",
    )
    constructed = 0

    def provider_factory():
        nonlocal constructed
        constructed += 1
        raise AssertionError("stale rebuild must not construct a provider")

    result = await SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
        fake_provider_factory=provider_factory,
    ).process(job.id)

    assert constructed == 0
    assert result.status.value == "skipped"
    assert result.reason_code == "discarded_suppression_changed"
    with managed_connection(database_url) as connection:
        audit = connection.execute(
            "SELECT status, reason_code FROM summary_job_audits "
            "WHERE job_id=? ORDER BY created_at DESC LIMIT 1",
            (job.id,),
        ).fetchone()
        assert tuple(audit) == ("skipped", "discarded_suppression_changed")


class _ProviderFailure:
    async def generate(self, messages, options):
        del messages, options
        raise RuntimeError("provider failed")

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_failed_rebuild_remains_bound_until_explicit_cancel(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'failed-bound.db'}"
    settings, _, summary = await _generated_summary(database_url)
    suppressed = SummaryInvalidationService(database_url).redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    rebuild = SummaryRebuildService(database_url, settings=settings)
    permit = rebuild.authorize(
        summary_id=summary["id"],
        expected_suppression_generation=suppressed.generation,
    )
    job, _ = rebuild.reserve(permit.permit_id)

    result = await SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
        fake_provider_factory=_ProviderFailure,
    ).process(job.id)

    assert result.status.value == "failed"
    with managed_connection(database_url) as connection:
        state = connection.execute(
            "SELECT generation, state, rebuild_permit_id, bound_job_id "
            "FROM summary_source_suppressions WHERE session_id=? "
            "AND source_set_hash=?",
            (summary["session_id"], summary["source_set_hash"]),
        ).fetchone()
        assert tuple(state) == (
            permit.generation + 1,
            "rebuild_in_progress",
            permit.permit_id,
            job.id,
        )
        assert connection.execute(
            "SELECT summary_text FROM session_summaries WHERE id=?",
            (summary["id"],),
        ).fetchone()[0] is None

    duplicate, created = rebuild.reserve(permit.permit_id)
    assert created is False
    assert duplicate.id == job.id
    cancelled = rebuild.cancel(
        permit.permit_id,
        expected_suppression_generation=permit.generation + 1,
    )
    assert cancelled.state is SummarySuppressionState.SUPPRESSED


@pytest.mark.asyncio
async def test_failed_rebuild_retry_issues_new_permit_and_job(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'failed-retry.db'}"
    settings, _, summary = await _generated_summary(database_url)
    suppressed = SummaryInvalidationService(database_url).redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    rebuild = SummaryRebuildService(database_url, settings=settings)
    permit = rebuild.authorize(
        summary_id=summary["id"],
        expected_suppression_generation=suppressed.generation,
    )
    failed_job, _ = rebuild.reserve(permit.permit_id)
    failed = await SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
        fake_provider_factory=_ProviderFailure,
    ).process(failed_job.id)
    assert failed.status is SummaryJobStatus.FAILED

    retried, retry_suppression = rebuild.retry(
        job_id=failed_job.id,
        expected_job_status=SummaryJobStatus.FAILED,
        expected_suppression_generation=permit.generation + 1,
        expected_suppression_state=SummarySuppressionState.REBUILD_IN_PROGRESS,
    )

    assert retried.id != failed_job.id
    assert retried.status is SummaryJobStatus.PENDING
    assert retried.rebuild_permit_id != permit.permit_id
    assert retry_suppression.state is SummarySuppressionState.REBUILD_IN_PROGRESS
    assert retry_suppression.bound_job_id == retried.id
    assert retry_suppression.generation == permit.generation + 4
    with managed_connection(database_url) as connection:
        repository = SummaryAutomationRepository(connection)
        assert repository.require_job(failed_job.id).status is SummaryJobStatus.FAILED
        assert repository.require_job(retried.id).status is SummaryJobStatus.PENDING


@pytest.mark.asyncio
async def test_cancelled_rebuild_retry_requires_exact_suppression_snapshot(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'cancelled-retry.db'}"
    settings, _, summary = await _generated_summary(database_url)
    suppressed = SummaryInvalidationService(database_url).redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    rebuild = SummaryRebuildService(database_url, settings=settings)
    permit = rebuild.authorize(
        summary_id=summary["id"],
        expected_suppression_generation=suppressed.generation,
    )
    cancelled_job, _ = rebuild.reserve(permit.permit_id)
    cancelled = rebuild.cancel(
        permit.permit_id,
        expected_suppression_generation=permit.generation + 1,
    )

    with pytest.raises(ValueError, match="snapshot"):
        rebuild.retry(
            job_id=cancelled_job.id,
            expected_job_status=SummaryJobStatus.CANCELLED,
            expected_suppression_generation=cancelled.generation - 1,
            expected_suppression_state=SummarySuppressionState.SUPPRESSED,
        )

    retried, retry_suppression = rebuild.retry(
        job_id=cancelled_job.id,
        expected_job_status=SummaryJobStatus.CANCELLED,
        expected_suppression_generation=cancelled.generation,
        expected_suppression_state=SummarySuppressionState.SUPPRESSED,
    )
    assert retried.id != cancelled_job.id
    assert retried.status is SummaryJobStatus.PENDING
    assert retry_suppression.state is SummarySuppressionState.REBUILD_IN_PROGRESS
    assert retry_suppression.bound_job_id == retried.id


class _ChangingDeletionGenerationProvider:
    def __init__(self, generation: list[int]) -> None:
        self._generation = generation

    async def generate(self, messages, options):
        del messages, options
        self._generation[0] += 1
        return SessionSummaryProviderResult(
            text="discard this result",
            provider="fake",
            model="fake-session-summary-v1",
        )

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_rebuild_discards_when_session_deletion_generation_changes(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'deletion-race.db'}"
    settings, _, summary = await _generated_summary(database_url)
    suppressed = SummaryInvalidationService(database_url).redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    generation = [4]
    read_generation = lambda _session_id: generation[0]
    rebuild = SummaryRebuildService(
        database_url,
        settings=settings,
        session_deletion_generation=read_generation,
    )
    permit = rebuild.authorize(
        summary_id=summary["id"],
        expected_suppression_generation=suppressed.generation,
    )
    job, _ = rebuild.reserve(permit.permit_id)

    result = await SummaryJobService(
        database_url=database_url,
        settings=settings,
        processing_fence=SummaryProcessingFence(),
        fake_provider_factory=lambda: _ChangingDeletionGenerationProvider(
            generation
        ),
        session_deletion_generation=read_generation,
    ).process(job.id)

    assert result.status.value == "skipped"
    assert result.reason_code == "discarded_session_deleted"
    with managed_connection(database_url) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_summaries WHERE replaces_summary_id=?",
            (summary["id"],),
        ).fetchone()[0] == 0
        state = connection.execute(
            "SELECT state, bound_job_id FROM summary_source_suppressions "
            "WHERE rebuild_permit_id=?",
            (permit.permit_id,),
        ).fetchone()
        assert tuple(state) == ("rebuild_in_progress", job.id)


@pytest.mark.asyncio
async def test_rebuild_reservation_captures_session_deletion_generation(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'deletion-generation.db'}"
    settings, _, summary = await _generated_summary(database_url)
    suppressed = SummaryInvalidationService(database_url).redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    rebuild = SummaryRebuildService(
        database_url,
        settings=settings,
        session_deletion_generation=lambda session_id: (
            7 if session_id == summary["session_id"] else 0
        ),
    )
    permit = rebuild.authorize(
        summary_id=summary["id"],
        expected_suppression_generation=suppressed.generation,
    )

    job, _ = rebuild.reserve(permit.permit_id)

    assert job.captured_session_deletion_generation == 7


@pytest.mark.asyncio
async def test_rebuild_rejects_when_no_safe_complete_turn_remains(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'unsafe.db'}"
    settings, _, summary = await _generated_summary(database_url)
    invalidator = SummaryInvalidationService(database_url)
    suppressed = invalidator.redact_summary(
        summary["id"],
        expected_suppression_generation=0,
        confirmation="redact_summary_payload",
    )
    rebuild = SummaryRebuildService(database_url, settings=settings)
    permit = rebuild.authorize(
        summary_id=summary["id"],
        expected_suppression_generation=suppressed.generation,
    )
    with managed_connection(database_url) as connection:
        source_id = connection.execute(
            "SELECT message_id FROM session_summary_sources WHERE summary_id=? "
            "ORDER BY source_order LIMIT 1",
            (summary["id"],),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO memory_summary_source_exclusions "
            "(source_message_id, reason_code, created_at) VALUES (?, 'forget', 'now')",
            (source_id,),
        )
        connection.commit()

    with pytest.raises(ValueError, match="safe complete turns"):
        rebuild.reserve(permit.permit_id)
