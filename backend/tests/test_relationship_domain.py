from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime

import pytest

from app.domain.models import (
    MemoryRecordState,
    MemoryType,
    MemoryVersion,
    MemoryVersionOperation,
    MemoryVersionSourceKind,
)
from app.domain.relationship import (
    RelationshipAudit,
    RelationshipAuditAction,
    RelationshipAuthorityAction,
    RelationshipAuthorityActionKind,
    RelationshipAuthoritySnapshot,
    RelationshipEvent,
    RelationshipEventKind,
    RelationshipEventType,
    RelationshipPayloadState,
    RelationshipProjectionSnapshot,
    RelationshipProjectionView,
    RelationshipReconcileJob,
    RelationshipReconcileJobStatus,
    RelationshipReconcileOutcome,
    RelationshipSourceSnapshot,
    RelationshipSummaryCode,
)
from app.domain.schemas import (
    ConfirmMemoryCandidateRequest,
    CreateMemoryRequest,
    MemoryResponse,
    MemoryVersionResponse,
    ReplaceConflictRequest,
    UpdateMemoryRequest,
)


_NOW = datetime(2026, 7, 27, tzinfo=UTC)


def test_relationship_enums_are_frozen_to_gate_c3_values() -> None:
    assert [item.value for item in RelationshipEventKind] == ["apply", "revoke"]
    assert [item.value for item in RelationshipEventType] == [
        "preferred_address",
        "shared_experience",
        "non_external_commitment",
    ]
    assert [item.value for item in RelationshipPayloadState] == [
        "active",
        "redacted",
    ]
    assert [item.value for item in RelationshipAuthorityAction] == [
        "suppress",
        "reenable",
    ]
    assert [item.value for item in RelationshipAuthorityActionKind] == [
        "user_revoke",
        "privacy_redact",
        "user_reenable",
        "inherited_conflict_suppression",
    ]
    assert [item.value for item in RelationshipReconcileJobStatus] == [
        "pending",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        "skipped",
    ]
    assert [item.value for item in RelationshipReconcileOutcome] == [
        "applied",
        "revoked",
        "no_change",
        "skipped_ineligible",
        "skipped_suppressed",
        "stale_source",
        "stale_authority",
        "incompatible_recovery",
        "failed",
        "cancelled",
    ]
    assert [item.value for item in RelationshipSummaryCode] == [
        "reserved",
        "steady",
        "familiar",
        "close",
    ]


def _source_snapshot() -> RelationshipSourceSnapshot:
    return RelationshipSourceSnapshot(
        scope_id="default",
        source_memory_id="memory-1",
        source_memory_version_id="version-1",
        record_head_version=2,
        record_generation=3,
        record_state=MemoryRecordState.ACTIVE,
        memory_type=MemoryType.RELATIONSHIP_EVENT,
        canonical_subject_code="shared_experience",
        version_source_kind=MemoryVersionSourceKind.USER_EDIT,
        version_confidence=0.9,
        version_importance=4,
        version_created_at=_NOW,
        open_conflict=False,
        payload_redacted=False,
        effective_authority_decision_id=None,
        effective_authority_generation=0,
        authority_epoch=0,
        inherited_authority_fingerprint="a" * 64,
        authority_suppressed=False,
        relationship_rule_version="relationship-rules-v1",
        preferred_address_candidate=None,
    )


