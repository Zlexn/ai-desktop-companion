from __future__ import annotations

from app.services.session_summary_contract import (
    CONTEXT_COMPOSER_VERSION_C2,
    CONTEXT_DATA_ENCODER_VERSION_C2,
    CONTEXT_MANIFEST_VERSION_C2,
    SUMMARY_AUDIT_SCHEMA_VERSION,
    SUMMARY_INJECTION_DISCLOSED_FIELDS,
    SUMMARY_INJECTION_DISCLOSURE_VERSION,
    SUMMARY_INJECTION_SCHEMA_VERSION,
    SUMMARY_JOB_SCHEMA_VERSION,
    SUMMARY_PROCESSING_DISCLOSED_FIELDS,
    SUMMARY_PROCESSING_DISCLOSURE_VERSION,
    SUMMARY_PROCESSING_PURPOSE,
    SUMMARY_SCHEMA_VERSION,
    SUMMARY_SOURCE_HASH_VERSION,
    summary_injection_policy_fingerprint,
    summary_processing_policy_fingerprint,
)


def test_gate_c2_version_and_disclosure_constants_are_frozen() -> None:
    assert SUMMARY_PROCESSING_DISCLOSURE_VERSION == (
        "summary-processing-disclosure-v1"
    )
    assert SUMMARY_INJECTION_DISCLOSURE_VERSION == (
        "summary-injection-disclosure-v1"
    )
    assert SUMMARY_PROCESSING_PURPOSE == (
        "generate bounded session continuity summaries from exact completed "
        "chat turns"
    )
    assert SUMMARY_PROCESSING_DISCLOSED_FIELDS == (
        "role",
        "content",
        "turn_order",
        "message_order_in_turn",
    )
    assert SUMMARY_INJECTION_DISCLOSED_FIELDS == (
        "summary_text",
        "low_trust_type_label",
        "source_session_id",
        "summary_id",
        "source_kind",
        "created_at",
    )
    assert SUMMARY_SCHEMA_VERSION == "session-summary-v2"
    assert SUMMARY_INJECTION_SCHEMA_VERSION == "summary-injection-v1"
    assert SUMMARY_SOURCE_HASH_VERSION == "summary-source-set-hash-v1"
    assert SUMMARY_JOB_SCHEMA_VERSION == "summary-job-v1"
    assert SUMMARY_AUDIT_SCHEMA_VERSION == "summary-audit-v1"
    assert CONTEXT_COMPOSER_VERSION_C2 == "context-composer-v2"
    assert CONTEXT_DATA_ENCODER_VERSION_C2 == "context-data-json-v2"
    assert CONTEXT_MANIFEST_VERSION_C2 == "context-manifest-v2"


def test_policy_fingerprint_domain_separator_cannot_be_overridden() -> None:
    processing = summary_processing_policy_fingerprint(kind="summary_injection")
    injection = summary_injection_policy_fingerprint(kind="summary_processing")

    assert processing == summary_processing_policy_fingerprint()
    assert injection == summary_injection_policy_fingerprint()
    assert processing != injection


def test_summary_processing_policy_fingerprint_is_canonical_and_binds_fields() -> None:
    values = {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "endpoint": "https://api.deepseek.com",
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "purpose": SUMMARY_PROCESSING_PURPOSE,
        "disclosed_fields": SUMMARY_PROCESSING_DISCLOSED_FIELDS,
    }

    first = summary_processing_policy_fingerprint(**values)
    second = summary_processing_policy_fingerprint(**values)
    changed = summary_processing_policy_fingerprint(
        **{**values, "model": "changed-model"}
    )
    reordered = summary_processing_policy_fingerprint(
        **{
            **values,
            "disclosed_fields": tuple(reversed(SUMMARY_PROCESSING_DISCLOSED_FIELDS)),
        }
    )

    assert len(first) == 64
    assert first == second
    assert first != changed
    assert first != reordered


def test_summary_injection_policy_fingerprint_binds_every_granted_limit() -> None:
    values = {
        "chat_provider": "deepseek",
        "chat_model": "deepseek-v4-flash",
        "endpoint": "https://api.deepseek.com",
        "disclosure_version": SUMMARY_INJECTION_DISCLOSURE_VERSION,
        "disclosed_fields": SUMMARY_INJECTION_DISCLOSED_FIELDS,
        "injection_schema_version": SUMMARY_INJECTION_SCHEMA_VERSION,
        "max_fragment_count": 2,
        "max_fragment_characters": 1_000,
        "max_total_characters": 1_600,
    }
    baseline = summary_injection_policy_fingerprint(**values)

    assert len(baseline) == 64
    for name, value in (
        ("max_fragment_count", 1),
        ("max_fragment_characters", 999),
        ("max_total_characters", 1_599),
        ("chat_model", "changed-model"),
        ("endpoint", "https://changed.invalid"),
        ("disclosure_version", "changed-disclosure"),
        ("injection_schema_version", "changed-schema"),
        ("disclosed_fields", tuple(reversed(SUMMARY_INJECTION_DISCLOSED_FIELDS))),
    ):
        assert summary_injection_policy_fingerprint(
            **{**values, name: value}
        ) != baseline
