from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from app.core.errors import (
    MemoryConflictRequiresResolutionError,
    MemoryConflictStaleError,
    MemoryNoUndoableAutoOperationError,
)
from app.domain.models import (
    MemoryConflictResolutionKind,
    MemoryEvidenceRelation,
    MemoryEvidenceExtractorKind,
    MemoryGovernorProposal,
    MemorySource,
    MemoryType,
    MemoryVersionOperation,
    MemoryWriteActivityOutcome,
)
from app.repositories.memories import MemoryRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import (
    DeletionGenerationSnapshot,
    VersionedMemoryRepository,
)
from app.services.memory_commit_policy import MemoryCommitPolicy
from app.services.memory_gate_b_contract import (
    MEMORY_ALLOWED_AUTO_TYPES,
    MEMORY_ALLOWED_AUTO_TYPES_VERSION,
    MEMORY_CANONICALIZATION_VERSION,
    MEMORY_COMMIT_POLICY_VERSION,
    MEMORY_WRITE_POLICY_VERSION,
    MEMORY_WRITE_PURPOSE,
    MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
)
from app.services.memory_conflict_resolution import (
    ConflictResolutionPayload,
    MemoryConflictResolutionService,
)
from app.services.memory_forget_service import MemoryForgetService
from app.services.memory_governor import MEMORY_GOVERNOR_VERSION, MemoryGovernor
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.versioned_memory_commit import (
    VersionedMemoryCommitRequest,
    VersionedMemoryCommitService,
    WriteAuthoritySnapshot,
)
from app.services.versioned_memory_mutation import VersionedMemoryMutationService


_NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _seed_authority(connection, *, generation: int = 1) -> None:
    connection.execute(
        """
        INSERT INTO memory_write_consents (
            scope_id, status, purpose, policy_version,
            allowed_memory_types_version, allowed_memory_types_json,
            retention_disclosure_version, generation, granted_at,
            created_at, updated_at
        ) VALUES ('default', 'granted', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            MEMORY_WRITE_PURPOSE,
            MEMORY_WRITE_POLICY_VERSION,
            MEMORY_ALLOWED_AUTO_TYPES_VERSION,
            '["user_fact","preference","long_term_goal","important_event","relationship_event","other"]',
            MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
            generation,
            _NOW.isoformat(),
            _NOW.isoformat(),
            _NOW.isoformat(),
        ),
    )


def _seed_turn(connection, *, job_id: str = "job-1", user_text: str) -> dict[str, str]:
    ids = {
        "session_id": "session-1",
        "user_message_id": "user-1",
        "assistant_message_id": "assistant-1",
        "job_id": job_id,
    }
    connection.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, 'test', ?, ?)",
        (ids["session_id"], _NOW.isoformat(), _NOW.isoformat()),
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
                _NOW.isoformat(),
            ),
            (
                ids["assistant_message_id"],
                ids["session_id"],
                "assistant",
                "好的。",
                _NOW.isoformat(),
            ),
        ),
    )
    connection.execute(
        """
        INSERT INTO memory_jobs (
            id, turn_id, schema_version, session_id, user_message_id,
            assistant_message_id, mode, extractor_route, status,
            attempt_count, governor_version, consent_generation, created_at
        ) VALUES (?, ?, 'memory-shadow-schema-v1', ?, ?, ?,
                  'shadow_auto', 'local', 'pending', 0, ?, NULL, ?)
        """,
        (
            job_id,
            ids["assistant_message_id"],
            ids["session_id"],
            ids["user_message_id"],
            ids["assistant_message_id"],
            MEMORY_GOVERNOR_VERSION,
            _NOW.isoformat(),
        ),
    )
    _seed_authority(connection)
    connection.commit()
    return ids


def _proposal(
    *,
    memory_type: MemoryType,
    subject: str,
    content: str,
    user_message_id: str = "user-1",
) -> MemoryGovernorProposal:
    return MemoryGovernorProposal(
        memory_type=memory_type,
        subject=subject,
        content=content,
        canonical_key_hint=None,
        confidence=0.9,
        source_message_ids=(user_message_id,),
    )


def _request(
    proposal: MemoryGovernorProposal,
    *,
    user_text: str,
    job_id: str = "job-1",
    proposal_index: int = 0,
    user_message_id: str = "user-1",
) -> VersionedMemoryCommitRequest:
    governor_result = MemoryGovernor(
        max_proposals=5,
        max_proposal_characters=300,
        max_total_characters=1000,
    ).evaluate(
        proposal=proposal,
        user_text=user_text,
        user_message_id=user_message_id,
        assistant_message_id="assistant-1",
    )
    return VersionedMemoryCommitRequest(
        job_id=job_id,
        turn_id="assistant-1",
        proposal_index=proposal_index,
        proposal=proposal,
        governor_result=governor_result,
        session_id="session-1",
        user_message_id=user_message_id,
        user_text=user_text,
        extractor_kind=MemoryEvidenceExtractorKind.LOCAL,
        provider_identifier=None,
        model_identifier="memory-local-rules-v1",
        authority=WriteAuthoritySnapshot(
            write_consent_generation=1,
            remote_consent_generation=None,
            remote_authority_fingerprint=None,
        ),
        deletion_snapshot=DeletionGenerationSnapshot(
            global_generation=0,
            session_generation=0,
            type_generations={memory_type: 0 for memory_type in MEMORY_ALLOWED_AUTO_TYPES},
        ),
    )


def _insert_job(
    connection,
    *,
    job_id: str,
    turn_id: str,
    schema_version: str,
    user_message_id: str = "user-1",
) -> None:
    connection.execute(
        """
        INSERT INTO memory_jobs (
            id, turn_id, schema_version, session_id, user_message_id,
            assistant_message_id, mode, extractor_route, status,
            attempt_count, governor_version, consent_generation, created_at
        ) VALUES (?, ?, ?, 'session-1', ?, 'assistant-1', 'shadow_auto',
                  'local', 'pending', 0, ?, NULL, ?)
        """,
        (
            job_id,
            turn_id,
            schema_version,
            user_message_id,
            MEMORY_GOVERNOR_VERSION,
            _NOW.isoformat(),
        ),
    )


def _service(connection):
    return VersionedMemoryCommitService(
        connection,
        versioned=VersionedMemoryRepository(connection),
        policy=MemoryCommitPolicy(),
        source_references=MemorySourceReferenceService(b"r" * 32),
    )


def _resolution_service(connection):
    references = MemorySourceReferenceService(b"r" * 32)
    versioned = VersionedMemoryRepository(connection)
    return MemoryConflictResolutionService(
        connection,
        versioned=versioned,
        memories=MemoryRepository(connection, source_references=references),
        forget=MemoryForgetService(
            connection,
            versioned=versioned,
            source_references=references,
        ),
        source_references=references,
    )


def test_commit_create_writes_projection_version_state_evidence_and_activity(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'create.db'}") as connection:
        _seed_turn(connection, user_text="我长期喜欢晨间散步。")
        request = _request(
            _proposal(
                memory_type=MemoryType.PREFERENCE,
                subject="晨间活动偏好",
                content="用户喜欢晨间散步",
            ),
            user_text="我长期喜欢晨间散步。",
        )

        result = _service(connection).commit_one(request)

        state = VersionedMemoryRepository(connection).get_state(result.memory_id)
        version = VersionedMemoryRepository(connection).get_current_version(result.memory_id)
        evidence = VersionedMemoryRepository(connection).list_evidence(
            result.memory_id,
            limit=10,
        ).items
        assert result.outcome is MemoryWriteActivityOutcome.COMMITTED_CREATE
        assert state is not None and state.head_version == 1
        assert state.canonical_key_hash is not None
        assert version is not None and version.operation is MemoryVersionOperation.CREATE
        assert version.subject == "晨间活动偏好"
        assert version.canonical_subject_code is None
        assert len(evidence) == 1
        assert evidence[0].relation is MemoryEvidenceRelation.SUPPORTS
        assert evidence[0].source_session_reference_hash != "session-1"
        assert evidence[0].source_message_reference_hash != "user-1"
        assert VersionedMemoryRepository(connection).get_activity(
            job_id="job-1",
            proposal_fingerprint=result.proposal_fingerprint,
            commit_policy_version=MEMORY_COMMIT_POLICY_VERSION,
        ) is not None
        summary = MemoryRepository(connection).require(result.memory_id)
        assert summary.v2_state is not None and summary.v2_state.value == "active"
        assert summary.v2_source_kind is not None
        assert summary.v2_source_kind.value == "automatic"
        assert summary.version_count == 1
        assert summary.evidence_count == 1
        assert summary.has_open_conflict is False
        assert summary.can_undo_latest_auto is True

        undone = _resolution_service(connection).undo_latest_auto(result.memory_id)
        assert undone.action == "forgotten_create"
        deleted = connection.execute(
            "SELECT content, status, metadata_json FROM memories WHERE id = ?",
            (result.memory_id,),
        ).fetchone()
        assert deleted["content"] == ""
        assert deleted["status"] == "archived"
        assert "用户喜欢晨间散步" not in deleted["metadata_json"]
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_tombstones WHERE source_memory_id = ?",
            (result.memory_id,),
        ).fetchone()[0] >= 1
        undo_audit = connection.execute(
            "SELECT metadata_json FROM memory_audit_events "
            "WHERE event_type = 'auto_change_undone'"
        ).fetchone()
        assert undo_audit is not None
        assert result.op_id in undo_audit["metadata_json"]
        assert "用户喜欢晨间散步" not in undo_audit["metadata_json"]
        with pytest.raises(MemoryNoUndoableAutoOperationError):
            _resolution_service(connection).undo_latest_auto(result.memory_id)


def test_undo_auto_create_rejects_after_user_edit_without_side_effects(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'create-user-edit.db'}") as connection:
        _seed_turn(connection, user_text="我长期喜欢晨间散步。")
        created = _service(connection).commit_one(
            _request(
                _proposal(
                    memory_type=MemoryType.PREFERENCE,
                    subject="晨间活动偏好",
                    content="用户喜欢晨间散步",
                ),
                user_text="我长期喜欢晨间散步。",
            )
        )
        references = MemorySourceReferenceService(b"r" * 32)
        versioned = VersionedMemoryRepository(connection)
        mutations = VersionedMemoryMutationService(
            connection,
            memories=MemoryRepository(connection, source_references=references),
            versioned=versioned,
            source_references=references,
        )
        edited, _ = mutations.update(
            created.memory_id,
            content="用户改为喜欢晚间散步",
            memory_type=None,
            importance=None,
            confidence=None,
            metadata=None,
        )
        before_versions = versioned.list_versions(created.memory_id, limit=10).items
        before_evidence = versioned.list_evidence(created.memory_id, limit=10).items
        before_tombstones = connection.execute(
            "SELECT COUNT(*) FROM memory_tombstones WHERE source_memory_id = ?",
            (created.memory_id,),
        ).fetchone()[0]

        summary = MemoryRepository(connection).require(created.memory_id)
        assert summary.v2_source_kind is not None
        assert summary.v2_source_kind.value == "user_edit"
        assert summary.can_undo_latest_auto is False
        with pytest.raises(MemoryConflictStaleError):
            _resolution_service(connection).undo_latest_auto(created.memory_id)

        preserved = MemoryRepository(connection).require(created.memory_id)
        head = versioned.get_current_version(created.memory_id)
        assert preserved.content == edited.content == "用户改为喜欢晚间散步"
        assert head is not None and head.operation is MemoryVersionOperation.USER_EDIT
        assert versioned.list_versions(created.memory_id, limit=10).items == before_versions
        assert versioned.list_evidence(created.memory_id, limit=10).items == before_evidence
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_tombstones WHERE source_memory_id = ?",
            (created.memory_id,),
        ).fetchone()[0] == before_tombstones
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_audit_events "
            "WHERE event_type = 'auto_change_undone' AND memory_id = ?",
            (created.memory_id,),
        ).fetchone()[0] == 0


def test_commit_support_adds_evidence_without_new_version(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'support.db'}") as connection:
        _seed_turn(connection, user_text="我还是喜欢无糖茶。")
        initial = _request(
            _proposal(
                memory_type=MemoryType.PREFERENCE,
                subject="饮品偏好",
                content="用户喜欢无糖茶",
            ),
            user_text="我还是喜欢无糖茶。",
            job_id="seed-job",
        )
        connection.execute(
            "UPDATE memory_jobs SET id = 'seed-job' WHERE id = 'job-1'"
        )
        connection.commit()
        service = _service(connection)
        seeded = service.commit_one(initial)
        connection.execute(
            """
            INSERT INTO messages (
                id, session_id, role, content, metadata_json, created_at
            ) VALUES ('user-2', 'session-1', 'user', ?, '{}', ?)
            """,
            ("我还是喜欢无糖茶。", _NOW.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO memory_jobs (
                id, turn_id, schema_version, session_id, user_message_id,
                assistant_message_id, mode, extractor_route, status,
                attempt_count, governor_version, consent_generation, created_at
            ) VALUES ('job-1', 'turn-2', 'memory-shadow-schema-v2',
                      'session-1', 'user-2', 'assistant-1', 'shadow_auto',
                      'local', 'pending', 0, ?, NULL, ?)
            """,
            (MEMORY_GOVERNOR_VERSION, _NOW.isoformat()),
        )
        connection.commit()

        support_proposal = _proposal(
            memory_type=initial.proposal.memory_type,
            subject=initial.proposal.subject,
            content=initial.proposal.content,
            user_message_id="user-2",
        )
        result = service.commit_one(
            _request(
                support_proposal,
                user_text="我还是喜欢无糖茶。",
                user_message_id="user-2",
            )
        )

        versions = VersionedMemoryRepository(connection).list_versions(
            seeded.memory_id,
            limit=10,
        ).items
        evidence = VersionedMemoryRepository(connection).list_evidence(
            seeded.memory_id,
            limit=10,
        ).items
        assert result.outcome is MemoryWriteActivityOutcome.COMMITTED_SUPPORT
        assert len(versions) == 1
        assert len(evidence) == 2
        assert result.previous_version_id == result.result_version_id
        support_evidence = next(
            item for item in evidence if item.source_message_id == "user-2"
        )
        summary = MemoryRepository(connection).require(seeded.memory_id)
        assert summary.version_count == 1
        assert summary.evidence_count == 2
        assert summary.can_undo_latest_auto is True

        undone = _resolution_service(connection).undo_latest_auto(seeded.memory_id)
        assert undone.action == "retracted_support"
        summary_after_undo = MemoryRepository(connection).require(seeded.memory_id)
        assert summary_after_undo.evidence_count == 2
        assert summary_after_undo.can_undo_latest_auto is False
        retractions = connection.execute(
            "SELECT evidence_id, reason_code FROM memory_evidence_retractions"
        ).fetchall()
        assert len(retractions) == 1
        assert retractions[0]["evidence_id"] == support_evidence.id
        assert retractions[0]["reason_code"] == "user_undo_auto_support"
        touched = VersionedMemoryRepository(connection).get_state(seeded.memory_id)
        assert touched is not None and touched.record_generation == 2
        with pytest.raises(MemoryNoUndoableAutoOperationError):
            _resolution_service(connection).undo_latest_auto(seeded.memory_id)


