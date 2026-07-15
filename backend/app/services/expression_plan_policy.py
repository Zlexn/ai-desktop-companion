import math

from app.domain.models import (
    EMOTION_BUCKET_HIGH_MIN,
    EMOTION_BUCKET_LOW_MAX,
    EmotionState,
    ExpressionDelivery,
    ExpressionIntensity,
    ExpressionPlanDraft,
)


class ExpressionPlanPolicy:
    def create_draft(self, snapshot: EmotionState) -> ExpressionPlanDraft | None:
        if not snapshot.enabled or type(snapshot.version) is not int or snapshot.version < 0:
            return None
        if any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in snapshot.vector.values()
        ):
            return None

        vector = snapshot.vector
        if vector.concern >= EMOTION_BUCKET_HIGH_MIN:
            delivery, rate, intensity = (
                ExpressionDelivery.REASSURING,
                0.94,
                ExpressionIntensity.MEDIUM,
            )
        elif (
            vector.irritation >= EMOTION_BUCKET_HIGH_MIN
            and vector.formality >= EMOTION_BUCKET_HIGH_MIN
        ):
            delivery, rate, intensity = (
                ExpressionDelivery.FIRM,
                0.94,
                ExpressionIntensity.MEDIUM,
            )
        elif vector.trust >= EMOTION_BUCKET_HIGH_MIN and vector.distance < EMOTION_BUCKET_LOW_MAX:
            delivery, rate, intensity = (
                ExpressionDelivery.WARM,
                1.04,
                ExpressionIntensity.MEDIUM,
            )
        elif vector.distance >= EMOTION_BUCKET_HIGH_MIN or vector.formality >= EMOTION_BUCKET_HIGH_MIN:
            delivery, rate, intensity = (
                ExpressionDelivery.RESERVED,
                0.94,
                ExpressionIntensity.LOW,
            )
        else:
            delivery, rate, intensity = (
                ExpressionDelivery.NEUTRAL,
                1.0,
                ExpressionIntensity.LOW,
            )
        return ExpressionPlanDraft(snapshot.version, delivery, rate, intensity)
