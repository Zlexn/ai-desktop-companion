from dataclasses import dataclass

from app.domain.models import ExpressionDelivery, ExpressionIntensity


@dataclass(frozen=True)
class TTSExpressionRequest:
    text: str
    voice_id: str | None
    rate: float
    delivery: ExpressionDelivery
    intensity: ExpressionIntensity


@dataclass(frozen=True)
class MappedTTSRequest:
    text: str
    voice_id: str | None
    speed: float


class TTSExpressionMapper:
    def map(self, request: TTSExpressionRequest) -> MappedTTSRequest:
        return MappedTTSRequest(request.text, request.voice_id, request.rate)
