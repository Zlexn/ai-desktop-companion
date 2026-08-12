from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.domain.models import ChatRole
from app.domain.session_summary import SummaryJobKind, SummaryJobStatus
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.repositories.summary_automation import SummaryAutomationRepository
from app.services.session_summary_contract import SUMMARY_SCHEMA_VERSION


def _snapshot(connection, session_id: str):
    messages = MessageRepository(connection)
    user = messages.add(session_id, ChatRole.USER, "private source text")
    assistant, _ = ChatTurnRepository(connection).append_assistant_turn(
        session_id=session_id,
        user_message_id=user.id,
        content="private assistant text",
        metadata={},
    )
    snapshot = ChatTurnRepository(connection).snapshot_generation_sources(
        session_id=session_id,
        after_turn_order=0,
        max_turns=1,
        max_messages=2,
        max_characters=10_000,
    )
    return snapshot, user, assistant


def _reservation(snapshot) -> dict[str, object]:
    return {
        "snapshot": snapshot,
        "job_kind": SummaryJobKind.INCREMENTAL,
        "route": "remote",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "summarizer_schema_version": SUMMARY_SCHEMA_VERSION,
        "processing_consent_generation": 4,
        "processing_policy_fingerprint": "processing-policy-fingerprint",
        "provider_policy_fingerprint": "provider-policy-fingerprint",
        "session_deletion_generation": 2,
        "suppression_generation": 3,
        "rebuild_authorization_generation": 0,
        "rebuild_permit_id": None,
    }


