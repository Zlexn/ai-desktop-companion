from __future__ import annotations

import math
from pathlib import Path

import pytest

from app.domain.models import MemoryType
from app.services.relationship_contract import (
    CANONICAL_RELATIONSHIP_SUBJECT_CODES,
    CONTEXT_COMPOSER_VERSION_C3,
    CONTEXT_DATA_ENCODER_VERSION_C3,
    CONTEXT_MANIFEST_VERSION_C3,
    FAMILIARITY_BASELINE,
    FAMILIARITY_MAX,
    FAMILIARITY_MIN,
    FAMILIARITY_PER_EVENT_CAP,
    FAMILIARITY_PER_SOURCE_LIFETIME_CAP,
    NON_EXTERNAL_COMMITMENT_DELTA,
    PREFERRED_ADDRESS_MAX_CHARACTERS,
    RELATIONSHIP_AUDIT_SCHEMA_VERSION,
    RELATIONSHIP_AUTHORITY_SCHEMA_VERSION,
    RELATIONSHIP_EVENT_SCHEMA_VERSION,
    RELATIONSHIP_FIXTURE_SCHEMA_VERSION,
    RELATIONSHIP_INTEGRITY_VERSION,
    RELATIONSHIP_MIN_CONFIDENCE,
    RELATIONSHIP_MIN_IMPORTANCE,
    RELATIONSHIP_OBSERVED_TIME_DERIVATION_VERSION,
    RELATIONSHIP_PROJECTION_RULE_VERSION,
    RELATIONSHIP_RECONCILE_JOB_VERSION,
    RELATIONSHIP_RECOVERY_STALE_SECONDS_DEFAULT,
    RELATIONSHIP_RECONCILE_MAX_ATTEMPTS_DEFAULT,
    RELATIONSHIP_RULE_VERSION,
    RELATIONSHIP_SCOPE_ID,
    RELATIONSHIP_CONTEXT_MAX_CHARACTERS_DEFAULT,
    SHARED_EXPERIENCE_DELTA,
    canonical_relationship_subject_code,
    familiarity_bucket,
    normalize_preferred_address,
    relationship_private_fingerprint,
)


def test_gate_c3_contract_versions_and_bounds_are_frozen() -> None:
    assert RELATIONSHIP_SCOPE_ID == "default"
    assert RELATIONSHIP_EVENT_SCHEMA_VERSION == "relationship-event-v1"
    assert RELATIONSHIP_RULE_VERSION == "relationship-rules-v1"
    assert RELATIONSHIP_PROJECTION_RULE_VERSION == "relationship-projection-v1"
    assert RELATIONSHIP_AUTHORITY_SCHEMA_VERSION == "relationship-authority-v1"
    assert RELATIONSHIP_RECONCILE_JOB_VERSION == "relationship-reconcile-job-v1"
    assert RELATIONSHIP_AUDIT_SCHEMA_VERSION == "relationship-audit-v1"
    assert RELATIONSHIP_INTEGRITY_VERSION == "relationship-integrity-v1"
    assert (
        RELATIONSHIP_OBSERVED_TIME_DERIVATION_VERSION
        == "memory-version-created-at-utc-v1"
    )
    assert RELATIONSHIP_FIXTURE_SCHEMA_VERSION == "gate-c3-replay-v1"
    assert CONTEXT_COMPOSER_VERSION_C3 == "context-composer-v3"
    assert CONTEXT_DATA_ENCODER_VERSION_C3 == "context-data-json-v3"
    assert CONTEXT_MANIFEST_VERSION_C3 == "context-manifest-v3"
    assert CANONICAL_RELATIONSHIP_SUBJECT_CODES == (
        "preferred_address",
        "shared_experience",
        "non_external_commitment",
    )
    assert PREFERRED_ADDRESS_MAX_CHARACTERS == 32
    assert RELATIONSHIP_MIN_CONFIDENCE == 0.75
    assert RELATIONSHIP_MIN_IMPORTANCE == 2
    assert FAMILIARITY_BASELINE == 0.40
    assert FAMILIARITY_MIN == 0.0
    assert FAMILIARITY_MAX == 1.0
    assert FAMILIARITY_PER_EVENT_CAP == 0.08
    assert FAMILIARITY_PER_SOURCE_LIFETIME_CAP == 0.10
    assert SHARED_EXPERIENCE_DELTA == 0.04
    assert NON_EXTERNAL_COMMITMENT_DELTA == 0.03
    assert RELATIONSHIP_CONTEXT_MAX_CHARACTERS_DEFAULT == 600
    assert RELATIONSHIP_RECONCILE_MAX_ATTEMPTS_DEFAULT == 3
    assert RELATIONSHIP_RECOVERY_STALE_SECONDS_DEFAULT == 300


def test_relationship_private_fingerprint_is_canonical_and_binds_values() -> None:
    left = relationship_private_fingerprint(
        {"scope": "default", "nested": {"b": 2, "a": ["一", 1]}}
    )
    right = relationship_private_fingerprint(
        {"nested": {"a": ["一", 1], "b": 2}, "scope": "default"}
    )

    assert left == right
    assert len(left) == 64
    assert left != relationship_private_fingerprint(
        {"scope": "default", "nested": {"b": 3, "a": ["一", 1]}}
    )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_relationship_private_fingerprint_rejects_non_finite_values(
    value: float,
) -> None:
    with pytest.raises(ValueError, match="canonical relationship document"):
        relationship_private_fingerprint({"value": value})


