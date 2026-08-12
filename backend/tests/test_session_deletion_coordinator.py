from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from app.domain.models import (
    MemoryAutomationMode,
    MemoryAutoActiveJobSnapshot,
    MemoryDeletionScope,
    MemoryEvidenceExtractorKind,
    MemoryExtractorRoute,
    MemoryGovernorProposal,
    MemoryJobAuditOutcome,
    MemoryJobStatus,
    MemorySource,
    MemoryType,
)
from app.repositories.memories import MemoryRepository
from app.repositories.memory_automation import MemoryAutomationRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import (
    DeletionGenerationSnapshot,
    VersionedMemoryRepository,
)
from app.services.memory_commit_policy import MemoryCommitPolicy
from app.services.memory_gate_b_contract import (
    MEMORY_ALLOWED_AUTO_TYPES_VERSION,
    MEMORY_WRITE_POLICY_VERSION,
    MEMORY_WRITE_PURPOSE,
    MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
)
from app.services.memory_forget_service import MemoryForgetService
from app.services.memory_governor import MemoryGovernor
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.session_deletion_coordinator import SessionDeletionCoordinator
from app.services.versioned_memory_commit import (
    VersionedMemoryCommitRequest,
    VersionedMemoryCommitService,
    WriteAuthoritySnapshot,
)


_NOW = datetime(2026, 7, 20, tzinfo=UTC)
_GOVERNOR_VERSION = "memory-governor-rules-v1"
_SCHEMA_VERSION = "memory-auto-active-schema-v1"


def _seed_session(connection, session_id: str = "session-1") -> dict[str, str]:
    ids = {
        "session": session_id,
        "user_1": f"{session_id}-user-1",
        "assistant_1": f"{session_id}-assistant-1",
        "user_2": f"{session_id}-user-2",
        "assistant_2": f"{session_id}-assistant-2",
        "user_3": f"{session_id}-user-3",
        "assistant_3": f"{session_id}-assistant-3",
        "user_4": f"{session_id}-user-4",
        "assistant_4": f"{session_id}-assistant-4",
    }
    connection.execute(
        "INSERT INTO sessions VALUES (?, 'title', ?, ?)",
        (session_id, _NOW.isoformat(), _NOW.isoformat()),
    )
    connection.executemany(
        "INSERT INTO messages VALUES (?, ?, ?, ?, '{}', ?)",
        [
            (
                message_id,
                session_id,
                "user" if "-user-" in message_id else "assistant",
                "我喜欢乌龙茶。" if "-user-" in message_id else "好的。",
                _NOW.isoformat(),
            )
            for key, message_id in ids.items()
            if key != "session"
        ],
    )
    connection.commit()
    return ids


def _snapshot(
    references: MemorySourceReferenceService,
    ids: dict[str, str],
    *,
    pair: int,
) -> MemoryAutoActiveJobSnapshot:
    return MemoryAutoActiveJobSnapshot(
        reserved_mode=MemoryAutomationMode.AUTO_ACTIVE,
        workflow_version=_SCHEMA_VERSION,
        extractor_route=MemoryExtractorRoute.LOCAL,
        governor_version=_GOVERNOR_VERSION,
        commit_policy_version="memory-commit-policy-v1",
        canonicalization_version="memory-canonicalization-v1",
        allowed_memory_types_version="memory-auto-write-types-v1",
        write_consent_generation=1,
        remote_consent_generation=None,
        remote_authority_fingerprint=None,
        global_deletion_generation=0,
        session_deletion_generation=0,
        type_deletion_generations={},
        source_session_reference_hash=references.session_hash(ids["session"]),
        source_user_message_reference_hash=references.message_hash(ids[f"user_{pair}"]),
        source_assistant_message_reference_hash=references.message_hash(
            ids[f"assistant_{pair}"]
        ),
        turn_completed_at=_NOW,
    )


