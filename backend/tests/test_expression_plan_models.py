import math

import pytest

from app.domain.models import (
    EXPRESSION_PLAN_SCHEMA_VERSION,
    ExpressionDelivery,
    ExpressionIntensity,
    ExpressionPlanDraft,
    ResolvedExpression,
)


def test_expression_plan_draft_accepts_only_bounded_v1_fields() -> None:
    draft = ExpressionPlanDraft(
        source_emotion_version=5,
        delivery=ExpressionDelivery.REASSURING,
        rate=0.94,
        intensity=ExpressionIntensity.MEDIUM,
    )

    assert EXPRESSION_PLAN_SCHEMA_VERSION == 1
    assert draft.source_emotion_version == 5
    assert draft.delivery is ExpressionDelivery.REASSURING
    assert draft.rate == 0.94
    assert draft.intensity is ExpressionIntensity.MEDIUM
    assert not hasattr(draft, "text")
    assert not hasattr(draft, "emotion_vector")
    assert not hasattr(draft, "provider_options")


@pytest.mark.parametrize("rate", [0.89, 1.11, math.nan, math.inf, -math.inf])
def test_expression_plan_draft_rejects_invalid_rate(rate: float) -> None:
    with pytest.raises(ValueError):
        ExpressionPlanDraft(
            source_emotion_version=0,
            delivery=ExpressionDelivery.NEUTRAL,
            rate=rate,
            intensity=ExpressionIntensity.LOW,
        )


def test_expression_plan_draft_rejects_negative_source_version() -> None:
    with pytest.raises(ValueError):
        ExpressionPlanDraft(
            source_emotion_version=-1,
            delivery=ExpressionDelivery.NEUTRAL,
            rate=1.0,
            intensity=ExpressionIntensity.LOW,
        )


@pytest.mark.parametrize("source_emotion_version", [1.0, True])
def test_expression_plan_draft_rejects_non_integer_source_version(
    source_emotion_version: float | bool,
) -> None:
    with pytest.raises(ValueError):
        ExpressionPlanDraft(
            source_emotion_version=source_emotion_version,  # type: ignore[arg-type]
            delivery=ExpressionDelivery.NEUTRAL,
            rate=1.0,
            intensity=ExpressionIntensity.LOW,
        )


@pytest.mark.parametrize("rate", [0.89, 1.11, math.nan, math.inf, -math.inf])
def test_resolved_expression_rejects_invalid_rate(rate: float) -> None:
    with pytest.raises(ValueError):
        ResolvedExpression(
            delivery=ExpressionDelivery.NEUTRAL,
            rate=rate,
            intensity=ExpressionIntensity.LOW,
        )
