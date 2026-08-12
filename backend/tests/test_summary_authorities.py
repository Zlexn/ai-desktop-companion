from __future__ import annotations

from dataclasses import asdict, replace
import sqlite3

import pytest

from app.core.config import Settings
from app.core.errors import (
    SummaryAuthorityStateError,
    SummaryAuthorityVersionConflictError,
)
from app.domain.session_summary import SummaryAuthorityStatus
from app.repositories.sqlite import connect, init_db
from app.repositories.summary_automation import (
    SummaryAutomationRepository,
    SummaryInjectionPolicy,
    SummaryProcessingPolicy,
)
from app.services.session_summary_contract import (
    SUMMARY_INJECTION_DISCLOSED_FIELDS,
    SUMMARY_INJECTION_DISCLOSURE_VERSION,
    SUMMARY_INJECTION_SCHEMA_VERSION,
    SUMMARY_PROCESSING_DISCLOSED_FIELDS,
    SUMMARY_PROCESSING_DISCLOSURE_VERSION,
    SUMMARY_PROCESSING_PURPOSE,
    SUMMARY_SCHEMA_VERSION,
)
from app.services.session_summary_service import build_summary_injection_policy


@pytest.fixture
def connection(tmp_path) -> sqlite3.Connection:
    connection = connect(f"sqlite:///{tmp_path / 'summary-authorities.db'}")
    init_db(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def repository(connection: sqlite3.Connection) -> SummaryAutomationRepository:
    return SummaryAutomationRepository(connection)


@pytest.fixture
def processing_policy() -> SummaryProcessingPolicy:
    return SummaryProcessingPolicy(
        route="remote",
        disclosure_version=SUMMARY_PROCESSING_DISCLOSURE_VERSION,
        purpose=SUMMARY_PROCESSING_PURPOSE,
        provider="deepseek",
        model="deepseek-chat",
        endpoint_policy="openai-compatible-v1",
        summarizer_schema_version=SUMMARY_SCHEMA_VERSION,
        disclosed_fields=SUMMARY_PROCESSING_DISCLOSED_FIELDS,
    )


@pytest.fixture
def injection_policy() -> SummaryInjectionPolicy:
    return SummaryInjectionPolicy(
        route="remote",
        disclosure_version=SUMMARY_INJECTION_DISCLOSURE_VERSION,
        purpose="inject bounded low-trust session continuity summaries into chat context",
        chat_provider="deepseek",
        chat_model="deepseek-chat",
        endpoint_policy="openai-compatible-v1",
        injection_schema_version=SUMMARY_INJECTION_SCHEMA_VERSION,
        disclosed_fields=SUMMARY_INJECTION_DISCLOSED_FIELDS,
        max_fragment_count=2,
        max_fragment_characters=1_000,
        max_total_characters=1_600,
    )


def _set_processing_state(
    repository: SummaryAutomationRepository,
    policy: SummaryProcessingPolicy,
    state: str,
) -> None:
    if state == "unknown":
        repository.get_processing_authority()
        return
    action = {"granted": "grant", "declined": "decline", "revoked": "revoke"}[state]
    repository.mutate_processing(
        action=action,
        expected_generation=0,
        policy=policy,
    )


def _set_injection_state(
    repository: SummaryAutomationRepository,
    policy: SummaryInjectionPolicy,
    state: str,
) -> None:
    if state == "unknown":
        repository.get_injection_authority()
        return
    action = {"granted": "grant", "declined": "decline", "revoked": "revoke"}[state]
    repository.mutate_injection(
        action=action,
        expected_generation=0,
        policy=policy,
    )


@pytest.mark.parametrize("processing", ["unknown", "granted", "declined", "revoked"])
@pytest.mark.parametrize("injection", ["unknown", "granted", "declined", "revoked"])
def test_processing_and_injection_authorities_never_substitute(
    processing: str,
    injection: str,
    repository: SummaryAutomationRepository,
    processing_policy: SummaryProcessingPolicy,
    injection_policy: SummaryInjectionPolicy,
) -> None:
    _set_processing_state(repository, processing_policy, processing)
    _set_injection_state(repository, injection_policy, injection)

    assert (repository.valid_processing_snapshot(processing_policy) is not None) is (
        processing == "granted"
    )
    assert (repository.valid_injection_snapshot(injection_policy) is not None) is (
        injection == "granted"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("route", "local"),
        ("disclosure_version", "summary-processing-disclosure-v2"),
        ("purpose", "different purpose"),
        ("provider", "anthropic"),
        ("model", "different-model"),
        ("endpoint_policy", "different-endpoint-policy"),
        ("summarizer_schema_version", "session-summary-v3"),
        ("disclosed_fields", ("content", "role")),
    ],
)
def test_processing_grant_binds_every_policy_field(
    field: str,
    value: object,
    repository: SummaryAutomationRepository,
    processing_policy: SummaryProcessingPolicy,
) -> None:
    repository.mutate_processing(
        action="grant",
        expected_generation=0,
        policy=processing_policy,
    )
    assert repository.valid_processing_snapshot(processing_policy) is not None

    assert repository.valid_processing_snapshot(
        replace(processing_policy, **{field: value})
    ) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("route", "local"),
        ("disclosure_version", "summary-injection-disclosure-v2"),
        ("purpose", "different purpose"),
        ("chat_provider", "anthropic"),
        ("chat_model", "different-model"),
        ("endpoint_policy", "different-endpoint-policy"),
        ("injection_schema_version", "summary-injection-v2"),
        ("disclosed_fields", ("summary_text",)),
        ("max_fragment_count", 3),
        ("max_fragment_characters", 999),
        ("max_total_characters", 1_599),
    ],
)
def test_injection_grant_binds_every_policy_field(
    field: str,
    value: object,
    repository: SummaryAutomationRepository,
    injection_policy: SummaryInjectionPolicy,
) -> None:
    granted = repository.mutate_injection(
        action="grant",
        expected_generation=0,
        policy=injection_policy,
    )
    snapshot = repository.valid_injection_snapshot(injection_policy)
    persisted = repository.get_injection_authority()
    assert snapshot is not None
    assert granted.max_fragment_characters == 1_000
    assert persisted.max_fragment_characters == 1_000
    assert snapshot.max_fragment_characters == 1_000

    changed = replace(injection_policy, **{field: value})
    assert repository.valid_injection_snapshot(changed) is None
    if field == "max_fragment_characters":
        assert changed.fingerprint() != injection_policy.fingerprint()


