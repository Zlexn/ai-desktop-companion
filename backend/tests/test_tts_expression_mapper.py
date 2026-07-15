from app.domain.models import ExpressionDelivery, ExpressionIntensity
from app.tts.expression_mapper import (
    MappedTTSRequest,
    TTSExpressionMapper,
    TTSExpressionRequest,
)


def test_expression_mapper_outputs_only_existing_tts_inputs() -> None:
    mapped = TTSExpressionMapper().map(
        TTSExpressionRequest(
            text="persisted reply",
            voice_id="fake-default",
            rate=1.04,
            delivery=ExpressionDelivery.WARM,
            intensity=ExpressionIntensity.MEDIUM,
        )
    )

    assert mapped == MappedTTSRequest("persisted reply", "fake-default", 1.04)
    assert not hasattr(mapped, "delivery")
    assert not hasattr(mapped, "intensity")
    assert not hasattr(mapped, "style")
    assert not hasattr(mapped, "provider_options")
