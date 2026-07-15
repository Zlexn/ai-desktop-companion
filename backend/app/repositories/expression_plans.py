import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.models import (
    EXPRESSION_PLAN_SCHEMA_VERSION,
    ExpressionDelivery,
    ExpressionIntensity,
    ExpressionPlan,
    ExpressionPlanDraft,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _row_to_expression_plan(row: sqlite3.Row) -> ExpressionPlan:
    return ExpressionPlan(
        id=str(row["id"]),
        assistant_message_id=str(row["assistant_message_id"]),
        schema_version=row["schema_version"],
        source_emotion_version=row["source_emotion_version"],
        delivery=ExpressionDelivery(str(row["delivery"])),
        rate=float(row["rate"]),
        intensity=ExpressionIntensity(str(row["intensity"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
    )


class ExpressionPlanRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(
        self,
        assistant_message_id: str,
        draft: ExpressionPlanDraft,
        *,
        schema_version: int = EXPRESSION_PLAN_SCHEMA_VERSION,
    ) -> ExpressionPlan:
        plan = ExpressionPlan(
            id=str(uuid4()),
            assistant_message_id=assistant_message_id,
            schema_version=schema_version,
            source_emotion_version=draft.source_emotion_version,
            delivery=draft.delivery,
            rate=draft.rate,
            intensity=draft.intensity,
            created_at=_now(),
        )
        try:
            self._connection.execute(
                """
                INSERT INTO expression_plans (
                    id, assistant_message_id, schema_version, source_emotion_version,
                    delivery, rate, intensity, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.id,
                    plan.assistant_message_id,
                    plan.schema_version,
                    plan.source_emotion_version,
                    plan.delivery.value,
                    plan.rate,
                    plan.intensity.value,
                    plan.created_at.isoformat(),
                ),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return plan

    def get(
        self,
        assistant_message_id: str,
        *,
        schema_version: int = EXPRESSION_PLAN_SCHEMA_VERSION,
    ) -> ExpressionPlan | None:
        row = self._connection.execute(
            """
            SELECT id, assistant_message_id, schema_version, source_emotion_version,
                   delivery, rate, intensity, created_at
            FROM expression_plans
            WHERE assistant_message_id = ? AND schema_version = ?
            """,
            (assistant_message_id, schema_version),
        ).fetchone()
        return None if row is None else _row_to_expression_plan(row)
