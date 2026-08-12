from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.domain.models import MemoryRecordState, MemoryType, MemoryVersionSourceKind
from app.domain.relationship import (
    RelationshipEventType,
    RelationshipSourceSnapshot,
)
from app.services.relationship_contract import RELATIONSHIP_RULE_VERSION
from app.services.relationship_rules import RelationshipRuleSet


_NOW = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)


def _source(
    *,
    memory_type: MemoryType = MemoryType.RELATIONSHIP_EVENT,
    subject_code: str | None = "shared_experience",
    source_kind: MemoryVersionSourceKind = MemoryVersionSourceKind.MANUAL,
    content: str | None = "arbitrary source prose",
) -> RelationshipSourceSnapshot:
    return RelationshipSourceSnapshot(
        scope_id="default",
        source_memory_id="memory-1",
        source_memory_version_id="version-1",
        record_head_version=1,
        record_generation=0,
        record_state=MemoryRecordState.ACTIVE,
        memory_type=memory_type,
        canonical_subject_code=subject_code,
        version_source_kind=source_kind,
        version_confidence=0.75,
        version_importance=2,
        version_created_at=_NOW,
        open_conflict=False,
        payload_redacted=False,
        effective_authority_decision_id=None,
        effective_authority_generation=0,
        authority_epoch=0,
        inherited_authority_fingerprint="a" * 64,
        authority_suppressed=False,
        relationship_rule_version=RELATIONSHIP_RULE_VERSION,
        preferred_address_candidate=content,
    )


def test_maps_only_three_explicit_allowlisted_subjects() -> None:
    rules = RelationshipRuleSet()

    preferred = rules.map(
        _source(
            memory_type=MemoryType.PREFERENCE,
            subject_code="preferred_address",
            content=" Ａｌｉｃｅ​ ",
        ),
        persona_artifact_id="persona-1",
    )
    shared = rules.map(_source(), persona_artifact_id="persona-1")
    commitment = rules.map(
        _source(subject_code="non_external_commitment"),
        persona_artifact_id="persona-1",
    )

    assert preferred.eligible
    assert preferred.event_type is RelationshipEventType.PREFERRED_ADDRESS
    assert preferred.payload == {"address": "Alice"}
    assert shared.payload == {
        "category": "shared_experience",
        "reason_code": "allowlisted_current_memory",
        "delta": 0.04,
    }
    assert commitment.payload == {
        "category": "non_external_commitment",
        "reason_code": "allowlisted_current_memory",
        "delta": 0.03,
    }
    assert all(
        result.persona_artifact_id == "persona-1"
        for result in (preferred, shared, commitment)
    )


@pytest.mark.parametrize(
    ("change", "reason_code"),
    [
        ({"record_state": MemoryRecordState.ARCHIVED}, "source_not_active"),
        ({"open_conflict": True}, "source_has_open_conflict"),
        ({"payload_redacted": True}, "source_payload_redacted"),
        ({"authority_suppressed": True}, "source_authority_suppressed"),
        ({"version_confidence": 0.749}, "confidence_below_threshold"),
        ({"version_confidence": float("nan")}, "confidence_below_threshold"),
        ({"version_importance": 1}, "importance_below_threshold"),
        ({"relationship_rule_version": "future-rules"}, "unsupported_rule_version"),
        ({"canonical_subject_code": None}, "missing_subject_code"),
        ({"version_source_kind": MemoryVersionSourceKind.LEGACY}, "source_kind_not_allowed"),
    ],
)
def test_eligibility_is_fail_closed_with_metadata_only_reasons(
    change: dict[str, object],
    reason_code: str,
) -> None:
    result = RelationshipRuleSet().map(
        replace(_source(), **change),
        persona_artifact_id="persona-1",
    )

    assert not result.eligible
    assert result.reason_code == reason_code
    assert result.event_type is None
    assert result.subject_code is None
    assert result.payload is None


@pytest.mark.parametrize(
    "source_kind",
    [
        MemoryVersionSourceKind.MANUAL,
        MemoryVersionSourceKind.CANDIDATE,
        MemoryVersionSourceKind.AUTOMATIC,
        MemoryVersionSourceKind.USER_EDIT,
        MemoryVersionSourceKind.USER_REVERT,
    ],
)
def test_all_and_only_frozen_source_kinds_are_allowed(
    source_kind: MemoryVersionSourceKind,
) -> None:
    result = RelationshipRuleSet().map(
        _source(source_kind=source_kind),
        persona_artifact_id="persona-1",
    )
    assert result.eligible


def test_strict_type_code_matrix_does_not_use_free_text_to_classify() -> None:
    rules = RelationshipRuleSet()
    prose = "preferred_address 小雪 shared_experience non_external_commitment"

    uncoded = rules.map(
        _source(
            memory_type=MemoryType.RELATIONSHIP_EVENT,
            subject_code=None,
            content=prose,
        ),
        persona_artifact_id="persona-1",
    )
    invalid_pair = rules.map(
        _source(
            memory_type=MemoryType.USER_FACT,
            subject_code="shared_experience",
            content=prose,
        ),
        persona_artifact_id="persona-1",
    )

    assert not uncoded.eligible and uncoded.reason_code == "missing_subject_code"
    assert not invalid_pair.eligible
    assert invalid_pair.reason_code == "subject_not_allowed_for_memory_type"
    assert invalid_pair.payload is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "x" * 33,
        "小\n雪",
        "小\x00雪",
        "请以后叫我小雪",
    ],
)
def test_preferred_address_requires_complete_bounded_address(value: str) -> None:
    result = RelationshipRuleSet().map(
        _source(
            memory_type=MemoryType.USER_FACT,
            subject_code="preferred_address",
            content=value,
        ),
        persona_artifact_id="persona-1",
    )

    if value == "请以后叫我小雪":
        # The rule never extracts a substring; the complete bounded value is used.
        assert result.payload == {"address": value}
    else:
        assert not result.eligible
        assert result.reason_code == "invalid_preferred_address"
        assert result.payload is None


def test_missing_or_malformed_persona_provenance_is_rejected() -> None:
    rules = RelationshipRuleSet()

    missing = rules.map(_source(), persona_artifact_id="")
    malformed = rules.map(
        _source(),
        persona_artifact_id=1,  # type: ignore[arg-type]
    )

    assert not missing.eligible
    assert missing.reason_code == "missing_persona_artifact"
    assert missing.payload is None
    assert not malformed.eligible
    assert malformed.reason_code == "missing_persona_artifact"
    assert malformed.payload is None


def test_mapping_result_payload_is_immutable() -> None:
    result = RelationshipRuleSet().map(_source(), persona_artifact_id="persona-1")
    assert result.payload is not None
    with pytest.raises(TypeError):
        result.payload["delta"] = 1.0  # type: ignore[index]