def test_preferred_address_is_nfkc_normalized_and_removes_format_marks() -> None:
    assert normalize_preferred_address("  Ｙｕｋｉ​  ") == "Yuki"
    assert normalize_preferred_address("小雪") == "小雪"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "雪\n乃",
        "雪\r乃",
        "雪\t乃",
        "雪 乃",
        "雪 乃",
        "雪\x00乃",
        "雪" * 33,
    ],
)
def test_preferred_address_rejects_empty_control_line_and_oversized_values(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="preferred address"):
        normalize_preferred_address(value)


@pytest.mark.parametrize("value", [None, 1, True, [], {}])
def test_preferred_address_requires_a_string(value: object) -> None:
    with pytest.raises(ValueError, match="preferred address"):
        normalize_preferred_address(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("memory_type", "subject_code"),
    [
        (MemoryType.RELATIONSHIP_EVENT, "preferred_address"),
        (MemoryType.RELATIONSHIP_EVENT, "shared_experience"),
        (MemoryType.RELATIONSHIP_EVENT, "non_external_commitment"),
        (MemoryType.PREFERENCE, "preferred_address"),
        (MemoryType.USER_FACT, "preferred_address"),
    ],
)
def test_explicit_relationship_subject_matrix_accepts_only_allowlisted_pairs(
    memory_type: MemoryType,
    subject_code: str,
) -> None:
    assert (
        canonical_relationship_subject_code(
            memory_type=memory_type,
            explicit_subject_code=subject_code,
        )
        == subject_code
    )


def test_missing_explicit_relationship_subject_remains_unclassified() -> None:
    assert (
        canonical_relationship_subject_code(
            memory_type=MemoryType.RELATIONSHIP_EVENT,
            explicit_subject_code=None,
        )
        is None
    )


@pytest.mark.parametrize(
    ("memory_type", "subject_code"),
    [
        (MemoryType.PREFERENCE, "shared_experience"),
        (MemoryType.USER_FACT, "non_external_commitment"),
        (MemoryType.OTHER, "preferred_address"),
        (MemoryType.RELATIONSHIP_EVENT, "称呼偏好"),
        (MemoryType.RELATIONSHIP_EVENT, "preferred_address:小雪"),
        (MemoryType.RELATIONSHIP_EVENT, "PREFERRED_ADDRESS"),
    ],
)
def test_explicit_relationship_subject_matrix_rejects_unknown_or_invalid_pairs(
    memory_type: MemoryType,
    subject_code: str,
) -> None:
    with pytest.raises(ValueError, match="relationship subject code"):
        canonical_relationship_subject_code(
            memory_type=memory_type,
            explicit_subject_code=subject_code,
        )


def test_relationship_subject_code_does_not_accept_untyped_inputs() -> None:
    with pytest.raises(ValueError, match="memory_type"):
        canonical_relationship_subject_code(  # type: ignore[arg-type]
            memory_type="relationship_event",
            explicit_subject_code="preferred_address",
        )
    with pytest.raises(ValueError, match="relationship subject code"):
        canonical_relationship_subject_code(
            memory_type=MemoryType.RELATIONSHIP_EVENT,
            explicit_subject_code=True,  # type: ignore[arg-type]
        )


def test_gate_c3_environment_template_is_local_bounded_and_authority_free() -> None:
    env_text = (
        Path(__file__).resolve().parents[2] / ".env.example"
    ).read_text(encoding="utf-8")
    values = {}
    for raw_line in env_text.splitlines():
        line = raw_line.strip()
        if line.startswith("RELATIONSHIP_") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value

    assert values == {
        "RELATIONSHIP_CONTEXT_MAX_CHARACTERS": "600",
        "RELATIONSHIP_RECONCILE_MAX_ATTEMPTS": "3",
        "RELATIONSHIP_RECOVERY_STALE_SECONDS": "300",
    }
    relationship_lines = "\n".join(
        line for line in env_text.splitlines() if "RELATIONSHIP_" in line
    )
    for forbidden in (
        "CONSENT=",
        "AUTHORITY=",
        "PROVIDER=",
        "MODEL=",
        "API_KEY=",
        "ASSET=",
    ):
        assert forbidden not in relationship_lines


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "reserved"),
        (0.349999, "reserved"),
        (0.35, "steady"),
        (0.549999, "steady"),
        (0.55, "familiar"),
        (0.749999, "familiar"),
        (0.75, "close"),
        (1.0, "close"),
    ],
)
def test_familiarity_bucket_thresholds_are_deterministic(
    value: float,
    expected: str,
) -> None:
    assert familiarity_bucket(value) == expected


@pytest.mark.parametrize("value", [-0.01, 1.01, math.nan, math.inf, True])
def test_familiarity_bucket_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValueError, match="familiarity"):
        familiarity_bucket(value)  # type: ignore[arg-type]
