import sqlite3

from app.core.errors import ExpressionMessageRoleError, NotFoundError, ValidationAppError
from app.domain.models import (
    EXPRESSION_PLAN_SCHEMA_VERSION,
    ChatRole,
    EmotionState,
    ExpressionDelivery,
    ExpressionIntensity,
    ExpressionPlan,
    ExpressionPlanLookup,
    ExpressionPlanSource,
    ResolvedExpression,
)
from app.repositories.expression_plans import ExpressionPlanRepository
from app.repositories.messages import MessageRepository
from app.services.expression_plan_policy import ExpressionPlanPolicy

DEFAULT_EXPRESSION = ResolvedExpression(
    delivery=ExpressionDelivery.NEUTRAL,
    rate=1.0,
    intensity=ExpressionIntensity.LOW,
)


class ExpressionPlanService:
    def __init__(
        self,
        messages: MessageRepository,
        plans: ExpressionPlanRepository,
        policy: ExpressionPlanPolicy,
    ) -> None:
        self._messages = messages
        self._plans = plans
        self._policy = policy

    def create_for_assistant_message(
        self,
        assistant_message_id: str,
        snapshot: EmotionState | None,
    ) -> ExpressionPlan | None:
        message = self._messages.get(assistant_message_id)
        if message is None:
            raise NotFoundError("消息不存在。")
        if message.role is not ChatRole.ASSISTANT:
            raise ValidationAppError("只能为助手消息创建表达计划。")
        if snapshot is None:
            return None
        draft = self._policy.create_draft(snapshot)
        if draft is None:
            return None
        existing = self._plans.get(assistant_message_id)
        if existing is not None:
            return existing
        try:
            return self._plans.create(assistant_message_id, draft)
        except sqlite3.IntegrityError:
            existing = self._plans.get(assistant_message_id)
            if existing is not None:
                return existing
            raise

    def get_for_assistant_message(
        self,
        assistant_message_id: str,
    ) -> ExpressionPlanLookup:
        message = self._messages.get(assistant_message_id)
        if message is None:
            raise NotFoundError("消息不存在。")
        if message.role is not ChatRole.ASSISTANT:
            raise ExpressionMessageRoleError()

        try:
            plan = self._plans.get(
                message.id,
                schema_version=EXPRESSION_PLAN_SCHEMA_VERSION,
            )
            if plan is None:
                expression = DEFAULT_EXPRESSION
                source = ExpressionPlanSource.DEFAULT
            else:
                expression = ResolvedExpression(
                    plan.delivery,
                    plan.rate,
                    plan.intensity,
                )
                source = ExpressionPlanSource.PERSISTED_PLAN
        except (TypeError, ValueError, OverflowError):
            expression = DEFAULT_EXPRESSION
            source = ExpressionPlanSource.DEFAULT

        return ExpressionPlanLookup(
            assistant_message_id=message.id,
            schema_version=EXPRESSION_PLAN_SCHEMA_VERSION,
            expression=expression,
            source=source,
        )

    def resolve_compatible_or_default(self, assistant_message_id: str) -> ResolvedExpression:
        try:
            plan = self._plans.get(assistant_message_id)
        except ValueError:
            return DEFAULT_EXPRESSION
        if plan is None:
            return DEFAULT_EXPRESSION
        try:
            return ResolvedExpression(plan.delivery, plan.rate, plan.intensity)
        except ValueError:
            return DEFAULT_EXPRESSION