def test_relationship_domain_dataclasses_are_frozen_and_typed() -> None:
    source = _source_snapshot()
    event = RelationshipEvent(
        id="event-1",
        scope_id="default",
        event_kind=RelationshipEventKind.APPLY,
        event_type=RelationshipEventType.SHARED_EXPERIENCE,
        subject_code="shared_experience",
        payload_state=RelationshipPayloadState.ACTIVE,
        payload={
            "category": "shared_experience",
            "reason_code": "allowlisted_current_memory",
            "delta": 0.04,
        },
        source_memory_id="memory-1",
        source_memory_version_id="version-1",
        observed_at=_NOW,
        observed_time_derivation_version="memory-version-created-at-utc-v1",
        revokes_event_id=None,
        rule_version="relationship-rules-v1",
        persona_artifact_id="persona-1",
        event_schema_version="relationship-event-v1",
        integrity_fingerprint="b" * 64,
        created_at=_NOW,
    )
    authority = RelationshipAuthoritySnapshot(
        scope_id="default",
        source_memory_id="memory-1",
        event_type=RelationshipEventType.SHARED_EXPERIENCE,
        subject_code="shared_experience",
        decision_id=None,
        generation=0,
        action=None,
        authority_epoch=0,
        inherited_authority_fingerprint="c" * 64,
        suppressed=False,
    )
    projection = RelationshipProjectionSnapshot(
        projection_id="projection-1",
        version=1,
        scope_id="default",
        persona_artifact_id="persona-1",
        projection_rule_version="relationship-projection-v1",
        familiarity=0.44,
        preferred_address_event_id=None,
        relationship_summary_code=RelationshipSummaryCode.STEADY,
        source_relationship_event_ids=("event-1",),
        source_emotion_snapshot_id=None,
        computed_at=_NOW,
        integrity_fingerprint="d" * 64,
    )
    view = RelationshipProjectionView(
        projection_id="projection-1",
        projection_version=1,
        familiarity_bucket="steady",
        preferred_address=None,
        relationship_summary_code=RelationshipSummaryCode.STEADY,
        persona_artifact_id="persona-1",
        projection_rule_version="relationship-projection-v1",
        contributing_event_count=1,
    )
    job = RelationshipReconcileJob(
        id="job-1",
        scope_id="default",
        source_memory_id="memory-1",
        source_memory_version_id="version-1",
        status=RelationshipReconcileJobStatus.PENDING,
        outcome=None,
        captured_record_head_version=2,
        captured_record_generation=3,
        captured_record_state=MemoryRecordState.ACTIVE,
        captured_event_type=RelationshipEventType.SHARED_EXPERIENCE,
        captured_subject_code="shared_experience",
        captured_authority_decision_id=None,
        captured_authority_generation=0,
        captured_authority_epoch=0,
        captured_inherited_authority_fingerprint="e" * 64,
        relationship_rule_version="relationship-rules-v1",
        persona_artifact_id="persona-1",
        job_schema_version="relationship-reconcile-job-v1",
        attempt_count=0,
        reason_code=None,
        error_category=None,
        created_at=_NOW,
        started_at=None,
        finished_at=None,
    )
    audit = RelationshipAudit(
        id="audit-1",
        action=RelationshipAuditAction.RECONCILED,
        outcome=RelationshipReconcileOutcome.APPLIED,
        reason_code="eligible_apply",
        source_memory_id="memory-1",
        event_id="event-1",
        projection_id="projection-1",
        created_at=_NOW,
    )

    assert source.canonical_subject_code == "shared_experience"
    assert event.payload["delta"] == 0.04
    assert authority.suppressed is False
    assert projection.source_emotion_snapshot_id is None
    assert view.contributing_event_count == 1
    assert job.outcome is None
    assert audit.action is RelationshipAuditAction.RECONCILED
    with pytest.raises(FrozenInstanceError):
        view.preferred_address = "mutated"  # type: ignore[misc]


def test_public_relationship_projection_view_omits_private_sources() -> None:
    public_names = {item.name for item in fields(RelationshipProjectionView)}
    assert public_names == {
        "projection_id",
        "projection_version",
        "familiarity_bucket",
        "preferred_address",
        "relationship_summary_code",
        "persona_artifact_id",
        "projection_rule_version",
        "contributing_event_count",
    }
    forbidden = {
        "source_set_hash",
        "canonical_key_hash",
        "content_hash",
        "source_memory_id",
        "source_memory_version_id",
        "source_relationship_event_ids",
        "inherited_authority_fingerprint",
        "integrity_fingerprint",
        "prompt",
        "raw_response",
        "hmac",
        "asset_path",
    }
    assert public_names.isdisjoint(forbidden)


