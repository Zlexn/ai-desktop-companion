from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_persona_service
from app.domain.persona import PersonaArtifact, PersonaPayloadState
from app.domain.schemas import (
    PersonaActivateRequest,
    PersonaArtifactResponse,
    PersonaCapabilitiesResponse,
    PersonaCreateRequest,
    PersonaRedactRequest,
    PersonaRedactResponse,
)
from app.services.persona_service import PersonaActivationResult, PersonaService
from app.core.errors import ValidationAppError


router = APIRouter(prefix="/api/persona", tags=["persona"])


def _response(
    artifact: PersonaArtifact,
    *,
    active_artifact_id: str,
    activation_generation: int,
    outcome: str | None = None,
) -> PersonaArtifactResponse:
    usable = artifact.payload_state is PersonaPayloadState.ACTIVE
    return PersonaArtifactResponse(
        id=artifact.id,
        version=artifact.version,
        payload_state=artifact.payload_state.value,
        schema_version=artifact.schema_version,
        ruleset_version=artifact.ruleset_version,
        template_version=artifact.template_version,
        compiler_version=artifact.compiler_version,
        config=artifact.source_content if usable else None,
        created_at=artifact.created_at,
        redacted_at=artifact.redacted_at,
        active=artifact.id == active_artifact_id,
        activation_generation=activation_generation,
        fingerprint_prefix=(artifact.behavior_fingerprint[:12] if usable else None),
        outcome=outcome,
    )


def _activation_response(
    result: PersonaActivationResult,
) -> PersonaArtifactResponse:
    return _response(
        result.artifact,
        active_artifact_id=result.active.artifact_id,
        activation_generation=result.active.activation_generation,
        outcome=result.outcome,
    )


@router.get("/current", response_model=PersonaArtifactResponse)
def current(
    service: PersonaService = Depends(get_persona_service),
) -> PersonaArtifactResponse:
    return _activation_response(service.current())


@router.get("/artifacts", response_model=list[PersonaArtifactResponse])
def list_artifacts(
    service: PersonaService = Depends(get_persona_service),
) -> list[PersonaArtifactResponse]:
    current_result = service.current()
    return [
        _response(
            artifact,
            active_artifact_id=current_result.active.artifact_id,
            activation_generation=current_result.active.activation_generation,
        )
        for artifact in service.list_artifacts()
    ]


@router.get("/artifacts/{artifact_id}", response_model=PersonaArtifactResponse)
def artifact_detail(
    artifact_id: str,
    service: PersonaService = Depends(get_persona_service),
) -> PersonaArtifactResponse:
    current_result = service.current()
    artifact = service.artifact(artifact_id)
    return _response(
        artifact,
        active_artifact_id=current_result.active.artifact_id,
        activation_generation=current_result.active.activation_generation,
    )


@router.post("/artifacts", response_model=PersonaArtifactResponse)
def create_artifact(
    request: PersonaCreateRequest,
    service: PersonaService = Depends(get_persona_service),
) -> PersonaArtifactResponse:
    try:
        result = service.create_and_activate(
            request.config.model_dump(),
            request.expected_artifact_id,
            request.expected_generation,
        )
    except ValueError as exc:
        raise ValidationAppError("角色配置内容无效。") from exc
    return _activation_response(result)


@router.post("/active", response_model=PersonaArtifactResponse)
def activate_artifact(
    request: PersonaActivateRequest,
    service: PersonaService = Depends(get_persona_service),
) -> PersonaArtifactResponse:
    result = service.activate(
        request.artifact_id,
        request.expected_artifact_id,
        request.expected_generation,
    )
    return _activation_response(result)


@router.post(
    "/artifacts/{artifact_id}/redact",
    response_model=PersonaRedactResponse,
)
def redact_artifact(
    artifact_id: str,
    request: PersonaRedactRequest,
    service: PersonaService = Depends(get_persona_service),
) -> PersonaRedactResponse:
    try:
        result = service.redact(
            artifact_id,
            expected_artifact_id=request.expected_artifact_id,
            expected_generation=request.expected_generation,
            replacement_artifact_id=request.replacement_artifact_id,
            replacement_config=(
                request.replacement_config.model_dump()
                if request.replacement_config is not None
                else None
            ),
            confirmation=request.confirmation,
        )
    except ValueError as exc:
        raise ValidationAppError("角色配置内容无效。") from exc
    active_artifact = service.current().artifact
    return PersonaRedactResponse(
        redacted=_response(
            result.redacted,
            active_artifact_id=result.active.artifact_id,
            activation_generation=result.active.activation_generation,
        ),
        active=_response(
            active_artifact,
            active_artifact_id=result.active.artifact_id,
            activation_generation=result.active.activation_generation,
        ),
    )


@router.get("/capabilities", response_model=PersonaCapabilitiesResponse)
def capabilities(request: Request) -> PersonaCapabilitiesResponse:
    return PersonaCapabilitiesResponse(
        persona_artifacts=True,
        context_composer=True,
        summary_processing=bool(
            getattr(request.app.state, "summary_processing_available", False)
        ),
        summary_injection=bool(
            getattr(request.app.state, "summary_injection_available", False)
        ),
        relationship_projection=False,
        remote_summary=getattr(
            request.app.state,
            "remote_summary_capability",
            "not_configured",
        ),
    )
