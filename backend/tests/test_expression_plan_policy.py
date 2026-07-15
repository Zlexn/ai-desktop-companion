import math
from datetime import UTC, datetime

import pytest

from app.domain.models import (
    DEFAULT_EMOTION_SCOPE_ID,
    EMOTION_BASELINE,
    EmotionState,
    EmotionVector,
    ExpressionDelivery,
    ExpressionIntensity,
)
from app.services.expression_plan_policy import ExpressionPlanPolicy


def now() -> datetime:
    return datetime.now(UTC)


@pytest.mark.parametrize(
    ("vector", "expected"),
    [
        (
            EmotionVector(0.5, 0.8, 0.67, 0.2, 0.8, 0.8),
            (ExpressionDelivery.REASSURING, 0.94, ExpressionIntensity.MEDIUM),
        ),
        (
            EmotionVector(0.5, 0.8, 0.2, 0.2, 0.67, 0.67),
            (ExpressionDelivery.FIRM, 0.94, ExpressionIntensity.MEDIUM),
        ),
        (
            EmotionVector(0.5, 0.67, 0.2, 0.33, 0.1, 0.2),
            (ExpressionDelivery.WARM, 1.04, ExpressionIntensity.MEDIUM),
        ),
        (
            EmotionVector(0.5, 0.4, 0.2, 0.67, 0.1, 0.2),
            (ExpressionDelivery.RESERVED, 0.94, ExpressionIntensity.LOW),
        ),
        (
            EMOTION_BASELINE,
            (ExpressionDelivery.NEUTRAL, 1.0, ExpressionIntensity.LOW),
        ),
    ],
)
def test_expression_plan_policy_uses_ordered_bounded_table(
    vector: EmotionVector,
    expected: tuple[ExpressionDelivery, float, ExpressionIntensity],
) -> None:
    snapshot = EmotionState(DEFAULT_EMOTION_SCOPE_ID, True, vector, 9, now())

    draft = ExpressionPlanPolicy().create_draft(snapshot)

    assert draft is not None
    assert (draft.delivery, draft.rate, draft.intensity) == expected
    assert draft.source_emotion_version == 9


def test_expression_plan_policy_is_deterministic() -> None:
    snapshot = EmotionState(
        DEFAULT_EMOTION_SCOPE_ID,
        True,
        EmotionVector(0.5, 0.67, 0.2, 0.33, 0.1, 0.2),
        4,
        now(),
    )
    policy = ExpressionPlanPolicy()

    assert policy.create_draft(snapshot) == policy.create_draft(snapshot)


@pytest.mark.parametrize(
    "snapshot",
    [
        EmotionState(DEFAULT_EMOTION_SCOPE_ID, False, EMOTION_BASELINE, 0, now()),
        EmotionState(DEFAULT_EMOTION_SCOPE_ID, True, EMOTION_BASELINE, -1, now()),
        EmotionState(
            DEFAULT_EMOTION_SCOPE_ID,
            True,
            EmotionVector(math.nan, 0.4, 0.2, 0.55, 0.1, 0.6),
            0,
            now(),
        ),
        EmotionState(
            DEFAULT_EMOTION_SCOPE_ID,
            True,
            EmotionVector(math.inf, 0.4, 0.2, 0.55, 0.1, 0.6),
            0,
            now(),
        ),
        EmotionState(
            DEFAULT_EMOTION_SCOPE_ID,
            True,
            EmotionVector(-0.01, 0.4, 0.2, 0.55, 0.1, 0.6),
            0,
            now(),
        ),
        EmotionState(
            DEFAULT_EMOTION_SCOPE_ID,
            True,
            EmotionVector(1.01, 0.4, 0.2, 0.55, 0.1, 0.6),
            0,
            now(),
        ),
    ],
)
def test_expression_plan_policy_rejects_disabled_or_invalid_state(snapshot: EmotionState) -> None:
    assert ExpressionPlanPolicy().create_draft(snapshot) is None
