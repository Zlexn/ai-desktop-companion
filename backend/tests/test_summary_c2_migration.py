from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.domain.session_summary import (
    SummaryPayloadState,
    SummaryProvenanceState,
    SummaryRecordState,
)
from app.repositories.sqlite import connect, init_db
from app.repositories.summary_migration import migrate_gate_c2
from app.services.session_summary_contract import (
    SUMMARY_INJECTION_SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
)


MAX_SUMMARY_OUTPUT_CHARACTERS = 8_000


def test_summary_record_state_exposes_bounded_source_metadata_without_payload() -> None:
    fields = set(SummaryRecordState.__dataclass_fields__)
    assert fields == {
        "payload_state",
        "provenance_state",
        "source_message_count",
        "source_turn_count",
        "source_started_at",
        "source_ended_at",
        "replaces_summary_id",
    }
    state = SummaryRecordState(
        payload_state=SummaryPayloadState.REDACTED,
        provenance_state=SummaryProvenanceState.LEGACY_UNVERIFIED,
        source_message_count=0,
        source_turn_count=0,
        source_started_at=None,
        source_ended_at=None,
        replaces_summary_id=None,
    )
    assert state.payload_state is SummaryPayloadState.REDACTED


LEGACY_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE TABLE session_summaries (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('manual', 'generated')),
    covered_message_start_id TEXT,
    covered_message_end_id TEXT,
    message_count INTEGER NOT NULL CHECK (message_count >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    observed_memory_summary_barrier INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (covered_message_start_id) REFERENCES messages(id) ON DELETE SET NULL,
    FOREIGN KEY (covered_message_end_id) REFERENCES messages(id) ON DELETE SET NULL
);
CREATE TABLE memory_summary_barrier (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    generation INTEGER NOT NULL CHECK (generation >= 0)
);
CREATE TABLE memory_summary_source_exclusions (
    source_message_id TEXT PRIMARY KEY,
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL
);
INSERT INTO memory_summary_barrier VALUES (1, 0);
"""


def _legacy_connection(tmp_path: Path) -> sqlite3.Connection:
    path = tmp_path / "legacy-c2.db"
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(LEGACY_SCHEMA)
    return connection


def _session(connection: sqlite3.Connection, session_id: str = "session-1") -> None:
    connection.execute(
        "INSERT INTO sessions VALUES (?, 'legacy', '2026-07-01T00:00:00+00:00', '2026-07-01T00:00:00+00:00')",
        (session_id,),
    )


def _message(
    connection: sqlite3.Connection,
    message_id: str,
    role: str,
    order: int,
    *,
    session_id: str = "session-1",
    content: str | None = None,
) -> None:
    connection.execute(
        "INSERT INTO messages VALUES (?, ?, ?, ?, '{}', ?)",
        (
            message_id,
            session_id,
            role,
            content or message_id,
            f"2026-07-01T00:00:{order:02d}+00:00",
        ),
    )


def _summary(
    connection: sqlite3.Connection,
    summary_id: str,
    text: str,
    start_id: str | None,
    end_id: str | None,
    count: int,
    *,
    source: str = "generated",
    barrier: int = 0,
    metadata_json: str = "{}",
) -> None:
    connection.execute(
        """
        INSERT INTO session_summaries (
            id, session_id, summary_text, source, covered_message_start_id,
            covered_message_end_id, message_count, metadata_json, created_at,
            updated_at, observed_memory_summary_barrier
        ) VALUES (?, 'session-1', ?, ?, ?, ?, ?, ?,
                  '2026-07-01T00:01:00+00:00',
                  '2026-07-01T00:01:00+00:00', ?)
        """,
        (
            summary_id,
            text,
            source,
            start_id,
            end_id,
            count,
            metadata_json,
            barrier,
        ),
    )


def test_fresh_database_contains_gate_c2_schema_and_direct_constraints(
    tmp_path: Path,
) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'fresh.db'}")
    try:
        init_db(connection)
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "chat_turns",
            "session_summary_sources",
            "summary_processing_consents",
            "summary_injection_consents",
            "summary_authority_audits",
            "summary_jobs",
            "summary_job_sources",
            "summary_job_audits",
            "summary_source_suppressions",
            "summary_suppression_audits",
            "summary_payload_audits",
        } <= tables
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(summary_injection_consents)"
            )
        }
        assert "max_fragment_characters" in columns
        suppression_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(summary_source_suppressions)"
            )
        }
        assert "authorized_summary_id" in suppression_columns
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' "
            "AND name='trg_summary_suppression_state_shape_update'"
        ).fetchone() is not None

        _session(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO session_summaries (
                    id, session_id, summary_text, source, message_count,
                    metadata_json, created_at, updated_at,
                    observed_memory_summary_barrier, payload_state,
                    provenance_state
                ) VALUES ('bad-redacted', 'session-1', 'must clear', 'manual',
                          0, '{}', 'now', 'now', 0, 'redacted',
                          'legacy_unverified')
                """
            )
        connection.rollback()
    finally:
        connection.close()


