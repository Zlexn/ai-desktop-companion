from datetime import UTC, datetime

from app.domain.models import (
    EMOTION_BUCKET_HIGH_MIN,
    EMOTION_BUCKET_LOW_MAX,
    EmotionState,
    EmotionVector,
)
from app.services.emotion_context import EmotionContextFormatter, MAX_EMOTION_CONTEXT_CHARACTERS


def state(vector: EmotionVector, *, enabled: bool = True) -> EmotionState:
    return EmotionState("default-companion", enabled, vector, 1, datetime.now(UTC))


def test_formatter_is_deterministic_bounded_and_safe() -> None:
    value = state(EmotionVector(0.5, 0.4, 0.2, 0.55, 0.1, 0.6))
    formatter = EmotionContextFormatter()
    first = formatter.format(value)
    assert first == formatter.format(value)
    assert first is not None
    assert len(first) <= MAX_EMOTION_CONTEXT_CHARACTERS
    assert "表达策略" in first
    assert "不代表真实感情或意识" in first
    assert "不得改变事实、安全要求、用户明确指令或角色边界" in first
    assert "0.50" not in first and "0.40" not in first


def test_formatter_maps_extremes_to_discrete_labels() -> None:
    low = EmotionContextFormatter().format(state(EmotionVector(0, 0, 0, 0, 0, 0)))
    high = EmotionContextFormatter().format(state(EmotionVector(1, 1, 1, 1, 1, 1)))
    assert low is not None and "严肃低沉" in low and "保持谨慎" in low and "较为亲近" in low
    assert high is not None and "明快" in high and "较为信赖" in high and "保持距离" in high


def test_formatter_uses_shared_bucket_boundaries() -> None:
    below_low = EmotionContextFormatter().format(
        state(EmotionVector(EMOTION_BUCKET_LOW_MAX - 0.01, 0.4, 0.2, 0.55, 0.1, 0.6))
    )
    at_low = EmotionContextFormatter().format(
        state(EmotionVector(EMOTION_BUCKET_LOW_MAX, 0.4, 0.2, 0.55, 0.1, 0.6))
    )
    below_high = EmotionContextFormatter().format(
        state(EmotionVector(EMOTION_BUCKET_HIGH_MIN - 0.01, 0.4, 0.2, 0.55, 0.1, 0.6))
    )
    at_high = EmotionContextFormatter().format(
        state(EmotionVector(EMOTION_BUCKET_HIGH_MIN, 0.4, 0.2, 0.55, 0.1, 0.6))
    )

    assert below_low is not None and "语气严肃低沉" in below_low
    assert at_low is not None and "语气平稳" in at_low
    assert below_high is not None and "语气平稳" in below_high
    assert at_high is not None and "语气明快" in at_high


def test_disabled_state_has_no_context() -> None:
    assert EmotionContextFormatter().format(state(EmotionVector(0.5, 0.4, 0.2, 0.55, 0.1, 0.6), enabled=False)) is None
