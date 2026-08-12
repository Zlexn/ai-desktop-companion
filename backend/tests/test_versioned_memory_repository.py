import base64
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.domain.models import (
    MemoryConflictStatus,
    MemoryRecordState,
    MemorySource,
    MemoryStatus,
    MemoryType,
)
from app.repositories.memories import MemoryRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository


_NOW = datetime(2026, 7, 19, tzinfo=UTC)


def _iso(index: int = 0) -> str:
    return (_NOW + timedelta(seconds=index)).isoformat()


def _forged_cursor(kind: str, filters: dict[str, str], key: list[object]) -> str:
    payload = json.dumps(
        {"v": 1, "kind": kind, "filters": filters, "key": key},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _create_memory(
    connection: sqlite3.Connection,
    memory_id: str,
    *,
    status: str = "active",
    source: str = "manual",
) -> None:
    connection.execute(
        """
        INSERT INTO memories (
            id, content, memory_type, source, source_session_id,
            importance, confidence, status, metadata_json, created_at, updated_at
        ) VALUES (?, ?, 'other', ?, NULL, 3, 1.0, ?, '{}', ?, ?)
        """,
        (memory_id, f"content-{memory_id}", source, status, _iso(), _iso()),
    )


def _create_version(
    connection: sqlite3.Connection,
    memory_id: str,
    version_number: int,
    *,
    version_id: str | None = None,
    parent_id: str | None = None,
    operation: str = "create",
    canonical_hash: str | None = None,
) -> str:
    version_id = version_id or f"{memory_id}-v{version_number:03d}"
    connection.execute(
        """
        INSERT INTO memory_versions (
            id, memory_id, version_number, parent_version_id, operation,
            memory_type, subject, content, content_hash, canonical_key_hash,
            subject_key_hash, canonicalization_version, confidence, importance,
            source_kind, source_session_id, source_session_reference_hash,
            writer_policy_version, created_at, redacted_at
        ) VALUES (?, ?, ?, ?, ?, 'other', 'subject', ?, ?, ?, 'subject-hash',
                  'memory-canonicalization-v1', 1.0, 3, 'manual', NULL, NULL,
                  'memory-auto-write-policy-v1', ?, NULL)
        """,
        (
            version_id,
            memory_id,
            version_number,
            parent_id,
            operation,
            f"content-{version_id}",
            f"hash-{version_id}",
            canonical_hash,
            _iso(version_number),
        ),
    )
    return version_id


def _create_state(
    connection: sqlite3.Connection,
    memory_id: str,
    version_id: str,
    version_number: int,
    *,
    state: str = "active",
    canonical_hash: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO memory_record_states (
            memory_id, state, current_version_id, head_version,
            record_generation, canonical_key_hash, subject_key_hash,
            canonicalization_version, source_kind, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 0, ?, 'subject-hash',
                  'memory-canonicalization-v1', 'manual', ?, ?)
        """,
        (memory_id, state, version_id, version_number, canonical_hash, _iso(), _iso()),
    )


def _seed_job(connection: sqlite3.Connection, job_id: str = "job-1") -> None:
    connection.execute(
        """
        INSERT INTO memory_jobs (
            id, turn_id, schema_version, mode, extractor_route, status,
            governor_version, created_at
        ) VALUES (?, ?, 'memory-shadow-schema-v1', 'shadow_auto', 'local',
                  'succeeded', 'memory-governor-rules-v1', ?)
        """,
        (job_id, f"turn-{job_id}", _iso()),
    )


def test_database_rejects_cross_identity_and_non_contiguous_version_links(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'invariants.db'}") as connection:
        _create_memory(connection, "memory-a")
        _create_memory(connection, "memory-b")
        root_a = _create_version(connection, "memory-a", 1)
        _create_version(connection, "memory-b", 1)

        with pytest.raises(sqlite3.IntegrityError):
            _create_version(
                connection,
                "memory-b",
                2,
                parent_id=root_a,
            )
        with pytest.raises(sqlite3.IntegrityError, match="previous version"):
            _create_version(
                connection,
                "memory-a",
                3,
                parent_id=root_a,
            )
        with pytest.raises(sqlite3.IntegrityError):
            _create_state(connection, "memory-b", root_a, 1)


def test_database_rejects_invalid_deleted_head_duplicate_activity_and_open_endpoint(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'guards.db'}") as connection:
        for memory_id in ("memory-a", "memory-b", "memory-c"):
            _create_memory(connection, memory_id)
            version_id = _create_version(connection, memory_id, 1)
            if memory_id == "memory-a":
                with pytest.raises(sqlite3.IntegrityError, match="delete head"):
                    _create_state(
                        connection,
                        memory_id,
                        version_id,
                        1,
                        state="deleted",
                    )
            else:
                _create_state(connection, memory_id, version_id, 1)

        connection.execute(
            """
            INSERT INTO memory_conflicts (
                conflict_id, left_memory_id, right_memory_id, status, created_at
            ) VALUES ('conflict-1', 'memory-a', 'memory-b', 'open', ?)
            """,
            (_iso(),),
        )
        with pytest.raises(sqlite3.IntegrityError, match="open conflict"):
            connection.execute(
                """
                INSERT INTO memory_conflicts (
                    conflict_id, left_memory_id, right_memory_id, status, created_at
                ) VALUES ('conflict-2', 'memory-b', 'memory-c', 'open', ?)
                """,
                (_iso(1),),
            )

        _seed_job(connection)
        activity = (
            "op-1", "job-1", 0, "fingerprint", "turn-job-1", "reject",
            "no_change", 1, "memory-governor-rules-v1",
            "memory-commit-policy-v1", "memory-canonicalization-v1", "local", _iso(),
        )
        connection.execute(
            """
            INSERT INTO memory_write_activities (
                op_id, job_id, proposal_index, proposal_fingerprint, turn_id,
                decision, outcome, write_consent_generation, governor_version,
                commit_policy_version, canonicalization_version, extractor_kind,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            activity,
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memory_write_activities (
                    op_id, job_id, proposal_index, proposal_fingerprint, turn_id,
                    decision, outcome, write_consent_generation, governor_version,
                    commit_policy_version, canonicalization_version, extractor_kind,
                    created_at
                ) VALUES ('op-2', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                activity[1:],
            )


def test_eligibility_keeps_legacy_active_and_excludes_incomplete_conflicted_deleted(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'eligibility.db'}") as connection:
        _create_memory(connection, "legacy-active")
        _create_memory(connection, "legacy-archived", status="archived")
        _create_memory(connection, "legacy-pending", status="pending", source="candidate")

        for memory_id, state in (
            ("v2-active", "active"),
            ("v2-archived", "archived"),
            ("v2-conflicted", "conflicted"),
        ):
            _create_memory(connection, memory_id)
            version_id = _create_version(connection, memory_id, 1, canonical_hash="exact")
            _create_state(
                connection,
                memory_id,
                version_id,
                1,
                state=state,
                canonical_hash="exact",
            )

        _create_memory(connection, "v2-incomplete")
        connection.execute(
            """
            INSERT INTO memory_record_states (
                memory_id, state, current_version_id, head_version,
                record_generation, source_kind, created_at, updated_at
            ) VALUES ('v2-incomplete', 'active', NULL, 0, 0, 'legacy', ?, ?)
            """,
            (_iso(), _iso()),
        )

        eligible = VersionedMemoryRepository(connection).list_eligible_memory_ids()
        assert eligible == ["legacy-active", "v2-active"]

        context_ids = [memory.id for memory in MemoryRepository(connection).list_for_context(20)]
        assert set(context_ids) == {"legacy-active", "v2-active"}
        relevant_ids = [
            memory.id
            for memory in MemoryRepository(connection).list_relevant_for_context(
                "content-v2-conflicted",
                limit=20,
                fallback_limit=3,
            )
        ]
        assert "v2-conflicted" not in relevant_ids


def test_open_conflict_endpoints_are_excluded_from_all_eligible_reads(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'conflict-eligibility.db'}") as connection:
        for memory_id in ("memory-a", "memory-b"):
            _create_memory(connection, memory_id)
            version_id = _create_version(connection, memory_id, 1, canonical_hash="exact")
            _create_state(connection, memory_id, version_id, 1, canonical_hash="exact")
        connection.execute(
            """
            INSERT INTO memory_conflicts (
                conflict_id, left_memory_id, right_memory_id, status, created_at
            ) VALUES ('conflict-1', 'memory-a', 'memory-b', 'open', ?)
            """,
            (_iso(),),
        )

        repository = VersionedMemoryRepository(connection)
        assert repository.list_eligible_memory_ids() == []
        assert repository.list_eligible_exact(
            memory_type=MemoryType.OTHER,
            canonical_key_hash="exact",
        ) == []
        assert MemoryRepository(connection).list_for_context(20) == []


def test_unbootstrapped_legacy_open_conflict_endpoints_are_ineligible(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'legacy-conflict.db'}") as connection:
        _create_memory(connection, "legacy-a")
        _create_memory(connection, "legacy-b")
        connection.execute(
            """
            INSERT INTO memory_conflicts (
                conflict_id, left_memory_id, right_memory_id, status, created_at
            ) VALUES ('conflict-legacy', 'legacy-a', 'legacy-b', 'open', ?)
            """,
            (_iso(),),
        )

        assert VersionedMemoryRepository(connection).list_eligible_memory_ids() == []
        assert MemoryRepository(connection).list_for_context(20) == []
        assert MemoryRepository(connection).list_relevant_for_context(
            "content-legacy-a",
            limit=20,
            fallback_limit=3,
        ) == []


def test_write_transaction_rolls_back_and_rejects_unmanaged_transaction(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'transaction.db'}") as connection:
        repository = VersionedMemoryRepository(connection)
        with pytest.raises(RuntimeError, match="rollback"):
            with repository.write_transaction():
                _create_memory(connection, "rolled-back")
                raise RuntimeError("rollback")
        assert connection.execute(
            "SELECT 1 FROM memories WHERE id = 'rolled-back'"
        ).fetchone() is None

        connection.execute("BEGIN")
        with pytest.raises(RuntimeError, match="unmanaged transaction"):
            with repository.write_transaction():
                pass
        connection.rollback()


def test_controlled_bootstrap_is_idempotent_and_never_bootstraps_candidates(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'bootstrap.db'}") as connection:
        _create_memory(connection, "legacy-active")
        _create_memory(connection, "legacy-archived", status="archived")
        _create_memory(connection, "candidate", status="pending", source="candidate")
        connection.commit()
        repository = VersionedMemoryRepository(connection)

        active = repository.bootstrap_legacy("legacy-active")
        archived = repository.bootstrap_legacy("legacy-archived")
        assert active == repository.bootstrap_legacy("legacy-active")
        assert active.state is MemoryRecordState.ACTIVE
        assert archived.state is MemoryRecordState.ARCHIVED
        assert connection.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_versions").fetchone()[0] == 2
        with pytest.raises(ValueError, match="formal legacy"):
            repository.bootstrap_legacy("candidate")


def test_controlled_bootstrap_is_durable_across_connections(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'durable-bootstrap.db'}"
    with managed_connection(database_url) as connection:
        _create_memory(connection, "legacy-active")
        connection.commit()
        state = VersionedMemoryRepository(connection).bootstrap_legacy("legacy-active")
        assert state.current_version_id is not None

    with managed_connection(database_url) as connection:
        persisted = VersionedMemoryRepository(connection).get_state("legacy-active")
        assert persisted == state
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_versions WHERE memory_id = 'legacy-active'"
        ).fetchone()[0] == 1


def test_version_keyset_traverses_101_rows_without_gaps_and_binds_cursor(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'versions.db'}") as connection:
        _create_memory(connection, "memory-1")
        parent = None
        for number in range(1, 102):
            parent = _create_version(
                connection,
                "memory-1",
                number,
                parent_id=parent,
                operation="create" if number == 1 else "user_edit",
            )
        repository = VersionedMemoryRepository(connection)
        ids: list[str] = []
        cursor = None
        while True:
            page = repository.list_versions("memory-1", limit=17, cursor=cursor)
            ids.extend(item.id for item in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert ids == [f"memory-1-v{number:03d}" for number in range(101, 0, -1)]
        assert len(ids) == len(set(ids)) == 101

        first = repository.list_versions("memory-1", limit=17)
        with pytest.raises(ValueError, match="requested filter"):
            repository.list_versions("other-memory", cursor=first.next_cursor)
        with pytest.raises(ValueError, match="pagination cursor"):
            repository.list_versions("memory-1", cursor="not-a-cursor")
        with pytest.raises(ValueError, match="pagination cursor"):
            repository.list_versions(
                "memory-1",
                cursor=_forged_cursor(
                    "versions",
                    {"memory_id": "memory-1"},
                    ["not-an-integer", "version-id"],
                ),
            )


def test_evidence_and_conflict_keysets_traverse_101_rows_and_bind_filters(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'pages.db'}") as connection:
        connection.execute(
            "INSERT INTO sessions VALUES ('session-1', 'title', ?, ?)",
            (_iso(), _iso()),
        )
        _create_memory(connection, "memory-main")
        version_id = _create_version(connection, "memory-main", 1)
        for number in range(101):
            message_id = f"message-{number:03d}"
            connection.execute(
                "INSERT INTO messages VALUES (?, 'session-1', 'user', 'content', '{}', ?)",
                (message_id, _iso(number)),
            )
            connection.execute(
                """
                INSERT INTO memory_evidence (
                    evidence_id, memory_id, memory_version_id, source_session_id,
                    source_message_id, source_session_reference_hash,
                    source_message_reference_hash, source_available, relation,
                    observed_at, extractor_kind, confidence, created_at
                ) VALUES (?, 'memory-main', ?, 'session-1', ?, 'session-hash', ?,
                          1, 'supports', ?, 'local', 1.0, ?)
                """,
                (
                    f"evidence-{number:03d}",
                    version_id,
                    message_id,
                    f"message-hash-{number}",
                    _iso(number),
                    _iso(number),
                ),
            )

        for number in range(101):
            left = f"left-{number:03d}"
            right = f"right-{number:03d}"
            _create_memory(connection, left)
            _create_memory(connection, right)
            connection.execute(
                """
                INSERT INTO memory_conflicts (
                    conflict_id, left_memory_id, right_memory_id, status,
                    resolution_kind, resolved_at, created_at
                ) VALUES (?, ?, ?, 'resolved', 'dismiss_both', ?, ?)
                """,
                (f"conflict-{number:03d}", left, right, _iso(number), _iso(number)),
            )

        repository = VersionedMemoryRepository(connection)
        evidence_ids: list[str] = []
        cursor = None
        while True:
            page = repository.list_evidence("memory-main", limit=13, cursor=cursor)
            evidence_ids.extend(item.id for item in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert evidence_ids == [f"evidence-{number:03d}" for number in range(100, -1, -1)]
        with pytest.raises(ValueError, match="pagination cursor"):
            repository.list_evidence(
                "memory-main",
                cursor=_forged_cursor(
                    "evidence",
                    {"memory_id": "memory-main"},
                    [{}, []],
                ),
            )

        conflict_ids: list[str] = []
        cursor = None
        while True:
            page = repository.list_conflicts(
                status=MemoryConflictStatus.RESOLVED,
                limit=19,
                cursor=cursor,
            )
            conflict_ids.extend(item.id for item in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert conflict_ids == [f"conflict-{number:03d}" for number in range(100, -1, -1)]
        first = repository.list_conflicts(status=MemoryConflictStatus.RESOLVED, limit=19)
        with pytest.raises(ValueError, match="requested filter"):
            repository.list_conflicts(
                status=MemoryConflictStatus.OPEN,
                cursor=first.next_cursor,
            )
        with pytest.raises(ValueError, match="pagination cursor"):
            repository.list_conflicts(
                status=MemoryConflictStatus.RESOLVED,
                cursor=_forged_cursor(
                    "conflicts",
                    {"status": "resolved"},
                    ["not-a-time", "conflict-id"],
                ),
            )


def test_generation_tombstone_and_activity_reads_are_metadata_only(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'metadata.db'}") as connection:
        repository = VersionedMemoryRepository(connection)
        connection.executemany(
            "INSERT INTO memory_deletion_generations VALUES (?, ?, ?, ?)",
            (
                ("all", "*", 2, _iso()),
                ("session", "session-hash", 3, _iso()),
                ("memory_type", "other", 4, _iso()),
            ),
        )
        _create_memory(connection, "memory-1")
        connection.execute(
            """
            INSERT INTO memory_tombstones (
                tombstone_id, source_memory_id, memory_type,
                canonical_key_hash, subject_key_hash, canonicalization_version,
                delete_generation, reason_code, created_at
            ) VALUES ('tombstone-1', 'memory-1', 'other', 'exact', 'exact-subject',
                      'memory-canonicalization-v1', 4, 'user_forget', ?)
            """,
            (_iso(),),
        )
        connection.execute(
            """
            INSERT INTO memory_tombstones (
                tombstone_id, source_memory_id, memory_type,
                canonical_key_hash, subject_key_hash, canonicalization_version,
                delete_generation, reason_code, created_at, expires_at
            ) VALUES ('expired-subject', 'memory-1', 'other', NULL, 'subject',
                      'memory-canonicalization-v1', 5, 'expired', ?, ?)
            """,
            (_iso(1), (_NOW - timedelta(seconds=1)).isoformat()),
        )
        connection.execute(
            """
            INSERT INTO memory_tombstones (
                tombstone_id, source_memory_id, memory_type,
                canonical_key_hash, subject_key_hash, canonicalization_version,
                delete_generation, reason_code, created_at
            ) VALUES ('active-subject', 'memory-1', 'other', NULL, 'subject-2',
                      'memory-canonicalization-v1', 6, 'subject_forget', ?)
            """,
            (_iso(2),),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memory_tombstones (
                    tombstone_id, source_memory_id, memory_type,
                    canonical_key_hash, subject_key_hash, canonicalization_version,
                    delete_generation, reason_code, created_at
                ) VALUES ('duplicate-exact', 'memory-1', 'other', 'exact', NULL,
                          'memory-canonicalization-v1', 7, 'duplicate', ?)
                """,
                (_iso(3),),
            )
        _seed_job(connection)
        connection.execute(
            """
            INSERT INTO memory_write_activities (
                op_id, job_id, proposal_index, proposal_fingerprint, turn_id,
                decision, outcome, write_consent_generation, governor_version,
                commit_policy_version, canonicalization_version, extractor_kind,
                created_at
            ) VALUES ('op-1', 'job-1', 0, 'fingerprint', 'turn-job-1',
                      'reject', 'no_change', 1, 'memory-governor-rules-v1',
                      'memory-commit-policy-v1', 'memory-canonicalization-v1',
                      'local', ?)
            """,
            (_iso(),),
        )

        snapshot = repository.read_deletion_generations(
            session_reference_hash="session-hash"
        )
        assert snapshot.global_generation == 2
        assert snapshot.session_generation == 3
        assert snapshot.type_generations[MemoryType.OTHER] == 4
        assert snapshot.type_generations[MemoryType.PREFERENCE] == 0
        assert repository.find_tombstone(
            memory_type=MemoryType.OTHER,
            canonical_key_hash="exact",
            subject_key_hash=None,
            canonicalization_version="memory-canonicalization-v1",
        ).tombstone_id == "tombstone-1"
        assert repository.find_tombstone(
            memory_type=MemoryType.OTHER,
            canonical_key_hash="exact",
            subject_key_hash="subject-2",
            canonicalization_version="memory-canonicalization-v1",
            now=_NOW,
        ).matched_by == "exact_canonical_key"
        assert repository.find_tombstone(
            memory_type=MemoryType.OTHER,
            canonical_key_hash=None,
            subject_key_hash="subject",
            canonicalization_version="memory-canonicalization-v1",
            now=_NOW,
        ) is None
        assert repository.find_tombstone(
            memory_type=MemoryType.OTHER,
            canonical_key_hash=None,
            subject_key_hash="subject-2",
            canonicalization_version="memory-canonicalization-v1",
            now=_NOW,
        ).tombstone_id == "active-subject"
        activity = repository.get_activity(
            job_id="job-1",
            proposal_fingerprint="fingerprint",
            commit_policy_version="memory-commit-policy-v1",
        )
        assert activity is not None and activity.op_id == "op-1"
        assert repository.get_activity(
            job_id="job-1",
            proposal_fingerprint="missing",
            commit_policy_version="memory-commit-policy-v1",
        ) is None
