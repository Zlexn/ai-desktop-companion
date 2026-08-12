from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


SUMMARY_PROCESSING_DISCLOSURE_VERSION = "summary-processing-disclosure-v1"
SUMMARY_INJECTION_DISCLOSURE_VERSION = "summary-injection-disclosure-v1"
SUMMARY_PROCESSING_PURPOSE = (
    "generate bounded session continuity summaries from exact completed chat turns"
)
SUMMARY_INJECTION_PURPOSE = (
    "inject bounded low-trust session continuity summaries into chat context"
)
SUMMARY_PROCESSING_DISCLOSED_FIELDS = (
    "role",
    "content",
    "turn_order",
    "message_order_in_turn",
)
SUMMARY_INJECTION_DISCLOSED_FIELDS = (
    "summary_text",
    "low_trust_type_label",
    "source_session_id",
    "summary_id",
    "source_kind",
    "created_at",
)
SUMMARY_SCHEMA_VERSION = "session-summary-v2"
SUMMARY_INJECTION_SCHEMA_VERSION = "summary-injection-v1"
SUMMARY_SOURCE_HASH_VERSION = "summary-source-set-hash-v1"
SUMMARY_JOB_SCHEMA_VERSION = "summary-job-v1"
SUMMARY_AUDIT_SCHEMA_VERSION = "summary-audit-v1"
CONTEXT_COMPOSER_VERSION_C2 = "context-composer-v2"
CONTEXT_DATA_ENCODER_VERSION_C2 = "context-data-json-v2"
CONTEXT_MANIFEST_VERSION_C2 = "context-manifest-v2"


def _canonical_fingerprint(kind: str, values: Mapping[str, object]) -> str:
    payload = {**values, "kind": kind}
    material = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def summary_processing_policy_fingerprint(**values: object) -> str:
    return _canonical_fingerprint("summary_processing", values)


def summary_injection_policy_fingerprint(**values: object) -> str:
    return _canonical_fingerprint("summary_injection", values)


def summary_provider_policy_fingerprint(**values: object) -> str:
    return _canonical_fingerprint("summary_provider_policy", values)


def canonical_summary_source_set_hash(
    *,
    session_id: str,
    turns: Sequence[Mapping[str, Any]],
) -> str:
    material = json.dumps(
        {
            "version": SUMMARY_SOURCE_HASH_VERSION,
            "session_id": session_id,
            "turns": list(turns),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def summary_logical_source_identity(**values: object) -> str:
    return _canonical_fingerprint("summary_logical_source_identity", values)


def summary_attempt_epoch(**values: object) -> str:
    return _canonical_fingerprint("summary_attempt_epoch", values)
