from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from app.domain.models import MemoryRecordState, MemoryType, MemoryVersionSourceKind
from app.domain.relationship import (
    RelationshipEventType,
    RelationshipSourceSnapshot,
    RelationshipSubjectCode,
)
from app.services.relationship_contract import (
    NON_EXTERNAL_COMMITMENT_DELTA,
    RELATIONSHIP_MIN_CONFIDENCE,
    RELATIONSHIP_MIN_IMPORTANCE,
    RELATIONSHIP_RULE_VERSION,
    SHARED_EXPERIENCE_DELTA,
    canonical_relationship_subject_code,
    normalize_preferred_address,
)


_ALLOWED_SOURCE_KINDS = frozenset(
    {
        MemoryVersionSourceKind.MANUAL,
        MemoryVersionSourceKind.CANDIDATE,
        MemoryVersionSourceKind.AUTOMATIC,
        MemoryVersionSourceKind.USER_EDIT,
        MemoryVersionSourceKind.USER_REVERT,
    }
)


@dataclass(frozen=True)
class RelationshipRuleResult:
    eligible: bool
    reason_code: str
    event_type: RelationshipEventType | None
    subject_code: RelationshipSubjectCode | None
    payload: Mapping[str, object] | None
    persona_artifact_id: str | None


class RelationshipRuleSet:
    """Maps exact immutable source fields without free-text inference."""

    def map(
        self,
        source: RelationshipSourceSnapshot,
        *,
        persona_artifact_id: str,
    ) -> RelationshipRuleResult:
        reason = self._ineligible_reason(source, persona_artifact_id)
        if reason is not None:
            return _skipped(reason)

        subject_code = source.canonical_subject_code
        if subject_code == "preferred_address":
            try:
                address = normalize_preferred_address(
                    source.preferred_address_candidate or ""
                )
            except ValueError:
                return _skipped("invalid_preferred_address")
            payload: Mapping[str, object] = MappingProxyType({"address": address})
            event_type = RelationshipEventType.PREFERRED_ADDRESS
        elif subject_code == "shared_experience":
            payload = MappingProxyType(
                {
                    "category": "shared_experience",
                    "reason_code": "allowlisted_current_memory",
                    "delta": SHARED_EXPERIENCE_DELTA,
                }
            )
            event_type = RelationshipEventType.SHARED_EXPERIENCE
        elif subject_code == "non_external_commitment":
            payload = MappingProxyType(
                {
                    "category": "non_external_commitment",
                    "reason_code": "allowlisted_current_memory",
                    "delta": NON_EXTERNAL_COMMITMENT_DELTA,
                }
            )
            event_type = RelationshipEventType.NON_EXTERNAL_COMMITMENT
        else:
            return _skipped("missing_subject_code")

        return RelationshipRuleResult(
            eligible=True,
            reason_code="eligible",
            event_type=event_type,
            subject_code=subject_code,
            payload=payload,
            persona_artifact_id=persona_artifact_id,
        )

    @staticmethod
    def _ineligible_reason(
        source: RelationshipSourceSnapshot,
        persona_artifact_id: str,
    ) -> str | None:
        if not isinstance(persona_artifact_id, str) or not persona_artifact_id:
            return "missing_persona_artifact"
        if source.relationship_rule_version != RELATIONSHIP_RULE_VERSION:
            return "unsupported_rule_version"
        if source.record_state is not MemoryRecordState.ACTIVE:
            return "source_not_active"
        if source.payload_redacted:
            return "source_payload_redacted"
        if source.open_conflict:
            return "source_has_open_conflict"
        if source.authority_suppressed:
            return "source_authority_suppressed"
        if source.version_source_kind not in _ALLOWED_SOURCE_KINDS:
            return "source_kind_not_allowed"
        if (
            isinstance(source.version_confidence, bool)
            or not isinstance(source.version_confidence, (int, float))
            or not math.isfinite(float(source.version_confidence))
            or source.version_confidence < RELATIONSHIP_MIN_CONFIDENCE
        ):
            return "confidence_below_threshold"
        if (
            isinstance(source.version_importance, bool)
            or not isinstance(source.version_importance, int)
            or source.version_importance < RELATIONSHIP_MIN_IMPORTANCE
        ):
            return "importance_below_threshold"
        if source.canonical_subject_code is None:
            return "missing_subject_code"
        try:
            canonical_relationship_subject_code(
                memory_type=source.memory_type,
                explicit_subject_code=source.canonical_subject_code,
            )
        except ValueError:
            return "subject_not_allowed_for_memory_type"
        if source.memory_type not in {
            MemoryType.RELATIONSHIP_EVENT,
            MemoryType.PREFERENCE,
            MemoryType.USER_FACT,
        }:
            return "subject_not_allowed_for_memory_type"
        return None


def _skipped(reason_code: str) -> RelationshipRuleResult:
    return RelationshipRuleResult(
        eligible=False,
        reason_code=reason_code,
        event_type=None,
        subject_code=None,
        payload=None,
        persona_artifact_id=None,
    )