def test_commit_supersede_and_conflict_write_correct_evidence_directions(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'decisions.db'}") as connection:
        ids = _seed_turn(connection, user_text="我住在山城。")
        service = _service(connection)
        old = service.commit_one(
            _request(
                _proposal(
                    memory_type=MemoryType.USER_FACT,
                    subject="居住地",
                    content="用户住在山城",
                ),
                user_text="我住在山城。",
            )
        )
        connection.execute("DELETE FROM memory_write_activities")
        connection.execute("DELETE FROM memory_jobs")
        connection.execute(
            """
            INSERT INTO memory_jobs (
                id, turn_id, schema_version, session_id, user_message_id,
                assistant_message_id, mode, extractor_route, status,
                attempt_count, governor_version, consent_generation, created_at
            ) VALUES ('job-2', 'turn-2', 'memory-shadow-schema-v2', ?, ?, ?,
                      'shadow_auto', 'local', 'pending', 0, ?, NULL, ?)
            """,
            (
                ids["session_id"], ids["user_message_id"],
                ids["assistant_message_id"], MEMORY_GOVERNOR_VERSION,
                _NOW.isoformat(),
            ),
        )
        connection.commit()
        supersede = service.commit_one(
            _request(
                _proposal(
                    memory_type=MemoryType.USER_FACT,
                    subject="居住地",
                    content="用户住在海边城市",
                ),
                user_text="更正一下，我现在住在海边城市。",
                job_id="job-2",
            )
        )

        versions = VersionedMemoryRepository(connection).list_versions(
            old.memory_id,
            limit=10,
        ).items
        evidence = VersionedMemoryRepository(connection).list_evidence(
            old.memory_id,
            limit=10,
        ).items
        assert supersede.outcome is MemoryWriteActivityOutcome.COMMITTED_SUPERSEDE
        assert versions[0].operation is MemoryVersionOperation.AUTO_SUPERSEDE
        assert versions[0].canonical_subject_code is None
        assert {item.relation for item in evidence} >= {
            MemoryEvidenceRelation.CORRECTS,
            MemoryEvidenceRelation.SUPPORTS,
        }
        summary = MemoryRepository(connection).require(old.memory_id)
        assert summary.source.value == "automatic"
        assert summary.v2_source_kind is not None
        assert summary.v2_source_kind.value == "automatic"
        assert summary.version_count == 2
        assert summary.evidence_count == 3
        assert summary.can_undo_latest_auto is True

        undone = _resolution_service(connection).undo_latest_auto(old.memory_id)
        assert undone.action == "reverted_supersede"
        assert undone.memory is not None
        assert undone.memory.content == "用户住在山城"
        head = VersionedMemoryRepository(connection).get_current_version(old.memory_id)
        state = VersionedMemoryRepository(connection).get_state(old.memory_id)
        assert head is not None
        assert state is not None
        assert head.operation is MemoryVersionOperation.USER_REVERT
        assert state.canonical_key_hash == head.canonical_key_hash
        assert state.subject_key_hash == head.subject_key_hash
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_tombstones WHERE reason_code = "
            "'user_undo_auto_supersede'"
        ).fetchone()[0] == 1
        with pytest.raises(MemoryNoUndoableAutoOperationError):
            _resolution_service(connection).undo_latest_auto(old.memory_id)


