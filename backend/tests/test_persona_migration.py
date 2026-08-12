import sqlite3
from pathlib import Path

import pytest

from app.repositories import sqlite as sqlite_repository
from app.repositories.memory_automation import MemoryAutomationRepository
from app.repositories.sqlite import connect, init_db, managed_connection


NOW = "2026-07-21T00:00:00+00:00"


def _insert_artifact(
    connection: sqlite3.Connection,
    artifact_id: str,
    version: int,
) -> None:
    connection.execute(
        """
        INSERT INTO persona_artifacts (
            id, version, payload_state, schema_version, ruleset_version,
            template_version, compiler_version, source_content_json,
            rendered_system_prompt, content_identity_hash,
            behavior_fingerprint, created_at, redacted_at,
            redaction_reason_code
        ) VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
        """,
        (
            artifact_id,
            version,
            "persona-schema-v1",
            "persona-ruleset-v1",
            "persona-template-v1",
            "persona-compiler-v1",
            '{"identity":{"name":"test"}}',
            f"prompt-{version}",
            f"{version:064x}",
            f"{version + 100:064x}",
            NOW,
        ),
    )


def _insert_two_artifacts(
    connection: sqlite3.Connection,
) -> tuple[str, str]:
    first = "persona-1"
    second = "persona-2"
    _insert_artifact(connection, first, 1)
    _insert_artifact(connection, second, 2)
    return first, second


