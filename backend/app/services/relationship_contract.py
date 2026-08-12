from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from typing import Literal

from app.domain.models import MemoryType


RELATIONSHIP_SCOPE_ID = "default"
RELATIONSHIP_EVENT_SCHEMA_VERSION = "relationship-event-v1"
RELATIONSHIP_RULE_VERSION = "relationship-rules-v1"
RELATIONSHIP_PROJECTION_RULE_VERSION = "relationship-projection-v1"
RELATIONSHIP_AUTHORITY_SCHEMA_VERSION = "relationship-authority-v1"
RELATIONSHIP_RECONCILE_JOB_VERSION = "relationship-reconcile-job-v1"
RELATIONSHIP_AUDIT_SCHEMA_VERSION = "relationship-audit-v1"
RELATIONSHIP_INTEGRITY_VERSION = "relationship-integrity-v1"
RELATIONSHIP_OBSERVED_TIME_DERIVATION_VERSION = "memory-version-created-at-utc-v1"
RELATIONSHIP_FIXTURE_SCHEMA_VERSION = "gate-c3-replay-v1"
CONTEXT_COMPOSER_VERSION_C3 = "context-composer-v3"
CONTEXT_DATA_ENCODER_VERSION_C3 = "context-data-json-v3"
CONTEXT_MANIFEST_VERSION_C3 = "context-manifest-v3"

CANONICAL_RELATIONSHIP_SUBJECT_CODES = (
    "preferred_address",
    "shared_experience",
    "non_external_commitment",
)

PREFERRED_ADDRESS_MAX_CHARACTERS = 32
RELATIONSHIP_MIN_CONFIDENCE = 0.75
RELATIONSHIP_MIN_IMPORTANCE = 2
FAMILIARITY_BASELINE = 0.40
FAMILIARITY_MIN = 0.0
FAMILIARITY_MAX = 1.0
FAMILIARITY_PER_EVENT_CAP = 0.08
FAMILIARITY_PER_SOURCE_LIFETIME_CAP = 0.10
SHARED_EXPERIENCE_DELTA = 0.04
NON_EXTERNAL_COMMITMENT_DELTA = 0.03
RELATIONSHIP_CONTEXT_MAX_CHARACTERS_DEFAULT = 600
RELATIONSHIP_RECONCILE_MAX_ATTEMPTS_DEFAULT = 3
RELATIONSHIP_RECOVERY_STALE_SECONDS_DEFAULT = 300

RelationshipSubjectCode = Literal[
    "preferred_address",
    "shared_experience",
    "non_external_commitment",
]
FamiliarityBucket = Literal["reserved", "steady", "familiar", "close"]

_ALLOWED_SUBJECTS_BY_MEMORY_TYPE: dict[MemoryType, frozenset[str]] = {
    MemoryType.RELATIONSHIP_EVENT: frozenset(CANONICAL_RELATIONSHIP_SUBJECT_CODES),
    MemoryType.PREFERENCE: frozenset({"preferred_address"}),
    MemoryType.USER_FACT: frozenset({"preferred_address"}),
}


def canonical_relationship_subject_code(
    *,
    memory_type: MemoryType,
    explicit_subject_code: str | None,
) -> RelationshipSubjectCode | None:
    if type(memory_type) is not MemoryType:
        raise ValueError("memory_type must be a MemoryType")
    if explicit_subject_code is None:
        return None
    if not isinstance(explicit_subject_code, str):
        raise ValueError("relationship subject code must be a string or null")
    allowed = _ALLOWED_SUBJECTS_BY_MEMORY_TYPE.get(memory_type, frozenset())
    if explicit_subject_code not in allowed:
        raise ValueError("relationship subject code is not allowed for memory type")
    return explicit_subject_code  # type: ignore[return-value]


def normalize_preferred_address(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("preferred address must be a string")
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Cf"
    ).strip()
    if not normalized or len(normalized) > PREFERRED_ADDRESS_MAX_CHARACTERS:
        raise ValueError("preferred address must contain between 1 and 32 characters")
    if any(
        character in {" ", " "}
        or unicodedata.category(character) in {"Cc", "Cs"}
        for character in normalized
    ):
        raise ValueError("preferred address must not contain control characters")
    return normalized


def relationship_private_fingerprint(document: object) -> str:
    try:
        material = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("canonical relationship document is invalid") from exc
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def familiarity_bucket(value: float) -> FamiliarityBucket:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not FAMILIARITY_MIN <= float(value) <= FAMILIARITY_MAX
    ):
        raise ValueError("familiarity must be a finite value between 0.0 and 1.0")
    numeric = float(value)
    if numeric < 0.35:
        return "reserved"
    if numeric < 0.55:
        return "steady"
    if numeric < 0.75:
        return "familiar"
    return "close"