def test_commit_bootstraps_legacy_before_exact_selection(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'legacy.db'}") as connection:
        _seed_turn(connection, user_text="我还是喜欢无糖茶。")
        canonical = __import__(
            "app.services.memory_commit_policy",
            fromlist=["canonicalize_memory_v1"],
        ).canonicalize_memory_v1(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户喜欢无糖茶",
        )
        connection.execute(
            """
            INSERT INTO memories (
                id, content, memory_type, source, source_session_id,
                importance, confidence, status, metadata_json,
                created_at, updated_at
            ) VALUES ('legacy', '用户喜欢无糖茶', 'preference', 'manual',
                      NULL, 3, 1.0, 'active', '{}', ?, ?)
            """,
            (_NOW.isoformat(), _NOW.isoformat()),
        )
        connection.commit()
        proposal = _proposal(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户喜欢无糖茶",
        )

        result = _service(connection).commit_one(
            _request(proposal, user_text="我还是喜欢无糖茶。")
        )

        assert result.outcome is MemoryWriteActivityOutcome.COMMITTED_SUPPORT
        legacy_state = VersionedMemoryRepository(connection).get_state("legacy")
        assert legacy_state is not None
        assert legacy_state.canonical_key_hash is None
        assert result.memory_id == "legacy"
        assert canonical.canonical_key_hash is not None


