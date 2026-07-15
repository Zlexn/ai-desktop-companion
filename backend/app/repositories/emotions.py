import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.models import (
    DEFAULT_EMOTION_SCOPE_ID,
    EMOTION_BASELINE,
    EmotionEvent,
    EmotionEventType,
    EmotionState,
    EmotionVector,
)


class EmotionVersionConflictError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _vector_dict(vector: EmotionVector) -> dict[str, float]:
    return {
        "mood": vector.mood,
        "trust": vector.trust,
        "concern": vector.concern,
        "distance": vector.distance,
        "irritation": vector.irritation,
        "formality": vector.formality,
    }


def _vector_from_json(raw: str) -> EmotionVector:
    value = json.loads(raw)
    return EmotionVector(**{key: float(value[key]) for key in _vector_dict(EMOTION_BASELINE)})


class EmotionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._transaction_depth = 0

    def begin_transaction(self) -> None:
        self._transaction_depth += 1

    def end_transaction(self) -> None:
        if self._transaction_depth <= 0:
            raise RuntimeError("emotion transaction depth is not active")
        self._transaction_depth -= 1

    def _commit(self) -> None:
        if not self._transaction_depth:
            self._connection.commit()

    def _rollback(self) -> None:
        if not self._transaction_depth:
            self._connection.rollback()

    def get_or_create(self, scope_id: str = DEFAULT_EMOTION_SCOPE_ID) -> EmotionState:
        row = self._connection.execute(
            "SELECT * FROM emotion_states WHERE scope_id = ?", (scope_id,)
        ).fetchone()
        if row is None:
            now = _now()
            self._connection.execute(
                """
                INSERT OR IGNORE INTO emotion_states (
                    scope_id, enabled, mood, trust, concern, distance,
                    irritation, formality, version, updated_at
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (scope_id, *EMOTION_BASELINE.values(), now.isoformat()),
            )
            self._commit()
            row = self._connection.execute(
                "SELECT * FROM emotion_states WHERE scope_id = ?", (scope_id,)
            ).fetchone()
        assert row is not None
        return self._state_from_row(row)

    def apply_transition(
        self,
        *,
        expected_version: int,
        after: EmotionVector,
        event_type: EmotionEventType,
        reason_codes: tuple[str, ...],
        source_session_id: str | None,
        source_user_message_id: str | None,
        source_assistant_message_id: str | None,
        engine: str,
        rule_version: str,
        scope_id: str = DEFAULT_EMOTION_SCOPE_ID,
        enabled: bool | None = None,
    ) -> EmotionState:
        before = self.get_or_create(scope_id)
        now = _now()
        delta = EmotionVector(*(
            round(after_value - before_value, 6)
            for after_value, before_value in zip(after.values(), before.vector.values(), strict=True)
        ))
        next_enabled = before.enabled if enabled is None else enabled
        try:
            cursor = self._connection.execute(
                """
                UPDATE emotion_states
                SET enabled = ?, mood = ?, trust = ?, concern = ?, distance = ?,
                    irritation = ?, formality = ?, version = version + 1, updated_at = ?
                WHERE scope_id = ? AND version = ?
                """,
                (int(next_enabled), *after.values(), now.isoformat(), scope_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise EmotionVersionConflictError("emotion state version changed")
            self._connection.execute(
                """
                INSERT INTO emotion_events (
                    id, scope_id, event_type, before_json, after_json,
                    applied_delta_json, reason_codes_json, source_session_id,
                    source_user_message_id, source_assistant_message_id,
                    engine, rule_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()), scope_id, event_type.value,
                    json.dumps(_vector_dict(before.vector), sort_keys=True),
                    json.dumps(_vector_dict(after), sort_keys=True),
                    json.dumps(_vector_dict(delta), sort_keys=True),
                    json.dumps(reason_codes), source_session_id, source_user_message_id,
                    source_assistant_message_id, engine, rule_version, now.isoformat(),
                ),
            )
            self._commit()
        except Exception:
            self._rollback()
            raise
        return self.get_or_create(scope_id)

    def get_rule_event_for_assistant(
        self,
        assistant_message_id: str,
        *,
        scope_id: str = DEFAULT_EMOTION_SCOPE_ID,
    ) -> EmotionEvent | None:
        row = self._connection.execute(
            """
            SELECT * FROM emotion_events
            WHERE scope_id = ? AND source_assistant_message_id = ? AND engine = 'rule'
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (scope_id, assistant_message_id),
        ).fetchone()
        return None if row is None else self._event_from_row(row)

    def list_events(
        self,
        *,
        limit: int,
        scope_id: str = DEFAULT_EMOTION_SCOPE_ID,
    ) -> list[EmotionEvent]:
        rows = self._connection.execute(
            """
            SELECT * FROM emotion_events
            WHERE scope_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (scope_id, limit),
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    @staticmethod
    def _state_from_row(row: sqlite3.Row) -> EmotionState:
        return EmotionState(
            scope_id=str(row["scope_id"]),
            enabled=bool(row["enabled"]),
            vector=EmotionVector(
                mood=float(row["mood"]),
                trust=float(row["trust"]),
                concern=float(row["concern"]),
                distance=float(row["distance"]),
                irritation=float(row["irritation"]),
                formality=float(row["formality"]),
            ),
            version=int(row["version"]),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> EmotionEvent:
        reasons = json.loads(str(row["reason_codes_json"]))
        return EmotionEvent(
            id=str(row["id"]),
            scope_id=str(row["scope_id"]),
            event_type=EmotionEventType(str(row["event_type"])),
            before=_vector_from_json(str(row["before_json"])),
            after=_vector_from_json(str(row["after_json"])),
            applied_delta=_vector_from_json(str(row["applied_delta_json"])),
            reason_codes=tuple(str(reason) for reason in reasons),
            source_session_id=row["source_session_id"],
            source_user_message_id=row["source_user_message_id"],
            source_assistant_message_id=row["source_assistant_message_id"],
            engine=str(row["engine"]),
            rule_version=str(row["rule_version"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )
