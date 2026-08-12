from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

from app.domain.persona import (
    PersonaActiveState,
    PersonaArtifact,
    PersonaPayloadState,
    PersonaStartupState,
)
from app.services.persona_compiler import CompiledPersona


class PersonaRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._transaction_depth = 0

    @contextmanager
    def write_transaction(self) -> Iterator[None]:
        if self._transaction_depth:
            savepoint = f"persona_sp_{self._transaction_depth}"
            self._transaction_depth += 1
            self._connection.execute(f"SAVEPOINT {savepoint}")
            try:
                yield
            except BaseException:
                self._connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            finally:
                self._transaction_depth -= 1
            return

        if self._connection.in_transaction:
            raise RuntimeError("connection already has an unmanaged transaction")
        self._transaction_depth = 1
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
        except BaseException:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()
        finally:
            self._transaction_depth = 0

    def inspect_startup_state(self) -> PersonaStartupState:
        artifact_count = int(
            self._connection.execute(
                "SELECT COUNT(*) FROM persona_artifacts"
            ).fetchone()[0]
        )
        return PersonaStartupState(
            artifact_count=artifact_count,
            active_state=self.current_state(),
        )

    def current_state(self) -> PersonaActiveState | None:
        row = self._connection.execute(
            "SELECT artifact_id, activation_generation, updated_at "
            "FROM persona_active_state WHERE singleton_id=1"
        ).fetchone()
        if row is None:
            return None
        return PersonaActiveState(
            artifact_id=str(row["artifact_id"]),
            activation_generation=int(row["activation_generation"]),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def artifact(self, artifact_id: str) -> PersonaArtifact | None:
        row = self._connection.execute(
            "SELECT * FROM persona_artifacts WHERE id=?",
            (artifact_id,),
        ).fetchone()
        return self._artifact_from_row(row) if row is not None else None

    def list_artifacts(self) -> list[PersonaArtifact]:
        rows = self._connection.execute(
            "SELECT * FROM persona_artifacts ORDER BY version ASC"
        ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def next_version(self) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM persona_artifacts"
        ).fetchone()
        return int(row[0])

    def insert_artifact(
        self,
        compiled: CompiledPersona,
        *,
        artifact_id: str,
        created_at: datetime,
    ) -> PersonaArtifact:
        self._connection.execute(
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
                self.next_version(),
                compiled.schema_version,
                compiled.ruleset_version,
                compiled.template_version,
                compiled.compiler_version,
                json.dumps(
                    compiled.source_content,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                compiled.rendered_system_prompt,
                compiled.content_identity_hash,
                compiled.behavior_fingerprint,
                created_at.isoformat(),
            ),
        )
        artifact = self.artifact(artifact_id)
        if artifact is None:
            raise RuntimeError("Persona artifact insert did not persist")
        return artifact

    def insert_initial_state(
        self,
        artifact_id: str,
        *,
        updated_at: datetime,
    ) -> PersonaActiveState:
        self._connection.execute(
            "INSERT INTO persona_active_state "
            "(singleton_id, artifact_id, activation_generation, updated_at) "
            "VALUES (1, ?, 0, ?)",
            (artifact_id, updated_at.isoformat()),
        )
        state = self.current_state()
        if state is None:
            raise RuntimeError("Persona active state insert did not persist")
        return state

    def cas_activate(
        self,
        artifact_id: str,
        *,
        expected_artifact_id: str,
        expected_generation: int,
        updated_at: datetime,
    ) -> PersonaActiveState | None:
        cursor = self._connection.execute(
            """
            UPDATE persona_active_state
            SET artifact_id=?, activation_generation=activation_generation+1,
                updated_at=?
            WHERE singleton_id=1 AND artifact_id=? AND activation_generation=?
            """,
            (
                artifact_id,
                updated_at.isoformat(),
                expected_artifact_id,
                expected_generation,
            ),
        )
        if cursor.rowcount != 1:
            return None
        return self.current_state()

    def redact_payload(
        self,
        artifact_id: str,
        *,
        redacted_at: datetime,
    ) -> PersonaArtifact:
        self._connection.execute(
            """
            UPDATE persona_artifacts
            SET payload_state='redacted', source_content_json=NULL,
                rendered_system_prompt=NULL, redacted_at=?,
                redaction_reason_code='user_privacy_redaction'
            WHERE id=?
            """,
            (redacted_at.isoformat(), artifact_id),
        )
        artifact = self.artifact(artifact_id)
        if artifact is None:
            raise RuntimeError("Persona artifact redaction target disappeared")
        return artifact

    def append_audit(
        self,
        *,
        action: str,
        artifact_id: str,
        reason_code: str,
        created_at: datetime,
    ) -> None:
        artifact = self.artifact(artifact_id)
        self._connection.execute(
            """
            INSERT INTO persona_audits (
                id, action, artifact_id, artifact_version, reason_code,
                actor_kind, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                action,
                artifact_id,
                artifact.version if artifact is not None else None,
                reason_code,
                "system" if action == "bootstrap" else "user",
                created_at.isoformat(),
            ),
        )

    def latest_audit(self) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM persona_audits ORDER BY rowid DESC LIMIT 1"
        ).fetchone()

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> PersonaArtifact:
        source_content = (
            json.loads(str(row["source_content_json"]))
            if row["source_content_json"] is not None
            else None
        )
        if source_content is not None and not isinstance(source_content, dict):
            raise ValueError("invalid persisted Persona source content")
        return PersonaArtifact(
            id=str(row["id"]),
            version=int(row["version"]),
            payload_state=PersonaPayloadState(str(row["payload_state"])),
            schema_version=str(row["schema_version"]),
            ruleset_version=str(row["ruleset_version"]),
            template_version=str(row["template_version"]),
            compiler_version=str(row["compiler_version"]),
            source_content=source_content,
            rendered_system_prompt=(
                str(row["rendered_system_prompt"])
                if row["rendered_system_prompt"] is not None
                else None
            ),
            content_identity_hash=str(row["content_identity_hash"]),
            behavior_fingerprint=str(row["behavior_fingerprint"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            redacted_at=(
                datetime.fromisoformat(str(row["redacted_at"]))
                if row["redacted_at"] is not None
                else None
            ),
            redaction_reason_code=row["redaction_reason_code"],
        )