def test_commit_conflict_creates_candidate_pair_and_evidence_directions(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'conflict.db'}") as connection:
        _seed_turn(connection, user_text="我喜欢咖啡。")
        service = _service(connection)
        original = service.commit_one(
            _request(
                _proposal(
                    memory_type=MemoryType.PREFERENCE,
                    subject="饮品偏好",
                    content="用户喜欢咖啡",
                ),
                user_text="我喜欢咖啡。",
            )
        )
        connection.execute(
            """
            INSERT INTO messages (
                id, session_id, role, content, metadata_json, created_at
            ) VALUES ('user-2', 'session-1', 'user', '我不喜欢咖啡。', '{}', ?)
            """,
            (_NOW.isoformat(),),
        )
        _insert_job(
            connection,
            job_id="job-2",
            turn_id="turn-2",
            schema_version="memory-shadow-schema-v2",
            user_message_id="user-2",
        )
        connection.commit()
        proposal = _proposal(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户不喜欢咖啡",
            user_message_id="user-2",
        )

        result = service.commit_one(
            _request(
                proposal,
                user_text="我不喜欢咖啡。",
                job_id="job-2",
                user_message_id="user-2",
            )
        )

        assert result.outcome is MemoryWriteActivityOutcome.CONFLICT_RECORDED
        candidate_state = VersionedMemoryRepository(connection).get_state(result.memory_id)
        assert candidate_state is not None
        assert candidate_state.state.value == "conflicted"
        candidate_version = VersionedMemoryRepository(connection).get_current_version(
            result.memory_id
        )
        assert candidate_version is not None
        assert candidate_version.operation is MemoryVersionOperation.CONFLICT_CANDIDATE
        conflict = connection.execute(
            "SELECT * FROM memory_conflicts WHERE conflict_id = ?",
            (result.conflict_id,),
        ).fetchone()
        assert conflict is not None
        assert {conflict["left_memory_id"], conflict["right_memory_id"]} == {
            original.memory_id,
            result.memory_id,
        }
        evidence = connection.execute(
            "SELECT memory_id, relation FROM memory_evidence WHERE source_message_id = 'user-2'"
        ).fetchall()
        assert {(row["memory_id"], row["relation"]) for row in evidence} == {
            (original.memory_id, "contradicts"),
            (result.memory_id, "supports"),
        }
        assert VersionedMemoryRepository(connection).list_eligible_memory_ids() == []

        with pytest.raises(MemoryConflictRequiresResolutionError):
            _resolution_service(connection).undo_latest_auto(original.memory_id)
        mutations = VersionedMemoryMutationService(
            connection,
            memories=MemoryRepository(
                connection,
                source_references=MemorySourceReferenceService(b"r" * 32),
            ),
            versioned=VersionedMemoryRepository(connection),
            source_references=MemorySourceReferenceService(b"r" * 32),
        )
        with pytest.raises(MemoryConflictRequiresResolutionError):
            mutations.archive(original.memory_id)

        resolution = _resolution_service(connection).resolve(
            result.conflict_id,
            ConflictResolutionPayload(
                kind=MemoryConflictResolutionKind.CHOOSE_LEFT,
            ),
        )
        assert resolution.resolved_memory is not None
        expected_left_content = (
            "用户喜欢咖啡"
            if conflict["left_memory_id"] == original.memory_id
            else "用户不喜欢咖啡"
        )
        assert resolution.resolved_memory.content == expected_left_content