def test_injection_policy_builder_binds_local_and_remote_chat_configuration() -> None:
    local = build_summary_injection_policy(
        Settings(
            llm_provider="fake",
            llm_model="local-model",
            summary_injection_max_fragments=3,
            summary_injection_max_fragment_characters=900,
            summary_injection_max_total_characters=1_500,
        )
    )
    remote = build_summary_injection_policy(
        Settings(
            llm_provider="deepseek",
            llm_model="deepseek-chat",
            deepseek_base_url="https://example.test/v1/",
        )
    )

    assert local.route == "local"
    assert local.endpoint_policy == "local-chat-v1"
    assert local.max_fragment_count == 3
    assert local.max_fragment_characters == 900
    assert local.max_total_characters == 1_500
    assert remote.route == "remote"
    assert remote.endpoint_policy == "https://example.test/v1"
    assert remote.chat_provider == "deepseek"
    assert remote.chat_model == "deepseek-chat"
    assert local.fingerprint() != remote.fingerprint()


def test_generation_zero_unknown_is_lazily_persisted(
    repository: SummaryAutomationRepository,
) -> None:
    processing = repository.get_processing_authority()
    injection = repository.get_injection_authority()

    assert processing.status is SummaryAuthorityStatus.UNKNOWN
    assert injection.status is SummaryAuthorityStatus.UNKNOWN
    assert processing.generation == injection.generation == 0
    assert processing.disclosed_fields == injection.disclosed_fields == ()
    assert injection.max_fragment_count is None
    assert injection.max_fragment_characters is None
    assert injection.max_total_characters is None