def test_same_epoch_deduplicates_but_new_consent_generation_allows_attempt(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'job-identity.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("jobs")
        snapshot, _, _ = _snapshot(connection, session.id)
        repository = SummaryAutomationRepository(connection)
        reservation = _reservation(snapshot)

        first, created = repository.reserve_job(**reservation)
        duplicate, duplicate_created = repository.reserve_job(**reservation)
        later, later_created = repository.reserve_job(
            **{
                **reservation,
                "processing_consent_generation": 5,
            }
        )

        assert created is True
        assert duplicate_created is False
        assert duplicate.id == first.id
        assert later_created is True
        assert later.id != first.id
        assert later.logical_source_identity == first.logical_source_identity
        assert later.attempt_epoch != first.attempt_epoch
        assert first.status is later.status is SummaryJobStatus.PENDING


def test_logical_identity_changes_only_for_logical_source_inputs(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'logical-identity.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("jobs")
        snapshot, _, _ = _snapshot(connection, session.id)
        repository = SummaryAutomationRepository(connection)
        reservation = _reservation(snapshot)

        baseline, _ = repository.reserve_job(**reservation)
        provider_epoch, _ = repository.reserve_job(
            **{**reservation, "provider_policy_fingerprint": "provider-policy-v2"}
        )
        connection.execute(
            "UPDATE memory_summary_barrier SET generation=generation+1 "
            "WHERE singleton_id=1"
        )
        connection.commit()
        new_barrier_snapshot = replace(
            snapshot,
            barrier_generation=snapshot.barrier_generation + 1,
        )
        logical_change, _ = repository.reserve_job(
            **{**reservation, "snapshot": new_barrier_snapshot}
        )

        assert provider_epoch.logical_source_identity == baseline.logical_source_identity
        assert provider_epoch.attempt_epoch != baseline.attempt_epoch
        assert logical_change.logical_source_identity != baseline.logical_source_identity


def test_reservation_copies_only_exact_ids_and_order(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'job-sources.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("jobs")
        snapshot, user, assistant = _snapshot(connection, session.id)

        job, created = SummaryAutomationRepository(connection).reserve_job(
            **_reservation(snapshot)
        )
        rows = connection.execute(
            "SELECT * FROM summary_job_sources WHERE job_id=? ORDER BY source_order",
            (job.id,),
        ).fetchall()

        assert created is True
        assert [(row["message_id"], row["message_order_in_turn"], row["source_order"]) for row in rows] == [
            (user.id, 0, 0),
            (assistant.id, 1, 1),
        ]
        assert job.source_message_count == 2
        assert job.source_turn_count == 1
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(summary_job_sources)")
        }
        assert "content" not in columns
        assert "summary_text" not in columns
        raw = "\n".join(str(tuple(row)) for row in rows)
        assert "private source text" not in raw
        assert "private assistant text" not in raw


def test_job_snapshot_is_immutable_after_reservation(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'job-immutable.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("jobs")
        snapshot, _, _ = _snapshot(connection, session.id)
        job, _ = SummaryAutomationRepository(connection).reserve_job(
            **_reservation(snapshot)
        )

        with pytest.raises(Exception, match="snapshot invariant"):
            connection.execute(
                "UPDATE summary_jobs SET source_set_hash='changed' WHERE id=?",
                (job.id,),
            )
        connection.rollback()


def test_terminal_duplicate_is_returned_but_new_epoch_can_reserve(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'terminal-dedupe.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("jobs")
        snapshot, _, _ = _snapshot(connection, session.id)
        repository = SummaryAutomationRepository(connection)
        reservation = _reservation(snapshot)
        first, _ = repository.reserve_job(**reservation)
        connection.execute(
            "UPDATE summary_jobs SET status='skipped', reason_code='no_consent', "
            "finished_at='2026-07-22T00:00:00+00:00' WHERE id=?",
            (first.id,),
        )
        connection.commit()

        duplicate, created = repository.reserve_job(**reservation)
        later, later_created = repository.reserve_job(
            **{**reservation, "suppression_generation": 4}
        )

        assert created is False
        assert duplicate.id == first.id
        assert duplicate.status is SummaryJobStatus.SKIPPED
        assert later_created is True
        assert later.id != first.id


def test_reservation_rejects_empty_or_mismatched_snapshot(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'invalid-job.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        session = sessions.create("jobs")
        other = sessions.create("other")
        empty = ChatTurnRepository(connection).snapshot_generation_sources(
            session_id=session.id,
            after_turn_order=0,
            max_turns=1,
            max_messages=2,
            max_characters=10_000,
        )
        repository = SummaryAutomationRepository(connection)

        with pytest.raises(ValueError, match="source snapshot"):
            repository.reserve_job(**_reservation(empty))

        snapshot, _, _ = _snapshot(connection, session.id)
        mismatched = replace(snapshot, session_id=other.id)
        with pytest.raises(ValueError, match="source snapshot"):
            repository.reserve_job(**_reservation(mismatched))


def test_reservation_rejects_stale_barrier_snapshot(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'stale-barrier-job.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("jobs")
        snapshot, _, _ = _snapshot(connection, session.id)
        connection.execute(
            "UPDATE memory_summary_barrier SET generation=generation+1 "
            "WHERE singleton_id=1"
        )
        connection.commit()

        with pytest.raises(ValueError, match="source snapshot"):
            SummaryAutomationRepository(connection).reserve_job(
                **_reservation(snapshot)
            )
        assert connection.execute("SELECT COUNT(*) FROM summary_jobs").fetchone()[0] == 0


def test_sealed_job_source_manifest_rejects_invalid_member(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'job-source-trigger.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("jobs")
        snapshot, user, assistant = _snapshot(connection, session.id)
        repository = SummaryAutomationRepository(connection)
        job, _ = repository.reserve_job(**_reservation(snapshot))
        other = MessageRepository(connection).add(
            session.id,
            ChatRole.USER,
            "not part of durable turn",
        )
        with pytest.raises(Exception, match="sealed"):
            connection.execute(
                """
                INSERT INTO summary_job_sources (
                    job_id, chat_turn_id, message_id, turn_order,
                    message_order_in_turn, source_order
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (job.id, snapshot.turns[0].id, other.id, 1, 0, 2),
            )
        connection.rollback()
        assert user.id != other.id
        assert assistant.id != other.id


def test_sealed_job_source_manifest_rejects_extra_valid_turn(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'sealed-job-sources.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("jobs")
        first_snapshot, _, _ = _snapshot(connection, session.id)
        second_user = MessageRepository(connection).add(
            session.id,
            ChatRole.USER,
            "valid but outside frozen snapshot",
        )
        second_assistant, second_turn = ChatTurnRepository(
            connection
        ).append_assistant_turn(
            session_id=session.id,
            user_message_id=second_user.id,
            content="valid second reply",
            metadata={},
        )
        job, _ = SummaryAutomationRepository(connection).reserve_job(
            **_reservation(first_snapshot)
        )

        with pytest.raises(Exception, match="sealed"):
            connection.execute(
                """
                INSERT INTO summary_job_sources (
                    job_id, chat_turn_id, message_id, turn_order,
                    message_order_in_turn, source_order
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (job.id, second_turn.id, second_user.id, 2, 0, 2),
            )
        connection.rollback()
        assert second_assistant.id != first_snapshot.turns[0].messages[1].id


def test_sealed_job_source_manifest_rejects_delete(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'sealed-job-delete.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("jobs")
        snapshot, _, _ = _snapshot(connection, session.id)
        job, _ = SummaryAutomationRepository(connection).reserve_job(
            **_reservation(snapshot)
        )

        with pytest.raises(Exception, match="sealed"):
            connection.execute(
                "DELETE FROM summary_job_sources WHERE job_id=?",
                (job.id,),
            )
        connection.rollback()


def test_incremental_reservation_rejects_active_source_suppression(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'suppressed-reservation.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("jobs")
        snapshot, _, _ = _snapshot(connection, session.id)
        assert snapshot.source_set_hash is not None
        connection.execute(
            "INSERT INTO summary_source_suppressions ("
            "session_id, source_set_hash, generation, state, reason_code, "
            "created_at, updated_at) VALUES (?, ?, 1, 'suppressed', "
            "'privacy', 'now', 'now')",
            (session.id, snapshot.source_set_hash),
        )
        connection.commit()

        with pytest.raises(ValueError, match="suppressed"):
            SummaryAutomationRepository(connection).reserve_job(
                **_reservation(snapshot)
            )


def test_identity_values_do_not_enter_audit_schema(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'private-identities.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("jobs")
        snapshot, _, _ = _snapshot(connection, session.id)
        SummaryAutomationRepository(connection).reserve_job(**_reservation(snapshot))

        audit_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(summary_job_audits)")
        }
        assert "logical_source_identity" not in audit_columns
        assert "attempt_epoch" not in audit_columns
        assert "source_set_hash" not in audit_columns