def test_commit_authority_and_deletion_gates_are_activity_only(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'gates.db'}") as connection:
        _seed_turn(connection, user_text="我喜欢红茶。")
        proposal = _proposal(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户喜欢红茶",
        )
        connection.execute(
            "UPDATE memory_write_consents SET status = 'revoked', generation = 2"
        )
        connection.commit()

        no_consent = _service(connection).commit_one(
            _request(proposal, user_text="我喜欢红茶。")
        )

        assert no_consent.outcome is MemoryWriteActivityOutcome.SKIPPED_NO_WRITE_CONSENT
        assert connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_versions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0] == 0

    with managed_connection(f"sqlite:///{tmp_path / 'deletion-gate.db'}") as connection:
        _seed_turn(connection, user_text="我喜欢红茶。")
        connection.execute(
            """
            INSERT INTO memory_deletion_generations (
                scope, scope_id, generation, updated_at
            ) VALUES ('all', '*', 1, ?)
            """,
            (_NOW.isoformat(),),
        )
        connection.commit()

        deleted = _service(connection).commit_one(
            _request(proposal, user_text="我喜欢红茶.")
        )

        assert deleted.outcome is MemoryWriteActivityOutcome.SKIPPED_DELETION_BARRIER
        assert connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0


def test_pre_extraction_target_snapshot_rejects_newer_user_edit(
    tmp_path: Path,
) -> None:
    with managed_connection(
        f"sqlite:///{tmp_path / 'pre-extraction-stale.db'}"
    ) as connection:
        _seed_turn(connection, user_text="更正一下，我现在住在海边城市。")
        references = MemorySourceReferenceService(b"r" * 32)
        repository = MemoryRepository(
            connection,
            source_references=references,
        )
        memory = repository.create(
            content="用户住在山城",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id="session-1",
            importance=3,
            confidence=0.9,
        )[0]
        versioned = VersionedMemoryRepository(connection)
        baseline = versioned.list_commit_targets()
        assert len(baseline) == 1 and baseline[0].memory_id == memory.id
        repository.update(memory.id, content="用户住在森林城市")
        request = _request(
            _proposal(
                memory_type=MemoryType.USER_FACT,
                subject="居住地",
                content="用户住在海边城市",
            ),
            user_text="更正一下，我现在住在海边城市。",
        )
        request = replace(request, expected_targets=tuple(baseline))

        result = _service(connection).commit_one(request)

        current = repository.require(memory.id)
        assert result.outcome is MemoryWriteActivityOutcome.STALE_HEAD
        assert current.content == "用户住在森林城市"
        assert versioned.get_state(memory.id).head_version == 2
        assert len(versioned.list_versions(memory.id, limit=10).items) == 2