def _set_active(
    connection: sqlite3.Connection,
    artifact_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO persona_active_state (
            singleton_id, artifact_id, activation_generation, updated_at
        ) VALUES (1, ?, 0, ?)
        """,
        (artifact_id, NOW),
    )


def _redact(connection: sqlite3.Connection, artifact_id: str) -> None:
    connection.execute(
        """
        UPDATE persona_artifacts
        SET payload_state='redacted', source_content_json=NULL,
            rendered_system_prompt=NULL, redacted_at=?,
            redaction_reason_code='user_privacy_redaction'
        WHERE id=?
        """,
        (NOW, artifact_id),
    )


def test_persona_schema_is_created_with_fixed_trigger_order(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "persona_artifacts",
            "persona_active_state",
            "persona_audits",
        } <= tables
        triggers = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='trigger' AND name LIKE 'trg_persona_%' ORDER BY rowid"
            )
        ]
        assert triggers == [
            "trg_persona_artifacts_immutable_delete",
            "trg_persona_artifacts_immutable_update",
            "trg_persona_active_state_valid_insert",
            "trg_persona_active_state_valid_update",
            "trg_persona_active_state_immutable_delete",
        ]
        assert "persona_artifact_id" in {
            row[1] for row in connection.execute("PRAGMA table_info(memory_jobs)")
        }


def test_persona_schema_allows_only_safe_noncurrent_redaction(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        first, second = _insert_two_artifacts(connection)
        _set_active(connection, second)
        connection.commit()

        _redact(connection, first)
        connection.commit()

        row = connection.execute(
            "SELECT payload_state, source_content_json, rendered_system_prompt "
            "FROM persona_artifacts WHERE id=?",
            (first,),
        ).fetchone()
        assert tuple(row) == ("redacted", None, None)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE persona_artifacts SET source_content_json=NULL WHERE id='persona-1'",
        "UPDATE persona_artifacts SET created_at='changed' WHERE id='persona-1'",
        "DELETE FROM persona_artifacts WHERE id='persona-1'",
    ],
)
def test_persona_schema_rejects_unsafe_artifact_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        _insert_artifact(connection, "persona-1", 1)
        connection.commit()

        with pytest.raises(
            sqlite3.IntegrityError,
            match="persona artifact invariant violation",
        ):
            connection.execute(mutation)
        connection.rollback()

        assert connection.execute(
            "SELECT payload_state, source_content_json FROM persona_artifacts "
            "WHERE id='persona-1'"
        ).fetchone()[0] == "active"


def test_persona_schema_rejects_current_and_last_usable_redaction(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        first, second = _insert_two_artifacts(connection)
        _set_active(connection, first)
        connection.commit()

        with pytest.raises(
            sqlite3.IntegrityError,
            match="persona artifact invariant violation",
        ):
            _redact(connection, first)
        connection.rollback()

        connection.execute(
            "UPDATE persona_active_state SET artifact_id=?, "
            "activation_generation=activation_generation+1, updated_at=? "
            "WHERE singleton_id=1",
            (second, NOW),
        )
        _redact(connection, first)
        connection.commit()

        with pytest.raises(
            sqlite3.IntegrityError,
            match="persona artifact invariant violation",
        ):
            _redact(connection, second)
        connection.rollback()


def test_persona_schema_rejects_reverse_redaction_transition(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        first, second = _insert_two_artifacts(connection)
        _set_active(connection, second)
        _redact(connection, first)
        connection.commit()

        with pytest.raises(
            sqlite3.IntegrityError,
            match="persona artifact invariant violation",
        ):
            connection.execute(
                "UPDATE persona_artifacts SET payload_state='active', "
                "source_content_json='{}', rendered_system_prompt='restored', "
                "redacted_at=NULL, redaction_reason_code=NULL WHERE id=?",
                (first,),
            )
        connection.rollback()


def test_persona_schema_rejects_last_usable_redaction_without_pointer(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        _insert_artifact(connection, "persona-1", 1)
        connection.commit()

        with pytest.raises(
            sqlite3.IntegrityError,
            match="persona artifact invariant violation",
        ):
            _redact(connection, "persona-1")
        connection.rollback()


def test_persona_schema_rejects_pointer_insert_to_redacted_artifact(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        first, second = _insert_two_artifacts(connection)
        _set_active(connection, second)
        _redact(connection, first)
        connection.commit()
        connection.execute("DROP TRIGGER trg_persona_active_state_immutable_delete")
        connection.execute("DELETE FROM persona_active_state")

        with pytest.raises(
            sqlite3.IntegrityError,
            match="persona active state invariant violation",
        ):
            connection.execute(
                "INSERT INTO persona_active_state VALUES (1, ?, 0, ?)",
                (first, NOW),
            )
        connection.rollback()


@pytest.mark.parametrize(
    "operation",
    [
        "INSERT INTO persona_active_state VALUES (1, 'missing', 0, 'now')",
        "INSERT INTO persona_active_state VALUES (2, 'persona-2', 0, 'now')",
        "INSERT INTO persona_active_state VALUES (1, 'persona-2', 1, 'now')",
        "UPDATE persona_active_state SET artifact_id='missing', "
        "activation_generation=activation_generation+1 WHERE singleton_id=1",
        "UPDATE persona_active_state SET artifact_id='persona-2' "
        "WHERE singleton_id=1",
        "UPDATE persona_active_state SET activation_generation="
        "activation_generation+1 WHERE singleton_id=1",
        "UPDATE persona_active_state SET artifact_id='persona-2', "
        "activation_generation=activation_generation+2 WHERE singleton_id=1",
        "DELETE FROM persona_active_state WHERE singleton_id=1",
    ],
)
def test_persona_schema_rejects_unsafe_active_pointer_sql(
    tmp_path: Path,
    operation: str,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        first, _ = _insert_two_artifacts(connection)
        _set_active(connection, first)
        connection.commit()

        with pytest.raises(
            sqlite3.IntegrityError,
            match="persona active state invariant violation",
        ):
            connection.execute(operation)
        connection.rollback()

        assert tuple(
            connection.execute(
                "SELECT artifact_id, activation_generation "
                "FROM persona_active_state WHERE singleton_id=1"
            ).fetchone()
        ) == (first, 0)


def test_persona_schema_rejects_pointer_to_redacted_artifact(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        first, second = _insert_two_artifacts(connection)
        _set_active(connection, second)
        _redact(connection, first)
        connection.commit()

        with pytest.raises(
            sqlite3.IntegrityError,
            match="persona active state invariant violation",
        ):
            connection.execute(
                "UPDATE persona_active_state SET artifact_id=?, "
                "activation_generation=activation_generation+1 WHERE singleton_id=1",
                (first,),
            )
        connection.rollback()


def test_persona_schema_rolls_back_artifact_and_pointer_together(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        first, second = _insert_two_artifacts(connection)
        _set_active(connection, first)
        connection.commit()

        connection.execute(
            "UPDATE persona_active_state SET artifact_id=?, "
            "activation_generation=activation_generation+1 WHERE singleton_id=1",
            (second,),
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="persona artifact invariant violation",
        ):
            connection.execute("DELETE FROM persona_artifacts WHERE id=?", (first,))
        connection.rollback()

        assert tuple(
            connection.execute(
                "SELECT artifact_id, activation_generation "
                "FROM persona_active_state WHERE singleton_id=1"
            ).fetchone()
        ) == (first, 0)


def test_persona_migration_rolls_back_all_schema_changes_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'rollback.db'}"
    connection = connect(database_url)
    init_db(connection)
    connection.execute("DROP TRIGGER trg_memory_jobs_persona_insert")
    connection.execute("DROP TRIGGER trg_memory_jobs_frozen_snapshot_update")
    connection.execute("ALTER TABLE memory_jobs DROP COLUMN persona_artifact_id")
    connection.execute("DROP TRIGGER trg_persona_active_state_immutable_delete")
    connection.execute("DROP TRIGGER trg_persona_active_state_valid_update")
    connection.execute("DROP TRIGGER trg_persona_active_state_valid_insert")
    connection.execute("DROP TRIGGER trg_persona_artifacts_immutable_update")
    connection.execute("DROP TRIGGER trg_persona_artifacts_immutable_delete")
    connection.execute("DROP TABLE persona_audits")
    connection.execute("DROP TABLE persona_active_state")
    connection.execute("DROP TABLE persona_artifacts")
    connection.commit()
    schema_before = [
        tuple(row)
        for row in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "ORDER BY type, name"
        )
    ]
    job_columns_before = [
        tuple(row) for row in connection.execute("PRAGMA table_info(memory_jobs)")
    ]

    def fail_after_persona_schema(
        connection_arg: sqlite3.Connection,
        script: str,
    ) -> None:
        if "CREATE INDEX IF NOT EXISTS idx_memories_status_importance_updated" in script:
            raise RuntimeError("injected post-Persona migration failure")
        original_execute_script(connection_arg, script)

    original_execute_script = sqlite_repository._execute_script_in_current_transaction
    monkeypatch.setattr(
        sqlite_repository,
        "_execute_script_in_current_transaction",
        fail_after_persona_schema,
    )

    with pytest.raises(RuntimeError, match="injected post-Persona migration failure"):
        init_db(connection)

    schema_after = [
        tuple(row)
        for row in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "ORDER BY type, name"
        )
    ]
    assert schema_after == schema_before
    assert [
        tuple(row) for row in connection.execute("PRAGMA table_info(memory_jobs)")
    ] == job_columns_before
    connection.close()


def test_memory_job_persona_reference_is_valid_and_immutable(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        _insert_artifact(connection, "persona-1", 1)
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memory_jobs (
                    id, turn_id, schema_version, mode, extractor_route, status,
                    governor_version, created_at, persona_artifact_id
                ) VALUES ('job-invalid', 'turn-invalid', 'v', 'shadow_auto',
                          'none', 'pending', 'v', ?, 'missing')
                """,
                (NOW,),
            )
        connection.rollback()

        connection.execute(
            """
            INSERT INTO memory_jobs (
                id, turn_id, schema_version, mode, extractor_route, status,
                governor_version, created_at, persona_artifact_id
            ) VALUES ('job-1', 'turn-1', 'v', 'shadow_auto', 'none',
                      'pending', 'v', ?, 'persona-1')
            """,
            (NOW,),
        )
        connection.commit()

        job = MemoryAutomationRepository(connection).require_job("job-1")
        assert job.persona_artifact_id == "persona-1"

        with pytest.raises(
            sqlite3.IntegrityError,
            match="memory job reservation snapshot is immutable",
        ):
            connection.execute(
                "UPDATE memory_jobs SET persona_artifact_id=NULL WHERE id='job-1'"
            )
        connection.rollback()
