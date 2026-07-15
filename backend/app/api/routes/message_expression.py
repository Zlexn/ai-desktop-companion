from fastapi import APIRouter, Depends

from app.api.dependencies import get_expression_query_service
from app.core.errors import AppError, InternalServerError
from app.domain.schemas import MessageExpressionResponse
from app.services.expression_plan_service import ExpressionPlanService

router = APIRouter(prefix="/api/messages", tags=["expression"])


@router.get(
    "/{assistant_message_id}/expression",
    response_model=MessageExpressionResponse,
)
def get_message_expression(
    assistant_message_id: str,
    service: ExpressionPlanService = Depends(get_expression_query_service),
) -> MessageExpressionResponse:
    try:
        lookup = service.get_for_assistant_message(assistant_message_id)
    except AppError:
        raise
    except Exception as exc:
        raise InternalServerError() from exc
    return MessageExpressionResponse(
        assistant_message_id=lookup.assistant_message_id,
        schema_version=lookup.schema_version,
        delivery=lookup.expression.delivery.value,
        intensity=lookup.expression.intensity.value,
        rate=lookup.expression.rate,
        source=lookup.source.value,
    )
