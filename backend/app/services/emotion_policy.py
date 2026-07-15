import math
from dataclasses import dataclass
from datetime import datetime

from app.domain.models import EMOTION_BASELINE, EMOTION_MAX_DELTA, EmotionState, EmotionVector

RULE_VERSION = "emotion-rules-v1"


@dataclass(frozen=True)
class EmotionTransition:
    after: EmotionVector
    delta: EmotionVector
    reason_codes: tuple[str, ...]
    proposed_delta: EmotionVector = EmotionVector.zero()


class EmotionPolicy:
    def evaluate_turn(
        self,
        *,
        state: EmotionState,
        user_text: str,
        assistant_text: str,
        now: datetime,
    ) -> EmotionTransition:
        del assistant_text, now
        if not state.enabled:
            return EmotionTransition(state.vector, EmotionVector.zero(), ())

        text = user_text.strip().lower()
        proposed = EmotionVector.zero()
        reasons: list[str] = []
        if any(phrase in text for phrase in ("谢谢", "感谢", "辛苦了")):
            reasons.append("user_respectful_support")
            proposed = self._sum(proposed, EmotionVector(0.02, 0.03, 0, -0.02, -0.01, -0.01))
        if any(phrase in text for phrase in ("对不起", "抱歉", "是我不对")):
            reasons.append("user_explicit_apology")
            proposed = self._sum(proposed, EmotionVector(0.01, 0.02, 0, -0.01, -0.04, 0))
        if any(phrase in text for phrase in ("请不要", "别这样称呼", "停止这样")):
            reasons.append("user_clear_boundary")
            proposed = self._sum(proposed, EmotionVector(0, 0, 0, 0.03, 0, 0.04))
        if any(phrase in text for phrase in ("真蠢", "闭嘴", "废物", "滚开")):
            reasons.append("user_repeated_hostility")
            proposed = self._sum(proposed, EmotionVector(-0.04, -0.03, 0, 0.04, 0.06, 0.03))
        if any(phrase in text for phrase in ("很难受", "需要帮助", "救救我", "不舒服")):
            reasons.append("user_distress_signal")
            proposed = self._sum(proposed, EmotionVector(-0.01, 0, 0.08, -0.01, -0.02, 0))

        if not reasons:
            return EmotionTransition(state.vector, EmotionVector.zero(), ("neutral_turn",))
        after = self.apply_delta(state.vector, proposed)
        delta = self._difference(after, state.vector)
        return EmotionTransition(after, delta, tuple(dict.fromkeys(reasons)), proposed)

    def apply_delta(self, before: EmotionVector, proposed: EmotionVector) -> EmotionVector:
        if not all(math.isfinite(value) for value in (*before.values(), *proposed.values())):
            raise ValueError("emotion vectors must contain finite values")
        values = []
        for current, delta, cap in zip(before.values(), proposed.values(), EMOTION_MAX_DELTA.values(), strict=True):
            bounded_delta = min(max(delta, -cap), cap)
            values.append(round(min(max(current + bounded_delta, 0.0), 1.0), 6))
        return EmotionVector(*values)

    def decay(self, state: EmotionState, *, now: datetime) -> EmotionTransition:
        elapsed_seconds = max((now - state.updated_at).total_seconds(), 0.0)
        if elapsed_seconds < 3600:
            return EmotionTransition(state.vector, EmotionVector.zero(), ())
        if elapsed_seconds < 24 * 3600:
            temporary, relational = 0.10, 0.00
        elif elapsed_seconds < 7 * 24 * 3600:
            temporary, relational = 0.25, 0.01
        else:
            temporary, relational = 0.50, 0.03
        fractions = (temporary, relational, temporary, relational, temporary, temporary / 2)
        values = tuple(
            round(current + (baseline - current) * fraction, 6)
            for current, baseline, fraction in zip(
                state.vector.values(), EMOTION_BASELINE.values(), fractions, strict=True
            )
        )
        after = EmotionVector(*values)
        if after == state.vector:
            return EmotionTransition(after, EmotionVector.zero(), ())
        return EmotionTransition(after, self._difference(after, state.vector), ("time_decay",))

    @staticmethod
    def _sum(left: EmotionVector, right: EmotionVector) -> EmotionVector:
        return EmotionVector(*(a + b for a, b in zip(left.values(), right.values(), strict=True)))

    @staticmethod
    def _difference(after: EmotionVector, before: EmotionVector) -> EmotionVector:
        return EmotionVector(*(round(a - b, 6) for a, b in zip(after.values(), before.values(), strict=True)))
