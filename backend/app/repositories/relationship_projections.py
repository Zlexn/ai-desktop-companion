from __future__ import annotations

import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Iterator

from app.domain.relationship import (
    RelationshipProjectionSnapshot,
    RelationshipSummaryCode,
)
from app.services.relationship_contract import (
    FAMILIARITY_MAX,
    FAMILIARITY_MIN,
    RELATIONSHIP_PROJECTION_RULE_VERSION,
    RELATIONSHIP_SCOPE_ID,
    familiarity_bucket,
    relationship_private_fingerprint,
)


class CorruptRelationshipProjectionError(ValueError):
    pass


class RelationshipProjectionRepository:
    """Stores immutable relationship projections and verifies current views."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @contextmanager
    def write_transaction(self) -> Iterator[None]:
        if self._connection.in_transaction:
            savepoint = f"relationship_projection_{uuid.uuid4().hex}"
            self._connection.execute(f"SAVEPOINT {savepoint}")
            try:
                yield
            except BaseException:
                self._connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            return
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
        except BaseException:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    def current(self, *, scope_id: str = RELATIONSHIP_SCOPE_ID) -> RelationshipProjectionSnapshot | None:
        row = self._connection.execute(
            """
            SELECT projection.*
            FROM relationship_projection_active_state AS active
            JOIN relationship_projections AS projection
              ON projection.scope_id = active.scope_id
             AND projection.projection_id = active.projection_id
             AND projection.version = active.projection_version
            WHERE active.scope_id = ?
            """,
            (scope_id,),
        ).fetchone()
        return None if row is None else self._snapshot_from_row(row)

    def pointer_generation(self, *, scope_id: str = RELATIONSHIP_SCOPE_ID) -> int | None:
        row = self._connection.execute(
            "SELECT generation FROM relationship_projection_active_state WHERE scope_id = ?",
            (scope_id,),
        ).fetchone()
        if row is None:
            return None
        generation = row["generation"]
        if type(generation) is not int or generation < 0:
            raise CorruptRelationshipProjectionError(
                "relationship projection pointer is invalid"
            )
        return generation

    def append_and_activate(
        self,
        *,
        snapshot: RelationshipProjectionSnapshot,
        expected_pointer_generation: int | None,
    ) -> RelationshipProjectionSnapshot:
        if not self._connection.in_transaction:
            raise RuntimeError("projection append requires a write transaction")
        if (
            snapshot.scope_id != RELATIONSHIP_SCOPE_ID
            or snapshot.projection_rule_version
            != RELATIONSHIP_PROJECTION_RULE_VERSION
            or snapshot.source_emotion_snapshot_id is not None
            or snapshot.relationship_summary_code.value
            != familiarity_bucket(snapshot.familiarity)
            or (
                snapshot.preferred_address_event_id is not None
                and snapshot.preferred_address_event_id
                not in snapshot.source_relationship_event_ids
            )
            or self.fingerprint(snapshot) != snapshot.integrity_fingerprint
        ):
            raise ValueError("relationship projection snapshot is invalid")
        if self.current(scope_id=snapshot.scope_id) is not None:
            current_generation = self.pointer_generation(scope_id=snapshot.scope_id)
            if current_generation != expected_pointer_generation:
                raise ValueError("relationship projection pointer expectation is stale")
        elif expected_pointer_generation is not None:
            raise ValueError("relationship projection pointer expectation is stale")
        self._connection.execute(
            """
            INSERT INTO relationship_projections (
                projection_id, version, scope_id, persona_artifact_id,
                projection_rule_version, familiarity, preferred_address_event_id,
                relationship_summary_code, source_relationship_event_ids_json,
                source_emotion_snapshot_id, computed_at, integrity_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                snapshot.projection_id,
                snapshot.version,
                snapshot.scope_id,
                snapshot.persona_artifact_id,
                snapshot.projection_rule_version,
                snapshot.familiarity,
                snapshot.preferred_address_event_id,
                snapshot.relationship_summary_code.value,
                _canonical_json(list(snapshot.source_relationship_event_ids)),
                snapshot.computed_at.isoformat(),
                snapshot.integrity_fingerprint,
            ),
        )
        if expected_pointer_generation is None:
            self._connection.execute(
                """
                INSERT INTO relationship_projection_active_state (
                    scope_id, projection_id, projection_version, generation, updated_at
                ) VALUES (?, ?, ?, 0, ?)
                """,
                (
                    snapshot.scope_id,
                    snapshot.projection_id,
                    snapshot.version,
                    snapshot.computed_at.isoformat(),
                ),
            )
        else:
            cursor = self._connection.execute(
                """
                UPDATE relationship_projection_active_state
                SET projection_id = ?, projection_version = ?,
                    generation = generation + 1, updated_at = ?
                WHERE scope_id = ? AND generation = ?
                """,
                (
                    snapshot.projection_id,
                    snapshot.version,
                    snapshot.computed_at.isoformat(),
                    snapshot.scope_id,
                    expected_pointer_generation,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("relationship projection pointer expectation is stale")
        return self.current(scope_id=snapshot.scope_id) or snapshot

    @staticmethod
    def same_semantics(
        left: RelationshipProjectionSnapshot,
        right: RelationshipProjectionSnapshot,
    ) -> bool:
        return (
            left.scope_id == right.scope_id
            and left.persona_artifact_id == right.persona_artifact_id
            and left.projection_rule_version == right.projection_rule_version
            and left.familiarity == right.familiarity
            and left.preferred_address_event_id == right.preferred_address_event_id
            and left.relationship_summary_code is right.relationship_summary_code
            and left.source_relationship_event_ids == right.source_relationship_event_ids
            and left.source_emotion_snapshot_id is None
            and right.source_emotion_snapshot_id is None
        )

    @staticmethod
    def integrity_document(snapshot: RelationshipProjectionSnapshot) -> dict[str, object]:
        return {
            "projection_id": snapshot.projection_id,
            "version": snapshot.version,
            "scope_id": snapshot.scope_id,
            "persona_artifact_id": snapshot.persona_artifact_id,
            "projection_rule_version": snapshot.projection_rule_version,
            "familiarity": snapshot.familiarity,
            "preferred_address_event_id": snapshot.preferred_address_event_id,
            "relationship_summary_code": snapshot.relationship_summary_code.value,
            "source_relationship_event_ids": list(
                snapshot.source_relationship_event_ids
            ),
            "source_emotion_snapshot_id": None,
        }

    @classmethod
    def fingerprint(cls, snapshot: RelationshipProjectionSnapshot) -> str:
        return relationship_private_fingerprint(cls.integrity_document(snapshot))

    @classmethod
    def _snapshot_from_row(cls, row: sqlite3.Row) -> RelationshipProjectionSnapshot:
        try:
            projection_id = _required_text(row["projection_id"])
            version = _positive_integer(row["version"])
            scope_id = _required_text(row["scope_id"])
            persona_id = _required_text(row["persona_artifact_id"])
            projection_rule = _required_text(row["projection_rule_version"])
            familiarity = _finite_familiarity(row["familiarity"])
            address_id = row["preferred_address_event_id"]
            if address_id is not None:
                address_id = _required_text(address_id)
            summary = RelationshipSummaryCode(_required_text(row["relationship_summary_code"]))
            event_ids_raw = _required_text(row["source_relationship_event_ids_json"])
            event_ids = json.loads(event_ids_raw)
            if (
                type(event_ids) is not list
                or not all(isinstance(value, str) and value for value in event_ids)
                or len(event_ids) != len(set(event_ids))
                or _canonical_json(event_ids) != event_ids_raw
            ):
                raise ValueError
            if row["source_emotion_snapshot_id"] is not None:
                raise ValueError
            computed_at = _stored_datetime(row["computed_at"])
            fingerprint = row["integrity_fingerprint"]
            if not _valid_fingerprint(fingerprint):
                raise ValueError
            if projection_rule != RELATIONSHIP_PROJECTION_RULE_VERSION:
                raise ValueError
            if summary.value != familiarity_bucket(familiarity):
                raise ValueError
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise CorruptRelationshipProjectionError(
                "relationship projection row is invalid"
            ) from exc
        snapshot = RelationshipProjectionSnapshot(
            projection_id=projection_id,
            version=version,
            scope_id=scope_id,
            persona_artifact_id=persona_id,
            projection_rule_version=projection_rule,
            familiarity=familiarity,
            preferred_address_event_id=address_id,
            relationship_summary_code=summary,
            source_relationship_event_ids=tuple(event_ids),
            source_emotion_snapshot_id=None,
            computed_at=computed_at,
            integrity_fingerprint=fingerprint,
        )
        if cls.fingerprint(snapshot) != fingerprint:
            raise CorruptRelationshipProjectionError(
                "relationship projection integrity is invalid"
            )
        if (
            address_id is not None
            and address_id not in snapshot.source_relationship_event_ids
        ):
            raise CorruptRelationshipProjectionError(
                "relationship projection address event is not a source"
            )
        return snapshot


def _canonical_json(document: object) -> str:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError
    return value


def _positive_integer(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError
    return value


def _finite_familiarity(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not FAMILIARITY_MIN <= float(value) <= FAMILIARITY_MAX
    ):
        raise ValueError
    return float(value)


def _stored_datetime(value: object) -> datetime:
    text = _required_text(value)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.isoformat() != text:
        raise ValueError
    return parsed.astimezone(UTC)


def _valid_fingerprint(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
