import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.errors import ExpressionMessageRoleError, NotFoundError, ValidationAppError
from app.domain.models import (
    DEFAULT_EMOTION_SCOPE_ID,
    ChatRole,
    EmotionState,
    EmotionVector,
    ExpressionDelivery,
    ExpressionIntensity,
    ExpressionPlan,
    ExpressionPlanDraft,
    ExpressionPlanSource,
)
from app.repositories.expression_plans import ExpressionPlanRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.expression_plan_policy import ExpressionPlanPolicy
from app.services.expression_plan_service import ExpressionPlanService


def snapshot(vector: EmotionVector, *, version: int = 1, enabled: bool = True) -> EmotionState:
    return EmotionState(DEFAULT_EMOTION_SCOPE_ID, enabled, vector, version, datetime.now(UTC))


def test_create_for_assistant_message_is_idempotent(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'idempotent.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        plans = ExpressionPlanRepository(connection)
        session = sessions.create("plans")
        assistant = messages.add(session.id, ChatRole.ASSISTANT, "reply")
        service = ExpressionPlanService(messages, plans, ExpressionPlanPolicy())
        warm = snapshot(EmotionVector(0.5, 0.8, 0.2, 0.2, 0.1, 0.2), version=3)
        reassuring = snapshot(EmotionVector(0.5, 0.8, 0.8, 0.2, 0.1, 0.2), version=4)

        first = service.create_for_assistant_message(assistant.id, warm)
        second = service.create_for_assistant_message(assistant.id, reassuring)

        assert first is not None
        assert second == first
        assert second.source_emotion_version == 3
        assert second.delivery is ExpressionDelivery.WARM


def test_create_for_assistant_message_rejects_unknown_and_user_messages(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'roles.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("roles")
        user = messages.add(session.id, ChatRole.USER, "hello")
        service = ExpressionPlanService(
            messages,
            ExpressionPlanRepository(connection),
            ExpressionPlanPolicy(),
        )
        value = snapshot(EmotionVector(0.5, 0.4, 0.2, 0.55, 0.1, 0.6))

        with pytest.raises(NotFoundError):
            service.create_for_assistant_message("missing", value)
        with pytest.raises(ValidationAppError):
            service.create_for_assistant_message(user.id, value)


@pytest.mark.parametrize("value", [None, snapshot(EmotionVector(0.5, 0.4, 0.2, 0.55, 0.1, 0.6), enabled=False)])
def test_create_for_assistant_message_skips_absent_or_disabled_snapshot(
    tmp_path: Path,
    value: EmotionState | None,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'skip.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        plans = ExpressionPlanRepository(connection)
        session = sessions.create("skip")
        assistant = messages.add(session.id, ChatRole.ASSISTANT, "reply")
        service = ExpressionPlanService(messages, plans, ExpressionPlanPolicy())

        assert service.create_for_assistant_message(assistant.id, value) is None
        assert plans.get(assistant.id) is None


def test_create_for_assistant_message_returns_existing_plan_after_unique_race() -> None:
    existing = ExpressionPlan(
        id="plan-1",
        assistant_message_id="assistant-1",
        schema_version=1,
        source_emotion_version=8,
        delivery=ExpressionDelivery.WARM,
        rate=1.04,
        intensity=ExpressionIntensity.MEDIUM,
        created_at=datetime.now(UTC),
    )

    class Messages:
        def get(self, message_id: str):
            return type("Message", (), {"id": message_id, "role": ChatRole.ASSISTANT})()

    class RacingPlans:
        def __init__(self) -> None:
            self.reads = 0

        def get(self, assistant_message_id: str) -> ExpressionPlan | None:
            self.reads += 1
            return None if self.reads == 1 else existing

        def create(self, assistant_message_id: str, draft):
            raise sqlite3.IntegrityError("unique race")

    service = ExpressionPlanService(Messages(), RacingPlans(), ExpressionPlanPolicy())  # type: ignore[arg-type]

    result = service.create_for_assistant_message(
        "assistant-1",
        snapshot(EmotionVector(0.5, 0.8, 0.2, 0.2, 0.1, 0.2), version=9),
    )

    assert result == existing


def test_lookup_returns_persisted_v1_plan(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'lookup.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        plans = ExpressionPlanRepository(connection)
        assistant = messages.add(sessions.create("lookup").id, ChatRole.ASSISTANT, "reply")
        service = ExpressionPlanService(messages, plans, ExpressionPlanPolicy())
        created = service.create_for_assistant_message(
            assistant.id,
            snapshot(EmotionVector(0.5, 0.8, 0.8, 0.2, 0.1, 0.2), version=7),
        )

        lookup = service.get_for_assistant_message(assistant.id)

        assert created is not None
        assert lookup.assistant_message_id == assistant.id
        assert lookup.schema_version == 1
        assert lookup.source is ExpressionPlanSource.PERSISTED_PLAN
        assert lookup.expression.delivery is created.delivery
        assert lookup.expression.rate == created.rate
        assert lookup.expression.intensity is created.intensity


def test_lookup_returns_default_without_writing(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'history.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        plans = ExpressionPlanRepository(connection)
        assistant = messages.add(sessions.create("history").id, ChatRole.ASSISTANT, "old reply")
        service = ExpressionPlanService(messages, plans, ExpressionPlanPolicy())

        first = service.get_for_assistant_message(assistant.id)
        second = service.get_for_assistant_message(assistant.id)

        assert first == second
        assert first.source is ExpressionPlanSource.DEFAULT
        assert first.expression.delivery is ExpressionDelivery.NEUTRAL
        assert first.expression.intensity is ExpressionIntensity.LOW
        assert first.expression.rate == 1.0
        assert plans.get(assistant.id) is None


def test_lookup_rejects_missing_and_user_messages(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'lookup-roles.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        user = messages.add(sessions.create("roles").id, ChatRole.USER, "hello")
        service = ExpressionPlanService(messages, ExpressionPlanRepository(connection), ExpressionPlanPolicy())

        with pytest.raises(NotFoundError):
            service.get_for_assistant_message("missing")
        with pytest.raises(ExpressionMessageRoleError):
            service.get_for_assistant_message(user.id)


def test_lookup_returns_default_when_only_future_schema_exists(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'future-schema.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        plans = ExpressionPlanRepository(connection)
        assistant = messages.add(sessions.create("future").id, ChatRole.ASSISTANT, "reply")
        future = plans.create(
            assistant.id,
            ExpressionPlanDraft(
                source_emotion_version=7,
                delivery=ExpressionDelivery.FIRM,
                rate=1.05,
                intensity=ExpressionIntensity.MEDIUM,
            ),
            schema_version=2,
        )
        service = ExpressionPlanService(messages, plans, ExpressionPlanPolicy())

        lookup = service.get_for_assistant_message(assistant.id)

        assert lookup.source is ExpressionPlanSource.DEFAULT
        assert lookup.expression.delivery is ExpressionDelivery.NEUTRAL
        assert plans.get(assistant.id, schema_version=2) == future
        assert plans.get(assistant.id, schema_version=1) is None


def test_lookup_defaults_for_corrupt_plan_but_not_for_database_failure() -> None:
    assistant = type("Message", (), {"id": "assistant-1", "role": ChatRole.ASSISTANT})()

    class Messages:
        def get(self, _message_id: str):
            return assistant

    class CorruptPlans:
        def get(self, _message_id: str, *, schema_version: int = 1):
            assert schema_version == 1
            raise ValueError("corrupt enum")

    class BrokenPlans:
        def get(self, _message_id: str, *, schema_version: int = 1):
            assert schema_version == 1
            raise sqlite3.OperationalError("database unavailable")

    corrupt = ExpressionPlanService(Messages(), CorruptPlans(), ExpressionPlanPolicy())  # type: ignore[arg-type]
    broken = ExpressionPlanService(Messages(), BrokenPlans(), ExpressionPlanPolicy())  # type: ignore[arg-type]

    assert corrupt.get_for_assistant_message("assistant-1").source is ExpressionPlanSource.DEFAULT
    with pytest.raises(sqlite3.OperationalError):
        broken.get_for_assistant_message("assistant-1")


def test_resolve_returns_default_without_writing_for_missing_plan(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'default.db'}"
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        plans = ExpressionPlanRepository(connection)
        session = sessions.create("default")
        assistant = messages.add(session.id, ChatRole.ASSISTANT, "reply")
        service = ExpressionPlanService(messages, plans, ExpressionPlanPolicy())

        resolved = service.resolve_compatible_or_default(assistant.id)

        assert resolved.delivery is ExpressionDelivery.NEUTRAL
        assert resolved.rate == 1.0
        assert resolved.intensity is ExpressionIntensity.LOW
        assert not hasattr(resolved, "source_emotion_version")
        assert plans.get(assistant.id) is None


def test_resolve_returns_default_for_corrupt_plan_value() -> None:
    class CorruptPlans:
        def get(self, assistant_message_id: str):
            raise ValueError("corrupt enum")

    service = ExpressionPlanService(object(), CorruptPlans(), ExpressionPlanPolicy())  # type: ignore[arg-type]

    assert service.resolve_compatible_or_default("assistant-1").rate == 1.0


def test_resolve_does_not_swallow_connection_failures() -> None:
    class BrokenPlans:
        def get(self, assistant_message_id: str):
            raise sqlite3.OperationalError("database unavailable")

    service = ExpressionPlanService(object(), BrokenPlans(), ExpressionPlanPolicy())  # type: ignore[arg-type]

    with pytest.raises(sqlite3.OperationalError):
        service.resolve_compatible_or_default("assistant-1")