def _reserve_active(
    connection,
    references: MemorySourceReferenceService,
    ids: dict[str, str],
    *,
    pair: int,
):
    snapshot = _snapshot(references, ids, pair=pair)
    return MemoryAutomationRepository(connection).reserve_job(
        turn_id=ids[f"assistant_{pair}"],
        schema_version=_SCHEMA_VERSION,
        session_id=ids["session"],
        user_message_id=ids[f"user_{pair}"],
        assistant_message_id=ids[f"assistant_{pair}"],
        mode=MemoryAutomationMode.AUTO_ACTIVE,
        extractor_route=MemoryExtractorRoute.LOCAL,
        governor_version=_GOVERNOR_VERSION,
        auto_active_snapshot=snapshot,
        source_session_reference_hash=snapshot.source_session_reference_hash,
        source_user_message_reference_hash=snapshot.source_user_message_reference_hash,
        source_assistant_message_reference_hash=(
            snapshot.source_assistant_message_reference_hash
        ),
    )[0]


def _seed_formal_memory_and_evidence(connection, references, ids):
    memory = MemoryRepository(
        connection,
        source_references=references,
    ).create(
        content="用户喜欢乌龙茶",
        memory_type=MemoryType.PREFERENCE,
        source=MemorySource.MANUAL,
        source_session_id=ids["session"],
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
            'evidence-1', ?, ?, ?, ?, ?, ?, 1, NULL, 'supports', ?,
            'manual', NULL, NULL, 0.9, ?
        )
        """,
        (
            memory.id,
            version.id,
            ids["session"],
            ids["user_1"],
            references.session_hash(ids["session"]),
            references.message_hash(ids["user_1"]),
            _NOW.isoformat(),
            _NOW.isoformat(),
        ),
    )
    connection.commit()
    return memory, version


def _coordinator(connection, references, *, fault_injector=None):
    return SessionDeletionCoordinator(
        connection,
        versioned=VersionedMemoryRepository(connection),
        source_references=references,
        fault_injector=fault_injector,
    )


def test_delete_session_preserves_memories_and_downgrades_provenance_atomically(
    tmp_path: Path,
) -> None:
    references = MemorySourceReferenceService(b"s" * 32)
    with managed_connection(f"sqlite:///{tmp_path / 'delete.db'}") as connection:
        ids = _seed_session(connection)
        memory, version = _seed_formal_memory_and_evidence(connection, references, ids)
        pending = _reserve_active(connection, references, ids, pair=1)
        running = _reserve_active(connection, references, ids, pair=2)
        automation = MemoryAutomationRepository(connection)
        automation.update_job_status(running.id, status=MemoryJobStatus.RUNNING)

        shadow, _ = automation.reserve_job(
            turn_id=ids["assistant_3"],
            schema_version="memory-shadow-schema-v1",
            session_id=ids["session"],
            user_message_id=ids["user_3"],
            assistant_message_id=ids["assistant_3"],
            mode=MemoryAutomationMode.SHADOW_AUTO,
            extractor_route=MemoryExtractorRoute.LOCAL,
            governor_version=_GOVERNOR_VERSION,
        )
        terminal = _reserve_active(connection, references, ids, pair=4)
        automation.complete_job_with_audit(
            terminal.id,
            status=MemoryJobStatus.SUCCEEDED,
            outcome=MemoryJobAuditOutcome.SKIPPED_NO_EXTRACTOR,
            decision_counts={},
            reason_counts={},
            outcome_counts={},
            proposal_count=0,
            accepted_count=0,
            rejected_count=0,
            redaction_count=0,
            provider=None,
            model=None,
            elapsed_ms=None,
            consent_generation=1,
        )
        connection.execute(
            """
            INSERT INTO emotion_analysis_jobs (
                id, scope_id, source_session_id, source_user_message_id,
                source_assistant_message_id, schema_version,
                base_emotion_version, consent_generation, status,
                outcome_reason, created_at, updated_at
            ) VALUES (
                'emotion-job', 'default', ?, ?, ?, 'emotion-analysis-v1',
                0, 1, 'succeeded', 'no_change', ?, ?
            )
            """,
            (
                ids["session"],
                ids["user_1"],
                ids["assistant_1"],
                _NOW.isoformat(),
                _NOW.isoformat(),
            ),
        )
        connection.execute(
            """
            INSERT INTO emotion_analysis_audits VALUES (
                'emotion-audit', 'emotion-job', 'default', 'no_change',
                ?, ?, ?, 'emotion-analysis-v1', 'fake', 'model',
                2, 0, 10, 0, 1, 'no_change', ?
            )
            """,
            (
                ids["session"],
                ids["user_1"],
                ids["assistant_1"],
                _NOW.isoformat(),
            ),
        )
        connection.commit()

        result = _coordinator(connection, references).delete(ids["session"])

        assert result.cancelled_job_ids == (pending.id, running.id)
        assert result.deletion_generation == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE id = ?", (ids["session"],)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (ids["session"],)
        ).fetchone()[0] == 0

        memory_row = connection.execute(
            "SELECT content, status FROM memories WHERE id = ?", (memory.id,)
        ).fetchone()
        assert tuple(memory_row) == ("用户喜欢乌龙茶", "active")
        version_row = connection.execute(
            "SELECT source_session_id, source_session_reference_hash, content "
            "FROM memory_versions WHERE id = ?",
            (version.id,),
        ).fetchone()
        assert tuple(version_row) == (
            None,
            references.session_hash(ids["session"]),
            "用户喜欢乌龙茶",
        )
        evidence = connection.execute(
            "SELECT source_session_id, source_message_id, "
            "source_session_reference_hash, source_message_reference_hash, "
            "source_available, source_deleted_at FROM memory_evidence "
            "WHERE evidence_id = 'evidence-1'"
        ).fetchone()
        assert evidence[0] is None and evidence[1] is None
        assert evidence[2] == references.session_hash(ids["session"])
        assert evidence[3] == references.message_hash(ids["user_1"])
        assert evidence[4] == 0 and evidence[5] is not None

        rows = connection.execute(
            "SELECT id, status, outcome, turn_id, session_id, user_message_id, "
            "assistant_message_id, source_session_reference_hash, "
            "source_user_message_reference_hash, "
            "source_assistant_message_reference_hash "
            "FROM memory_jobs ORDER BY id"
        ).fetchall()
        by_id = {row["id"]: row for row in rows}
        for job in (pending, running):
            row = by_id[job.id]
            assert (row["status"], row["outcome"]) == (
                "cancelled",
                "cancelled_session_deleted",
            )
            assert connection.execute(
                "SELECT COUNT(*) FROM memory_job_audits WHERE job_id = ?",
                (job.id,),
            ).fetchone()[0] == 1
        assert by_id[shadow.id]["status"] == "pending"
        assert by_id[terminal.id]["outcome"] == "skipped_no_extractor"
        for row in rows:
            assert row["turn_id"] not in set(ids.values())
            assert row["session_id"] is None
            assert row["user_message_id"] is None
            assert row["assistant_message_id"] is None
            assert row["source_session_reference_hash"] == references.session_hash(
                ids["session"]
            )
            assert row["source_user_message_reference_hash"] is not None
            assert row["source_assistant_message_reference_hash"] is not None

        cancellation_audits = connection.execute(
            "SELECT decision_counts_json, reason_counts_json, outcome_counts_json, "
            "proposal_count, accepted_count, rejected_count, redaction_count, "
            "provider, model FROM memory_job_audits "
            "WHERE outcome = 'cancelled_session_deleted'"
        ).fetchall()
        assert len(cancellation_audits) == 2
        assert all(tuple(row) == ("{}", "{}", "{}", 0, 0, 0, 0, None, None) for row in cancellation_audits)
        assert connection.execute(
            "SELECT generation FROM memory_deletion_generations "
            "WHERE scope = 'session' AND scope_id = ?",
            (references.session_hash(ids["session"]),),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM emotion_analysis_jobs"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM emotion_analysis_audits"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        retained_values = {
            str(value)
            for table in ("memory_jobs", "memory_write_activities")
            for row in connection.execute(f"SELECT * FROM {table}").fetchall()
            for value in row
        }
        assert not set(ids.values()).intersection(retained_values)

        scoped = MemoryForgetService(
            connection,
            versioned=VersionedMemoryRepository(connection),
            source_references=references,
        ).forget_scope(scope=MemoryDeletionScope.SESSION, scope_id=ids["session"])
        assert scoped.forgotten_memory_ids == (memory.id,)


@pytest.mark.parametrize(
    "checkpoint",
    [
        "generation",
        "jobs",
        "versions",
        "evidence",
        "summaries",
        "sources",
        "messages",
        "session",
    ],
)
def test_delete_session_rolls_back_every_low_level_step(
    tmp_path: Path,
    checkpoint: str,
) -> None:
    references = MemorySourceReferenceService(b"r" * 32)
    with managed_connection(
        f"sqlite:///{tmp_path / f'rollback-{checkpoint}.db'}"
    ) as connection:
        ids = _seed_session(connection)
        _memory, version = _seed_formal_memory_and_evidence(connection, references, ids)
        job = _reserve_active(connection, references, ids, pair=1)

        def fail(name: str) -> None:
            if name == checkpoint:
                raise RuntimeError(f"fault:{checkpoint}")

        with pytest.raises(RuntimeError, match=f"fault:{checkpoint}"):
            _coordinator(connection, references, fault_injector=fail).delete(
                ids["session"]
            )

        assert connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE id = ?", (ids["session"],)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (ids["session"],)
        ).fetchone()[0] == 8
        job_row = connection.execute(
            "SELECT status, outcome, session_id FROM memory_jobs WHERE id = ?",
            (job.id,),
        ).fetchone()
        assert tuple(job_row) == ("pending", None, ids["session"])
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_job_audits WHERE job_id = ?", (job.id,)
        ).fetchone()[0] == 0
        version_row = connection.execute(
            "SELECT source_session_id FROM memory_versions WHERE id = ?",
            (version.id,),
        ).fetchone()
        assert version_row[0] == ids["session"]
        evidence = connection.execute(
            "SELECT source_available, source_session_id, source_message_id "
            "FROM memory_evidence WHERE evidence_id = 'evidence-1'"
        ).fetchone()
        assert tuple(evidence) == (1, ids["session"], ids["user_1"])
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_deletion_generations "
            "WHERE scope = 'session'"
        ).fetchone()[0] == 0


def test_terminal_deleted_session_job_is_safe_for_late_maintenance(tmp_path: Path) -> None:
    references = MemorySourceReferenceService(b"l" * 32)
    with managed_connection(f"sqlite:///{tmp_path / 'late.db'}") as connection:
        ids = _seed_session(connection)
        job = _reserve_active(connection, references, ids, pair=1)
        _coordinator(connection, references).delete(ids["session"])

        retained = MemoryAutomationRepository(connection).require_job(job.id)

        assert retained.status is MemoryJobStatus.CANCELLED
        assert retained.outcome is MemoryJobAuditOutcome.CANCELLED_SESSION_DELETED
        assert retained.session_id is None
        assert retained.user_message_id is None
        assert retained.assistant_message_id is None
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_versions WHERE source_kind = 'automatic'"
        ).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_write_activities").fetchone()[0] == 0


def test_one_way_provenance_backfill_remains_guarded_by_triggers(
    tmp_path: Path,
) -> None:
    references = MemorySourceReferenceService(b"t" * 32)
    with managed_connection(f"sqlite:///{tmp_path / 'triggers.db'}") as connection:
        ids = _seed_session(connection)
        shadow = MemoryAutomationRepository(connection).reserve_job(
            turn_id=ids["assistant_1"],
            schema_version="memory-shadow-schema-v1",
            session_id=ids["session"],
            user_message_id=ids["user_1"],
            assistant_message_id=ids["assistant_1"],
            mode=MemoryAutomationMode.SHADOW_AUTO,
            extractor_route=MemoryExtractorRoute.LOCAL,
            governor_version=_GOVERNOR_VERSION,
        )[0]
        memory, version = _seed_formal_memory_and_evidence(
            connection,
            references,
            ids,
        )
        connection.execute("DROP TRIGGER trg_memory_versions_append_only_update")
        connection.execute(
            "UPDATE memory_versions SET source_session_reference_hash = NULL "
            "WHERE id = ?",
            (version.id,),
        )
        connection.commit()
        from app.repositories.sqlite import init_db

        init_db(connection)
        session_hash = references.session_hash(ids["session"])
        connection.execute(
            "UPDATE memory_versions SET source_session_reference_hash = ? "
            "WHERE id = ?",
            (session_hash, version.id),
        )
        connection.execute(
            "UPDATE memory_jobs SET source_session_reference_hash = ? WHERE id = ?",
            (session_hash, shadow.id),
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE memory_versions SET source_session_reference_hash = 'different' "
                "WHERE id = ?",
                (version.id,),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE memory_jobs SET source_session_reference_hash = 'different' "
                "WHERE id = ?",
                (shadow.id,),
            )
        connection.rollback()
        assert MemoryRepository(connection).require(memory.id).content == "用户喜欢乌龙茶"


def test_stale_commit_after_session_deletion_has_no_memory_side_effects(
    tmp_path: Path,
) -> None:
    references = MemorySourceReferenceService(b"c" * 32)
    with managed_connection(f"sqlite:///{tmp_path / 'stale-commit.db'}") as connection:
        ids = _seed_session(connection)
        job = _reserve_active(connection, references, ids, pair=1)
        proposal = MemoryGovernorProposal(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户喜欢乌龙茶",
            canonical_key_hint=None,
            confidence=0.9,
            source_message_ids=(ids["user_1"],),
        )
        governor_result = MemoryGovernor(
            max_proposals=5,
            max_proposal_characters=300,
            max_total_characters=1000,
        ).evaluate(
            proposal=proposal,
            user_text="我喜欢乌龙茶。",
            user_message_id=ids["user_1"],
            assistant_message_id=ids["assistant_1"],
        )
        connection.execute(
            """
            INSERT INTO memory_write_consents (
                scope_id, status, purpose, policy_version,
                allowed_memory_types_version, allowed_memory_types_json,
                retention_disclosure_version, generation, granted_at,
                created_at, updated_at
            ) VALUES ('default', 'granted', ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                MEMORY_WRITE_PURPOSE,
                MEMORY_WRITE_POLICY_VERSION,
                MEMORY_ALLOWED_AUTO_TYPES_VERSION,
                '["user_fact","preference","long_term_goal","important_event","relationship_event","other"]',
                MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
                _NOW.isoformat(),
                _NOW.isoformat(),
                _NOW.isoformat(),
            ),
        )
        connection.commit()
        request = VersionedMemoryCommitRequest(
            job_id=job.id,
            turn_id=ids["assistant_1"],
            proposal_index=0,
            proposal=proposal,
            governor_result=governor_result,
            session_id=ids["session"],
            user_message_id=ids["user_1"],
            user_text="我喜欢乌龙茶。",
            extractor_kind=MemoryEvidenceExtractorKind.LOCAL,
            provider_identifier=None,
            model_identifier="memory-local-rules-v1",
            authority=WriteAuthoritySnapshot(
                write_consent_generation=1,
                remote_consent_generation=None,
                remote_authority_fingerprint=None,
                turn_completed_at=_NOW,
            ),
            deletion_snapshot=DeletionGenerationSnapshot(
                global_generation=0,
                session_generation=0,
                type_generations={},
            ),
        )
        _coordinator(connection, references).delete(ids["session"])

        result = VersionedMemoryCommitService(
            connection,
            versioned=VersionedMemoryRepository(connection),
            policy=MemoryCommitPolicy(),
            source_references=references,
        ).commit_one(request)

        assert result.outcome.value == "cancelled_session_deleted"
        assert connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_versions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_write_activities").fetchone()[0] == 0