@pytest.mark.parametrize("kind", ["processing", "injection"])
def test_stale_expected_generation_is_rejected_without_audit_or_other_mutation(
    kind: str,
    repository: SummaryAutomationRepository,
    connection: sqlite3.Connection,
    processing_policy: SummaryProcessingPolicy,
    injection_policy: SummaryInjectionPolicy,
) -> None:
    if kind == "processing":
        repository.mutate_processing(
            action="grant", expected_generation=0, policy=processing_policy
        )
        mutate = lambda: repository.mutate_processing(
            action="revoke", expected_generation=0, policy=processing_policy
        )
    else:
        repository.mutate_injection(
            action="grant", expected_generation=0, policy=injection_policy
        )
        mutate = lambda: repository.mutate_injection(
            action="revoke", expected_generation=0, policy=injection_policy
        )

    before_audits = connection.execute(
        "SELECT COUNT(*) FROM summary_authority_audits"
    ).fetchone()[0]
    with pytest.raises(SummaryAuthorityVersionConflictError):
        mutate()
    after_audits = connection.execute(
        "SELECT COUNT(*) FROM summary_authority_audits"
    ).fetchone()[0]

    assert before_audits == after_audits == 1
    assert repository.get_processing_authority().generation == int(kind == "processing")
    assert repository.get_injection_authority().generation == int(kind == "injection")


def test_decline_and_revoke_clear_grant_only_private_bindings(
    repository: SummaryAutomationRepository,
    connection: sqlite3.Connection,
    processing_policy: SummaryProcessingPolicy,
    injection_policy: SummaryInjectionPolicy,
) -> None:
    repository.mutate_processing(
        action="grant", expected_generation=0, policy=processing_policy
    )
    processing = repository.mutate_processing(
        action="revoke", expected_generation=1, policy=processing_policy
    )
    repository.mutate_injection(
        action="grant", expected_generation=0, policy=injection_policy
    )
    injection = repository.mutate_injection(
        action="decline", expected_generation=1, policy=injection_policy
    )

    assert processing.status is SummaryAuthorityStatus.REVOKED
    assert processing.disclosure_version is None
    assert processing.purpose is None
    assert processing.provider is None
    assert processing.disclosed_fields == ()
    assert injection.status is SummaryAuthorityStatus.DECLINED
    assert injection.disclosure_version is None
    assert injection.disclosed_fields == ()
    assert injection.max_fragment_count is None
    assert injection.max_fragment_characters is None
    assert injection.max_total_characters is None

    processing_row = connection.execute(
        "SELECT * FROM summary_processing_consents"
    ).fetchone()
    injection_row = connection.execute(
        "SELECT * FROM summary_injection_consents"
    ).fetchone()
    assert processing_row["policy_fingerprint"] is None
    assert injection_row["chat_provider_fingerprint"] is None
    assert injection_row["disclosed_fields_json"] == "[]"


def test_authority_projection_and_audits_omit_private_fingerprints(
    repository: SummaryAutomationRepository,
    connection: sqlite3.Connection,
    processing_policy: SummaryProcessingPolicy,
    injection_policy: SummaryInjectionPolicy,
) -> None:
    repository.mutate_processing(
        action="grant", expected_generation=0, policy=processing_policy
    )
    repository.mutate_injection(
        action="grant", expected_generation=0, policy=injection_policy
    )

    assert "fingerprint" not in asdict(repository.get_processing_authority())
    assert "fingerprint" not in asdict(repository.get_injection_authority())
    audits = repository.list_authority_audits()
    assert len(audits) == 2
    assert all("fingerprint" not in asdict(audit) for audit in audits)
    audit_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(summary_authority_audits)")
    }
    assert "policy_fingerprint" not in audit_columns
    assert "chat_provider_fingerprint" not in audit_columns