def test_memory_version_contract_has_nullable_canonical_subject_code() -> None:
    version = MemoryVersion(
        id="version-1",
        memory_id="memory-1",
        version_number=1,
        parent_version_id=None,
        operation=MemoryVersionOperation.CREATE,
        memory_type=MemoryType.RELATIONSHIP_EVENT,
        subject="shared experience",
        content="一起看过雪",
        content_hash="hash",
        canonical_key_hash=None,
        subject_key_hash=None,
        canonicalization_version="memory-canonicalization-v1",
        confidence=0.9,
        importance=4,
        source_kind=MemoryVersionSourceKind.MANUAL,
        source_session_id=None,
        source_session_reference_hash=None,
        writer_policy_version="manual-write-v1",
        created_at=_NOW,
        redacted_at=None,
        canonical_subject_code="shared_experience",
    )

    assert version.canonical_subject_code == "shared_experience"
    assert MemoryVersion(
        **{
            **version.__dict__,
            "canonical_subject_code": None,
        }
    ).canonical_subject_code is None


def test_memory_request_contracts_accept_only_explicit_allowlisted_pairs() -> None:
    create = CreateMemoryRequest(
        content="小雪",
        memory_type="preference",
        canonical_subject_code="preferred_address",
    )
    confirm = ConfirmMemoryCandidateRequest(
        canonical_subject_code="preferred_address"
    )
    replacement = ReplaceConflictRequest(
        kind="replace_both",
        content="一起看过雪",
        memory_type="relationship_event",
        subject="shared experience",
        canonical_subject_code="shared_experience",
        importance=4,
        confidence=0.9,
    )

    assert create.canonical_subject_code == "preferred_address"
    assert confirm.canonical_subject_code == "preferred_address"
    assert replacement.canonical_subject_code == "shared_experience"

    for model, payload in (
        (
            CreateMemoryRequest,
            {
                "content": "invalid",
                "memory_type": "preference",
                "canonical_subject_code": "shared_experience",
            },
        ),
        (
            ReplaceConflictRequest,
            {
                "kind": "replace_both",
                "content": "invalid",
                "memory_type": "user_fact",
                "subject": "invalid",
                "canonical_subject_code": "non_external_commitment",
            },
        ),
        (
            ConfirmMemoryCandidateRequest,
            {"canonical_subject_code": "称呼偏好"},
        ),
    ):
        with pytest.raises(ValueError):
            model.model_validate(payload)


def test_update_contract_distinguishes_omitted_from_explicit_null() -> None:
    omitted = UpdateMemoryRequest(content="新内容")
    cleared = UpdateMemoryRequest(canonical_subject_code=None)
    classified = UpdateMemoryRequest(
        memory_type="relationship_event",
        canonical_subject_code="shared_experience",
    )

    assert "canonical_subject_code" not in omitted.model_fields_set
    assert "canonical_subject_code" in cleared.model_fields_set
    assert cleared.canonical_subject_code is None
    assert classified.canonical_subject_code == "shared_experience"
    with pytest.raises(ValueError):
        UpdateMemoryRequest(
            memory_type="other",
            canonical_subject_code="preferred_address",
        )


def test_memory_response_contract_defaults_unpersisted_classification_to_null() -> None:
    response = MemoryResponse(
        id="memory-1",
        content="legacy",
        memory_type="other",
        source="manual",
        source_session_id=None,
        importance=3,
        confidence=1.0,
        status="active",
        created_at=_NOW,
        updated_at=_NOW,
        metadata={},
        v2_state="active",
        v2_source_kind="legacy",
        version_count=1,
        evidence_count=0,
        has_open_conflict=False,
        can_undo_latest_auto=False,
    )
    version_response = MemoryVersionResponse(
        id="version-1",
        memory_id="memory-1",
        version_number=1,
        parent_version_id=None,
        operation="bootstrap",
        memory_type="other",
        subject=None,
        content="legacy",
        confidence=1.0,
        importance=3,
        source_kind="legacy",
        source_session_id=None,
        created_at=_NOW,
        redacted_at=None,
    )

    assert response.canonical_subject_code is None
    assert version_response.canonical_subject_code is None