def test_zero_row_cas_rolls_back_and_records_stale_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'stale.db'}") as connection:
        _seed_turn(connection, user_text="我喜欢红茶。")
        service = _service(connection)
        seeded = service.commit_one(
            _request(
                _proposal(
                    memory_type=MemoryType.PREFERENCE,
                    subject="饮品偏好",
                    content="用户喜欢红茶",
                ),
                user_text="我喜欢红茶。",
            )
        )
        connection.execute(
            """
            INSERT INTO messages (
                id, session_id, role, content, metadata_json, created_at
            ) VALUES ('user-2', 'session-1', 'user', '我还是喜欢红茶。', '{}', ?)
            """,
            (_NOW.isoformat(),),
        )
        _insert_job(
            connection,
            job_id="job-2",
            turn_id="turn-2",
            schema_version="memory-shadow-schema-v2",
            user_message_id="user-2",
        )
        connection.commit()
        monkeypatch.setattr(
            service._versioned,
            "guarded_touch_target",
            lambda _target: False,
        )
        proposal = _proposal(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户喜欢红茶",
            user_message_id="user-2",
        )

        result = service.commit_one(
            _request(
                proposal,
                user_text="我还是喜欢红茶。",
                job_id="job-2",
                user_message_id="user-2",
            )
        )

        assert result.outcome is MemoryWriteActivityOutcome.STALE_HEAD
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_evidence WHERE source_message_id = 'user-2'"
        ).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_versions").fetchone()[0] == 1
        assert VersionedMemoryRepository(connection).get_state(
            seeded.memory_id
        ).record_generation == 0


def test_busy_retries_transaction_without_provider_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'retry.db'}") as connection:
        _seed_turn(connection, user_text="我喜欢红茶。")
        service = _service(connection)
        original = service._commit_attempt
        calls = 0

        def fail_once(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise sqlite3.OperationalError("database is locked")
            return original(*args, **kwargs)

        monkeypatch.setattr(service, "_commit_attempt", fail_once)
        result = service.commit_one(
            _request(
                _proposal(
                    memory_type=MemoryType.PREFERENCE,
                    subject="饮品偏好",
                    content="用户喜欢红茶",
                ),
                user_text="我喜欢红茶。",
            )
        )

        assert calls == 2
        assert result.semantic_attempts == 2
        assert result.outcome is MemoryWriteActivityOutcome.COMMITTED_CREATE
        assert not hasattr(service, "provider")


def test_duplicate_operation_is_idempotent_and_ignores_proposal_index(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'duplicate.db'}") as connection:
        _seed_turn(connection, user_text="我喜欢红茶。")
        proposal = _proposal(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户喜欢红茶",
        )
        service = _service(connection)
        first = service.commit_one(_request(proposal, user_text="我喜欢红茶。"))
        second = service.commit_one(
            _request(proposal, user_text="我喜欢红茶。", proposal_index=9)
        )

        assert second.outcome is MemoryWriteActivityOutcome.DUPLICATE_OP
        assert second.op_id == first.op_id
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_write_activities"
        ).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM memory_versions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0] == 1


def test_commit_rolls_back_all_business_writes_when_activity_insert_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'rollback.db'}") as connection:
        _seed_turn(connection, user_text="我喜欢红茶。")
        repository = VersionedMemoryRepository(connection)
        service = VersionedMemoryCommitService(
            connection,
            versioned=repository,
            policy=MemoryCommitPolicy(),
            source_references=MemorySourceReferenceService(b"r" * 32),
        )
        monkeypatch.setattr(
            repository,
            "insert_commit_activity",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("injected")),
        )

        with pytest.raises(RuntimeError, match="injected"):
            service.commit_one(
                _request(
                    _proposal(
                        memory_type=MemoryType.PREFERENCE,
                        subject="饮品偏好",
                        content="用户喜欢红茶",
                    ),
                    user_text="我喜欢红茶。",
                )
            )

        for table in (
            "memories",
            "memory_versions",
            "memory_record_states",
            "memory_evidence",
            "memory_write_activities",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
