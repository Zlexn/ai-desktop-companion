import sqlite3
from pathlib import Path

import pytest

from app.domain.models import ChatRole, ExpressionDelivery, ExpressionIntensity, ExpressionPlanDraft
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import connect, managed_connection


def test_expression_plan_repository_persists_exact_message_and_version(tmp_path: Path) -> None:
    from app.repositories.expression_plans import ExpressionPlanRepository

    database_url = f"sqlite:///{tmp_path / 'expression-plan.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("plan test")
        message = MessageRepository(connection).add(session.id, ChatRole.ASSISTANT, "persisted reply")
        repository = ExpressionPlanRepository(connection)

        created = repository.create(
            message.id,
            ExpressionPlanDraft(
                source_emotion_version=7,
                delivery=ExpressionDelivery.WARM,
                rate=1.04,
                intensity=ExpressionIntensity.MEDIUM,
            ),
        )

        assert repository.get(message.id) == created
        assert created.assistant_message_id == message.id
        assert created.schema_version == 1


def test_expression_plan_repository_reads_requested_future_schema_version(tmp_path: Path) -> None:
    from app.repositories.expression_plans import ExpressionPlanRepository

    database_url = f"sqlite:///{tmp_path / 'future-schema.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("future schema")
        message = MessageRepository(connection).add(session.id, ChatRole.ASSISTANT, "reply")
        repository = ExpressionPlanRepository(connection)
        created = repository.create(
            message.id,
            ExpressionPlanDraft(3, ExpressionDelivery.RESERVED, 0.94, ExpressionIntensity.LOW),
            schema_version=2,
        )

        assert repository.get(message.id) is None
        assert repository.get(message.id, schema_version=2) == created


def test_expression_plan_repository_enforces_one_plan_per_message_version(tmp_path: Path) -> None:
    from app.repositories.expression_plans import ExpressionPlanRepository

    database_url = f"sqlite:///{tmp_path / 'unique.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("idempotency")
        message = MessageRepository(connection).add(session.id, ChatRole.ASSISTANT, "reply")
        repository = ExpressionPlanRepository(connection)
        draft = ExpressionPlanDraft(0, ExpressionDelivery.NEUTRAL, 1.0, ExpressionIntensity.LOW)

        repository.create(message.id, draft)
        with pytest.raises(sqlite3.IntegrityError):
            repository.create(message.id, draft)


def test_expression_plan_repository_rolls_back_failed_unique_insert(tmp_path: Path) -> None:
    from app.repositories.expression_plans import ExpressionPlanRepository

    database_url = f"sqlite:///{tmp_path / 'rollback.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("rollback")
        message = MessageRepository(connection).add(session.id, ChatRole.ASSISTANT, "reply")
        repository = ExpressionPlanRepository(connection)
        draft = ExpressionPlanDraft(0, ExpressionDelivery.NEUTRAL, 1.0, ExpressionIntensity.LOW)
        repository.create(message.id, draft)

        with pytest.raises(sqlite3.IntegrityError):
            repository.create(message.id, draft)

        assert connection.in_transaction is False
        other_connection = connect(database_url)
        try:
            SessionRepository(other_connection).create("write after failed expression plan")
        finally:
            other_connection.close()


def test_expression_plan_is_deleted_with_its_message(tmp_path: Path) -> None:
    from app.repositories.expression_plans import ExpressionPlanRepository

    database_url = f"sqlite:///{tmp_path / 'cascade.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("cascade")
        message = MessageRepository(connection).add(session.id, ChatRole.ASSISTANT, "reply")
        repository = ExpressionPlanRepository(connection)
        repository.create(
            message.id,
            ExpressionPlanDraft(0, ExpressionDelivery.NEUTRAL, 1.0, ExpressionIntensity.LOW),
        )

        connection.execute("DELETE FROM messages WHERE id = ?", (message.id,))
        connection.commit()

        assert repository.get(message.id) is None


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("schema_version", 0),
        ("schema_version", 1.5),
        ("source_emotion_version", -1),
        ("source_emotion_version", 1.5),
        ("rate", 0.89),
        ("rate", 1.11),
        ("delivery", "unknown"),
        ("intensity", "high"),
    ],
)
def test_expression_plan_database_rejects_invalid_v1_values(
    tmp_path: Path,
    column: str,
    value: int | float | str,
) -> None:
    database_url = f"sqlite:///{tmp_path / f'bad-{column}-{value}.db'}"
    with managed_connection(database_url) as connection:
        session = SessionRepository(connection).create("constraints")
        message = MessageRepository(connection).add(session.id, ChatRole.ASSISTANT, "reply")
        row = {
            "id": "bad-plan",
            "assistant_message_id": message.id,
            "schema_version": 1,
            "source_emotion_version": 0,
            "delivery": "neutral",
            "rate": 1.0,
            "intensity": "low",
            "created_at": "2026-07-14T00:00:00+00:00",
        }
        row[column] = value

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO expression_plans (
                    id, assistant_message_id, schema_version, source_emotion_version,
                    delivery, rate, intensity, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(row.values()),
            )