def test_rerun_drops_obsolete_exact_summary_blocking_trigger(
    tmp_path: Path,
) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'obsolete-trigger.db'}")
    try:
        init_db(connection)
        connection.execute(
            """
            CREATE TRIGGER trg_summary_exact_generated_requires_atomic_repository
            BEFORE INSERT ON session_summaries
            WHEN NEW.source='generated' AND NEW.provenance_state='exact'
            BEGIN
                SELECT RAISE(ABORT, 'obsolete exact summary blocker');
            END
            """
        )
        connection.commit()

        init_db(connection)

        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' "
            "AND name='trg_summary_exact_generated_requires_atomic_repository'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' "
            "AND name='trg_summary_exact_generated_requires_atomic_repository_v3'"
        ).fetchone() is not None
    finally:
        connection.close()


def test_rerun_adds_strict_suppression_insert_trigger_to_old_c2_database(
    tmp_path: Path,
) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'old-suppression-trigger.db'}")
    try:
        init_db(connection)
        connection.execute(
            "DROP TRIGGER trg_summary_suppression_state_shape_insert_v2"
        )
        connection.commit()

        init_db(connection)

        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' "
            "AND name='trg_summary_suppression_state_shape_insert_v2'"
        ).fetchone() is not None
        _session(connection)
        with pytest.raises(
            sqlite3.IntegrityError,
            match="state invariant",
        ):
            connection.execute(
                """
                INSERT INTO summary_source_suppressions (
                    session_id, source_set_hash, generation, state,
                    rebuild_permit_id, reason_code, created_at, updated_at
                ) VALUES (
                    'session-1', 'source-hash', 1, 'rebuild_authorized',
                    'forged-permit', 'bypass', 'now', 'now'
                )
                """
            )
        connection.rollback()
    finally:
        connection.close()


def test_migration_does_not_guess_across_ambiguous_legacy_sequences(
    tmp_path: Path,
) -> None:
    connection = _legacy_connection(tmp_path)
    try:
        _session(connection)
        _message(connection, "u1", "user", 1)
        _message(connection, "u2", "user", 2)
        _message(connection, "a2", "assistant", 3)
        _message(connection, "a3", "assistant", 4)
        _summary(connection, "ambiguous", "AMBIGUOUS_PAYLOAD", "u2", "a2", 2)
        connection.commit()

        connection.execute("BEGIN")
        migrate_gate_c2(connection)
        connection.commit()

        assert connection.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 0
        row = connection.execute(
            "SELECT summary_text, payload_state, provenance_state "
            "FROM session_summaries WHERE id='ambiguous'"
        ).fetchone()
        assert row is not None
        assert tuple(row) == (None, "redacted", "legacy_unverified")
    finally:
        connection.close()


def test_migration_quarantines_corrupt_and_oversized_payloads(tmp_path: Path) -> None:
    connection = _legacy_connection(tmp_path)
    try:
        _session(connection)
        _message(connection, "u1", "user", 1)
        _message(connection, "a1", "assistant", 2)
        _summary(connection, "empty", "   ", "u1", "a1", 2)
        _summary(
            connection,
            "oversized",
            "X" * (MAX_SUMMARY_OUTPUT_CHARACTERS + 1),
            "u1",
            "a1",
            2,
        )
        connection.commit()

        connection.execute("BEGIN")
        migrate_gate_c2(connection)
        connection.commit()

        rows = connection.execute(
            "SELECT id, summary_text, payload_state, redaction_reason_code "
            "FROM session_summaries ORDER BY id"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("empty", None, "quarantined", "migration_corrupt_payload"),
            (
                "oversized",
                None,
                "quarantined",
                "migration_oversized_payload",
            ),
        ]
        audits = connection.execute(
            "SELECT summary_id, action, payload_state FROM summary_payload_audits "
            "ORDER BY summary_id"
        ).fetchall()
        assert [tuple(row) for row in audits] == [
            ("empty", "quarantined", "quarantined"),
            ("oversized", "quarantined", "quarantined"),
        ]
    finally:
        connection.close()


