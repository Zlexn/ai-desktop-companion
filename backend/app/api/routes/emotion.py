from fastapi import APIRouter, Depends, Query

from app.api.dependencies import (
    get_emotion_analysis_dispatch_fence,
    get_emotion_analysis_repository,
    get_emotion_service,
)
from app.core.config import Settings, get_settings
from app.domain.models import (
    EmotionAnalysisAudit,
    EmotionAnalysisConsent,
    EmotionAnalysisConsentStatus,
    EmotionEvent,
    EmotionState,
    EmotionVector,
)
from app.domain.schemas import (
    EmotionAnalysisAuditResponse,
    EmotionAnalysisConsentResponse,
    EmotionEventResponse,
    EmotionStateResponse,
    EmotionVectorResponse,
    UpdateEmotionAnalysisConsentRequest,
    UpdateEmotionSettingsRequest,
)
from app.repositories.emotion_analysis import EmotionAnalysisRepository
from app.services.emotion_analysis_dispatch import EmotionAnalysisDispatchFence
from app.services.emotion_service import EmotionService

router = APIRouter(prefix="/api/emotion", tags=["emotion"])


def _vector_response(vector: EmotionVector) -> EmotionVectorResponse:
    return EmotionVectorResponse(
        mood=vector.mood,
        trust=vector.trust,
        concern=vector.concern,
        distance=vector.distance,
        irritation=vector.irritation,
        formality=vector.formality,
    )


def _state_response(state: EmotionState) -> EmotionStateResponse:
    return EmotionStateResponse(
        scope_id=state.scope_id,
        enabled=state.enabled,
        vector=_vector_response(state.vector),
        version=state.version,
        updated_at=state.updated_at,
    )


def _event_response(event: EmotionEvent) -> EmotionEventResponse:
    return EmotionEventResponse(
        id=event.id,
        event_type=event.event_type.value,
        before=_vector_response(event.before),
        after=_vector_response(event.after),
        applied_delta=_vector_response(event.applied_delta),
        reason_codes=list(event.reason_codes),
        source_session_id=event.source_session_id,
        source_user_message_id=event.source_user_message_id,
        source_assistant_message_id=event.source_assistant_message_id,
        engine=event.engine,
        rule_version=event.rule_version,
        created_at=event.created_at,
    )


def _consent_response(
    consent: EmotionAnalysisConsent,
    settings: Settings,
) -> EmotionAnalysisConsentResponse:
    return EmotionAnalysisConsentResponse(
        scope_id=consent.scope_id,
        status=consent.status.value,
        disclosure_version=consent.disclosure_version,
        provider=consent.provider,
        deployment_provider=settings.emotion_analysis_provider,
        deployment_enabled=settings.emotion_analysis_enabled,
        updated_at=consent.updated_at,
    )


def _audit_response(audit: EmotionAnalysisAudit) -> EmotionAnalysisAuditResponse:
    return EmotionAnalysisAuditResponse(
        id=audit.id,
        job_id=audit.job_id,
        outcome=audit.outcome.value,
        source_session_id=audit.source_session_id,
        source_user_message_id=audit.source_user_message_id,
        source_assistant_message_id=audit.source_assistant_message_id,
        schema_version=audit.schema_version,
        provider=audit.provider,
        model=audit.model,
        message_count=audit.message_count,
        memory_count=audit.memory_count,
        input_characters=audit.input_characters,
        redaction_count=audit.redaction_count,
        elapsed_ms=audit.elapsed_ms,
        reason_code=audit.reason_code,
        created_at=audit.created_at,
    )


@router.get("/analysis/consent", response_model=EmotionAnalysisConsentResponse)
def get_analysis_consent(
    repository: EmotionAnalysisRepository = Depends(get_emotion_analysis_repository),
    settings: Settings = Depends(get_settings),
) -> EmotionAnalysisConsentResponse:
    return _consent_response(repository.get_consent(), settings)


@router.put("/analysis/consent", response_model=EmotionAnalysisConsentResponse)
async def update_analysis_consent(
    request: UpdateEmotionAnalysisConsentRequest,
    repository: EmotionAnalysisRepository = Depends(get_emotion_analysis_repository),
    settings: Settings = Depends(get_settings),
    dispatch_fence: EmotionAnalysisDispatchFence = Depends(
        get_emotion_analysis_dispatch_fence
    ),
) -> EmotionAnalysisConsentResponse:
    status_by_action = {
        "grant": EmotionAnalysisConsentStatus.GRANTED,
        "decline": EmotionAnalysisConsentStatus.DECLINED,
        "revoke": EmotionAnalysisConsentStatus.REVOKED,
    }
    mutation = dispatch_fence.begin_consent_mutation()
    async with mutation:
        consent = repository.set_consent(
            status=status_by_action[request.action],
            disclosure_version=request.disclosure_version,
            provider=settings.emotion_analysis_provider,
            policy_fingerprint=settings.emotion_analysis_policy_fingerprint(),
        )
    return _consent_response(consent, settings)


@router.get("/analysis/audits", response_model=list[EmotionAnalysisAuditResponse])
def list_analysis_audits(
    limit: int = Query(default=20, ge=1, le=100),
    repository: EmotionAnalysisRepository = Depends(get_emotion_analysis_repository),
) -> list[EmotionAnalysisAuditResponse]:
    return [_audit_response(audit) for audit in repository.list_audits(limit=limit)]


@router.get("/state", response_model=EmotionStateResponse)
def get_state(service: EmotionService = Depends(get_emotion_service)) -> EmotionStateResponse:
    return _state_response(service.get_state())


@router.get("/events", response_model=list[EmotionEventResponse])
def list_events(
    limit: int = Query(default=20, ge=1, le=100),
    service: EmotionService = Depends(get_emotion_service),
) -> list[EmotionEventResponse]:
    return [_event_response(event) for event in service.list_events(limit=limit)]


@router.patch("/settings", response_model=EmotionStateResponse)
def update_settings(
    request: UpdateEmotionSettingsRequest,
    service: EmotionService = Depends(get_emotion_service),
) -> EmotionStateResponse:
    return _state_response(service.set_enabled(request.enabled))


@router.post("/reset", response_model=EmotionStateResponse)
def reset(service: EmotionService = Depends(get_emotion_service)) -> EmotionStateResponse:
    return _state_response(service.reset())