def test_environment_configuration_never_creates_authority(
    monkeypatch: pytest.MonkeyPatch,
    repository: SummaryAutomationRepository,
    processing_policy: SummaryProcessingPolicy,
    injection_policy: SummaryInjectionPolicy,
) -> None:
    monkeypatch.setenv("SESSION_SUMMARY_PROVIDER", "llm")
    monkeypatch.setenv("SESSION_SUMMARY_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("SUMMARY_INJECTION_MAX_FRAGMENTS", "2")

    assert repository.valid_processing_snapshot(processing_policy) is None
    assert repository.valid_injection_snapshot(injection_policy) is None
    assert repository.get_processing_authority().generation == 0
    assert repository.get_injection_authority().generation == 0


def test_local_enable_and_disable_use_explicit_route_actions(
    repository: SummaryAutomationRepository,
    processing_policy: SummaryProcessingPolicy,
    injection_policy: SummaryInjectionPolicy,
) -> None:
    local_processing = replace(processing_policy, route="local")
    local_injection = replace(injection_policy, route="local")

    repository.mutate_processing(
        action="enable_local", expected_generation=0, policy=local_processing
    )
    repository.mutate_injection(
        action="enable_local", expected_generation=0, policy=local_injection
    )
    assert repository.valid_processing_snapshot(local_processing) is not None
    assert repository.valid_injection_snapshot(local_injection) is not None

    repository.mutate_processing(
        action="disable_local", expected_generation=1, policy=local_processing
    )
    repository.mutate_injection(
        action="disable_local", expected_generation=1, policy=local_injection
    )
    assert repository.valid_processing_snapshot(local_processing) is None
    assert repository.valid_injection_snapshot(local_injection) is None


@pytest.mark.parametrize(
    ("kind", "changes"),
    [
        ("processing", {"status": "corrupt"}),
        ("processing", {"generation": "not-an-int"}),
        ("processing", {"disclosed_fields_json": "{broken-json"}),
        ("injection", {"status": "corrupt"}),
        ("injection", {"generation": "not-an-int"}),
        ("injection", {"max_fragment_characters": "not-an-int"}),
        ("injection", {"max_fragment_characters": 2_000}),
        ("injection", {"disclosed_fields_json": "{broken-json"}),
        ("injection", {"max_fragment_count": 0}),
    ],
)
def test_corrupt_authority_rows_fail_closed(
    kind: str,
    changes: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    repository: SummaryAutomationRepository,
    connection: sqlite3.Connection,
    processing_policy: SummaryProcessingPolicy,
    injection_policy: SummaryInjectionPolicy,
) -> None:
    repository.mutate_processing(
        action="grant", expected_generation=0, policy=processing_policy
    )
    repository.mutate_injection(
        action="grant", expected_generation=0, policy=injection_policy
    )
    table = f"summary_{kind}_consents"
    row = dict(connection.execute(f"SELECT * FROM {table}").fetchone())
    row.update(changes)
    row_method = f"_{kind}_row"
    monkeypatch.setattr(repository, row_method, lambda _scope_id: row)

    snapshot_name = f"valid_{kind}_snapshot"
    getter_name = f"get_{kind}_authority"
    policy = processing_policy if kind == "processing" else injection_policy
    assert getattr(repository, snapshot_name)(policy) is None
    with pytest.raises(SummaryAuthorityStateError):
        getattr(repository, getter_name)()


@pytest.mark.parametrize(
    ("kind", "action", "route"),
    [
        ("processing", "grant", "local"),
        ("processing", "enable_local", "remote"),
        ("injection", "grant", "local"),
        ("injection", "enable_local", "remote"),
    ],
)
def test_route_and_mutation_action_must_agree(
    kind: str,
    action: str,
    route: str,
    repository: SummaryAutomationRepository,
    processing_policy: SummaryProcessingPolicy,
    injection_policy: SummaryInjectionPolicy,
) -> None:
    policy = replace(
        processing_policy if kind == "processing" else injection_policy,
        route=route,
    )
    mutate = (
        repository.mutate_processing
        if kind == "processing"
        else repository.mutate_injection
    )
    with pytest.raises(ValueError):
        mutate(action=action, expected_generation=0, policy=policy)