def test_migration_is_idempotent_and_revalidates_exact_source_maps(
    tmp_path: Path,
) -> None:
    connection = _legacy_connection(tmp_path)
    try:
        _session(connection)
        _message(connection, "u1", "user", 1)
        _message(connection, "a1", "assistant", 2)
        _summary(connection, "exact", "safe exact", "u1", "a1", 2)
        connection.commit()

        for _ in range(2):
            connection.execute("BEGIN")
            migrate_gate_c2(connection)
            connection.commit()

        assert connection.execute(
            "SELECT COUNT(*) FROM chat_turns"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM session_summary_sources"
        ).fetchone()[0] == 2

        connection.execute("DROP TRIGGER trg_summary_sources_append_only_update")
        connection.execute(
            "UPDATE session_summary_sources SET turn_order=2 "
            "WHERE summary_id='exact' AND source_order=0"
        )
        connection.commit()
        connection.execute("BEGIN")
        with pytest.raises(RuntimeError, match="source map"):
            migrate_gate_c2(connection)
        connection.rollback()
    finally:
        connection.close()


def test_direct_constraints_enforce_turn_roles_source_maps_and_lineage(
    tmp_path: Path,
) -> None:
    connection = connect(f"sqlite:///{tmp_path / 'constraints.db'}")
    try:
        init_db(connection)
        _session(connection)
        _message(connection, "u1", "user", 1)
        _message(connection, "a1", "assistant", 2)
        _message(connection, "u2", "user", 3)
        _message(connection, "a2", "assistant", 4)
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO chat_turns VALUES "
                "('bad-turn', 'session-1', 'a1', 'u1', 1, 'now')"
            )
        connection.rollback()
        assert connection.execute(
            "SELECT COUNT(*) FROM chat_turns"
        ).fetchone()[0] == 0

        connection.execute(
            "INSERT INTO summary_jobs ("
            "id, session_id, job_kind, status, logical_source_identity, attempt_epoch, "
            "source_set_hash, source_message_count, source_turn_count, "
            "captured_barrier_generation, captured_processing_consent_generation, "
            "captured_session_deletion_generation, captured_suppression_generation, "
            "route, summarizer_schema_version, attempt_count, created_at) VALUES ("
            "'job-1', 'session-1', 'incremental', 'pending', 'logical', 'epoch', "
            "'hash', 2, 1, 0, 0, 0, 0, 'fake', ?, 0, 'now')",
            (SUMMARY_SCHEMA_VERSION,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE summary_jobs SET source_message_count=4 WHERE id='job-1'"
            )
        connection.rollback()

        connection.execute(
            "INSERT INTO summary_jobs ("
            "id, session_id, job_kind, status, logical_source_identity, attempt_epoch, "
            "source_set_hash, source_message_count, source_turn_count, "
            "captured_barrier_generation, captured_processing_consent_generation, "
            "captured_session_deletion_generation, captured_suppression_generation, "
            "route, summarizer_schema_version, attempt_count, created_at, finished_at) "
            "VALUES ('job-terminal', 'session-1', 'incremental', 'succeeded', "
            "'logical-terminal', 'epoch-terminal', 'hash', 2, 1, 0, 0, 0, 0, "
            "'fake', ?, 1, 'now', 'later')",
            (SUMMARY_SCHEMA_VERSION,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE summary_jobs SET reason_code='mutated' WHERE id='job-terminal'"
            )
        connection.rollback()

        connection.execute(
            "INSERT INTO chat_turns VALUES "
            "('turn-1', 'session-1', 'u1', 'a1', 1, 'now')"
        )
        connection.execute(
            "INSERT INTO session_summaries ("
            "id, session_id, summary_text, source, message_count, metadata_json, "
            "created_at, updated_at, observed_memory_summary_barrier, payload_state, "
            "source_set_hash, summarizer_schema_version, injection_schema_version, "
            "provenance_state) VALUES ("
            "'s1', 'session-1', 'safe', 'manual', 2, '{}', '1', '1', 0, "
            "'active', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
            "?, ?, 'legacy_unverified')",
            (SUMMARY_SCHEMA_VERSION, SUMMARY_INJECTION_SCHEMA_VERSION),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO session_summary_sources VALUES "
                "('s1', 'turn-1', 'a1', 1, 0, 0)"
            )
        connection.rollback()

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO session_summaries ("
                "id, session_id, summary_text, source, message_count, metadata_json, "
                "created_at, updated_at, observed_memory_summary_barrier, payload_state, "
                "source_set_hash, summarizer_schema_version, injection_schema_version, "
                "provenance_state) VALUES ("
                "'exact-direct', 'session-1', 'unsafe direct', 'generated', 2, '{}', "
                "'1', '1', 0, 'active', "
                "'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', "
                "?, ?, 'exact')",
                (SUMMARY_SCHEMA_VERSION, SUMMARY_INJECTION_SCHEMA_VERSION),
            )
        connection.rollback()

        connection.execute(
            "INSERT INTO session_summaries ("
            "id, session_id, summary_text, source, message_count, metadata_json, "
            "created_at, updated_at, observed_memory_summary_barrier, payload_state, "
            "provenance_state) VALUES ("
            "'base', 'session-1', 'base', 'manual', 0, '{}', '2', '2', 0, "
            "'active', 'legacy_unverified')"
        )
        connection.execute(
            "INSERT INTO sessions VALUES "
            "('session-2', 'other', 'now', 'now')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO session_summaries ("
                "id, session_id, summary_text, source, message_count, metadata_json, "
                "created_at, updated_at, observed_memory_summary_barrier, payload_state, "
                "replaces_summary_id, provenance_state) VALUES ("
                "'cross', 'session-2', 'cross', 'manual', 0, '{}', '3', '3', 0, "
                "'active', 'base', 'legacy_unverified')"
            )
        connection.rollback()
    finally:
        connection.close()


def test_migration_reconstructs_only_complete_deterministic_turns(
    tmp_path: Path,
) -> None:
    connection = _legacy_connection(tmp_path)
    try:
        _session(connection)
        _message(connection, "u1", "user", 1)
        _message(connection, "a1", "assistant", 2)
        _message(connection, "u2", "user", 3)
        _message(connection, "a2", "assistant", 4)
        _summary(connection, "exact", "safe exact", "u1", "a2", 4)
        connection.commit()

        connection.execute("BEGIN")
        migrate_gate_c2(connection)
        connection.commit()

        turns = connection.execute(
            "SELECT user_message_id, assistant_message_id, turn_order "
            "FROM chat_turns ORDER BY turn_order"
        ).fetchall()
        assert [tuple(row) for row in turns] == [
            ("u1", "a1", 1),
            ("u2", "a2", 2),
        ]
        row = connection.execute(
            "SELECT * FROM session_summaries WHERE id='exact'"
        ).fetchone()
        assert row is not None
        assert row["summary_text"] == "safe exact"
        assert row["payload_state"] == "active"
        assert row["provenance_state"] == "exact"
        assert row["summarizer_schema_version"] == SUMMARY_SCHEMA_VERSION
        assert row["injection_schema_version"] == SUMMARY_INJECTION_SCHEMA_VERSION
        assert len(str(row["source_set_hash"])) == 64
        sources = connection.execute(
            "SELECT message_id, turn_order, message_order_in_turn, source_order "
            "FROM session_summary_sources WHERE summary_id='exact' "
            "ORDER BY source_order"
        ).fetchall()
        assert [tuple(source) for source in sources] == [
            ("u1", 1, 0, 0),
            ("a1", 1, 1, 1),
            ("u2", 2, 0, 2),
            ("a2", 2, 1, 3),
        ]
        assert row["metadata_json"] == "{}"
    finally:
        connection.close()


def test_migration_redacts_ambiguous_stale_and_excluded_payloads(
    tmp_path: Path,
) -> None:
    connection = _legacy_connection(tmp_path)
    try:
        _session(connection)
        _message(connection, "u1", "user", 1, content="SECRET_SENTINEL")
        _message(connection, "a1", "assistant", 2, content="echo SECRET_SENTINEL")
        _message(connection, "u2", "user", 3)
        _message(connection, "u3", "user", 4)
        _message(connection, "a3", "assistant", 5)
        _summary(
            connection,
            "excluded",
            "EXCLUDED_PAYLOAD",
            "u1",
            "a1",
            2,
            metadata_json='{"provider_response":"METADATA_SECRET_SENTINEL"}',
        )
        _summary(connection, "ambiguous", "AMBIGUOUS_PAYLOAD", "u2", "a3", 3)
        _summary(connection, "stale", "STALE_PAYLOAD", "u1", "a1", 2)
        connection.execute(
            "UPDATE session_summaries SET observed_memory_summary_barrier=1 "
            "WHERE id <> 'stale'"
        )
        connection.execute(
            "UPDATE memory_summary_barrier SET generation=1 WHERE singleton_id=1"
        )
        connection.execute(
            "INSERT INTO memory_summary_source_exclusions VALUES "
            "('u1', 'memory_true_forget', 'now')"
        )
        connection.commit()

        connection.execute("BEGIN")
        migrate_gate_c2(connection)
        connection.commit()

        rows = {
            str(row["id"]): row
            for row in connection.execute(
                "SELECT id, summary_text, payload_state, provenance_state, "
                "redaction_reason_code FROM session_summaries"
            )
        }
        for summary_id in ("excluded", "ambiguous", "stale"):
            assert rows[summary_id]["summary_text"] is None
            assert rows[summary_id]["payload_state"] == "redacted"
            assert rows[summary_id]["redaction_reason_code"] is not None
        excluded = {
            str(row[0])
            for row in connection.execute(
                "SELECT source_message_id FROM memory_summary_source_exclusions"
            )
        }
        assert {"u1", "a1"} <= excluded
        raw = "\n".join(
            str(value)
            for row in connection.execute("SELECT * FROM session_summaries")
            for value in row
        )
        assert "EXCLUDED_PAYLOAD" not in raw
        assert "AMBIGUOUS_PAYLOAD" not in raw
        assert "STALE_PAYLOAD" not in raw
        assert "METADATA_SECRET_SENTINEL" not in raw
    finally:
        connection.close()


def test_safe_manual_legacy_payload_can_remain_but_is_noninjectable(
    tmp_path: Path,
) -> None:
    connection = _legacy_connection(tmp_path)
    try:
        _session(connection)
        _message(connection, "u1", "user", 1)
        _message(connection, "a1", "assistant", 2)
        _summary(
            connection,
            "manual",
            "manual safe",
            "u1",
            "a1",
            2,
            source="manual",
        )
        connection.commit()
        connection.execute("BEGIN")
        migrate_gate_c2(connection)
        connection.commit()

        row = connection.execute(
            "SELECT summary_text, payload_state, provenance_state, source "
            "FROM session_summaries WHERE id='manual'"
        ).fetchone()
        assert row is not None
        assert tuple(row) == ("manual safe", "active", "exact", "manual")
    finally:
        connection.close()


def test_session_summaries_rebuild_preserves_inbound_foreign_keys(tmp_path: Path) -> None:
    connection = _legacy_connection(tmp_path)
    try:
        connection.execute(
            "CREATE TABLE legacy_summary_bookmarks ("
            "id TEXT PRIMARY KEY, summary_id TEXT NOT NULL, "
            "FOREIGN KEY (summary_id) REFERENCES session_summaries(id) ON DELETE CASCADE)"
        )
        _session(connection)
        _message(connection, "u1", "user", 1)
        _message(connection, "a1", "assistant", 2)
        _summary(connection, "legacy", "safe", "u1", "a1", 2)
        connection.execute(
            "INSERT INTO legacy_summary_bookmarks VALUES ('bookmark', 'legacy')"
        )
        connection.commit()

        connection.execute("BEGIN")
        with pytest.raises(RuntimeError, match="inbound foreign keys"):
            migrate_gate_c2(connection)
        connection.rollback()

        target = connection.execute(
            "SELECT \"table\" FROM pragma_foreign_key_list('legacy_summary_bookmarks')"
        ).fetchone()
        assert target is not None
        assert target[0] == "session_summaries"
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(session_summaries)")
        }
        assert "payload_state" not in columns
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_migration_fault_rolls_back_schema_and_payload(tmp_path: Path) -> None:
    connection = _legacy_connection(tmp_path)
    try:
        _session(connection)
        _message(connection, "u1", "user", 1)
        _message(connection, "a1", "assistant", 2)
        _summary(connection, "legacy", "ROLLBACK_PAYLOAD", "u1", "a1", 2)
        connection.commit()
        before = connection.execute(
            "SELECT id, summary_text FROM session_summaries"
        ).fetchall()

        connection.execute("BEGIN")
        with pytest.raises(RuntimeError, match="migration fault"):
            migrate_gate_c2(
                connection,
                fault_injector=lambda point: (
                    (_ for _ in ()).throw(RuntimeError("migration fault"))
                    if point == "post_scrub"
                    else None
                ),
            )
        connection.rollback()

        assert connection.execute(
            "SELECT id, summary_text FROM session_summaries"
        ).fetchall() == before
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(session_summaries)")
        }
        assert "payload_state" not in columns
    finally:
        connection.close()
