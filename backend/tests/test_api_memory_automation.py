import asyncio
import json
import threading
import time
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import get_settings
from app.main import create_app
from app.providers.base import LLMResponse
from app.repositories.memory_automation import MemoryAutomationRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.memory_extractor import MEMORY_EXTRACTION_SCHEMA_VERSION

from app.domain.models import (
    ChatRole,
    MemoryAutomationMode,
    MemoryExtractionConsent,
    MemoryExtractionConsentStatus,
    MemoryExtractorRoute,
    MemoryGovernorDecision,
    MemoryGovernorProposal,
    MemoryGovernorResult,
    MemoryJob,
    MemoryJobAudit,
    MemoryJobAuditOutcome,
    MemoryJobStatus,
    MemoryType,
)
from app.domain.schemas import (
    MemoryExtractionConsentResponse,
    MemoryJobAuditResponse,
    MemoryJobResponse,
    UpdateMemoryExtractionConsentRequest,
)


def test_gate_a_domain_values_are_frozen():
    assert [item.value for item in MemoryAutomationMode] == [
        "off",
        "candidate_confirmation",
        "shadow_auto",
        "auto_active",
    ]
    assert [item.value for item in MemoryExtractorRoute] == [
        "none",
        "local",
        "fake",
        "remote",
    ]
    assert [item.value for item in MemoryExtractionConsentStatus] == [
        "unknown",
        "granted",
        "declined",
        "revoked",
    ]
    assert [item.value for item in MemoryJobStatus] == [
        "pending",
        "running",
        "succeeded",
        "failed",
        "cancelled",
    ]
    assert [item.value for item in MemoryGovernorDecision] == [
        "create",
        "support",
        "supersede",
        "conflict",
        "reject",
        "no_change",
    ]
    assert [item.value for item in MemoryJobAuditOutcome] == [
        "shadow_recorded",
        "completed_with_decisions",
        "skipped_no_extractor",
        "skipped_no_write_consent",
        "skipped_write_consent_changed",
        "skipped_turn_before_write_grant",
        "skipped_mode_changed",
        "skipped_no_consent",
        "skipped_consent_changed",
        "skipped_governor_policy",
        "invalid_output",
        "provider_error",
        "cancelled_session_deleted",
        "cancelled",
        "failed",
    ]


def test_memory_consent_mutation_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        UpdateMemoryExtractionConsentRequest.model_validate(
            {
                "action": "grant",
                "disclosure_version": "memory-extraction-disclosure-v1",
                "provider": "anthropic",
            }
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("action", "unknown"),
        ("disclosure_version", "memory-extraction-disclosure-v2"),
    ],
)
def test_memory_consent_mutation_requires_frozen_literals(field_name, value):
    payload = {
        "action": "grant",
        "disclosure_version": "memory-extraction-disclosure-v1",
    }
    payload[field_name] = value

    with pytest.raises(ValidationError):
        UpdateMemoryExtractionConsentRequest.model_validate(payload)


def test_default_unknown_consent_keeps_policy_fields_null_and_deployment_separate():
    now = datetime(2026, 7, 16, tzinfo=UTC)
    consent = MemoryExtractionConsent(
        scope_id="default",
        status=MemoryExtractionConsentStatus.UNKNOWN,
        purpose=None,
        provider=None,
        disclosure_version=None,
        disclosed_fields=(),
        generation=0,
        created_at=now,
        updated_at=now,
    )

    response = MemoryExtractionConsentResponse.model_validate(
        {
            "scope_id": consent.scope_id,
            "status": consent.status.value,
            "purpose": consent.purpose,
            "provider": consent.provider,
            "disclosure_version": consent.disclosure_version,
            "disclosed_fields": list(consent.disclosed_fields),
            "generation": consent.generation,
            "deployment_route": "remote",
            "deployment_provider": "anthropic",
            "deployment_configured": False,
            "created_at": consent.created_at,
            "updated_at": consent.updated_at,
        }
    )

    assert response.model_dump(mode="json") == {
        "scope_id": "default",
        "status": "unknown",
        "purpose": None,
        "provider": None,
        "disclosure_version": None,
        "disclosed_fields": [],
        "generation": 0,
        "deployment_route": "remote",
        "deployment_provider": "anthropic",
        "deployment_configured": False,
        "created_at": "2026-07-16T00:00:00Z",
        "updated_at": "2026-07-16T00:00:00Z",
    }


def test_gate_a_records_are_frozen_and_persisted_records_are_metadata_only():
    now = datetime(2026, 7, 16, tzinfo=UTC)
    job = MemoryJob(
        id="job-1",
        turn_id="assistant-1",
        schema_version="memory-shadow-schema-v1",
        session_id="session-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        mode=MemoryAutomationMode.SHADOW_AUTO,
        extractor_route=MemoryExtractorRoute.LOCAL,
        status=MemoryJobStatus.PENDING,
        attempt_count=0,
        outcome=None,
        error_category=None,
        governor_version="memory-governor-rules-v1",
        consent_generation=None,
        created_at=now,
        started_at=None,
        finished_at=None,
    )
    audit = MemoryJobAudit(
        id="audit-1",
        job_id=job.id,
        outcome=MemoryJobAuditOutcome.SHADOW_RECORDED,
        decision_counts={"create": 1},
        reason_counts={"eligible_shadow_create": 1},
        outcome_counts={},
        proposal_count=1,
        accepted_count=1,
        rejected_count=0,
        redaction_count=0,
        provider="local",
        model="memory-local-rules-v1",
        elapsed_ms=1,
        schema_version=job.schema_version,
        governor_version=job.governor_version,
        consent_generation=None,
        created_at=now,
    )

    with pytest.raises(FrozenInstanceError):
        job.status = MemoryJobStatus.RUNNING

    forbidden = {"content", "prompt", "response", "user_text", "assistant_text"}
    for record_type in (MemoryExtractionConsent, MemoryJob, MemoryJobAudit):
        assert forbidden.isdisjoint(field.name for field in fields(record_type))

    assert set(MemoryJobResponse.model_fields) == {
        field.name for field in fields(MemoryJob)
        if field.name != "auto_active_snapshot"
    }
    assert set(MemoryJobAuditResponse.model_fields) == {
        field.name for field in fields(MemoryJobAudit)
    }
    assert audit.proposal_count == 1


def test_governor_values_keep_content_transient():
    proposal = MemoryGovernorProposal(
        memory_type=MemoryType.PREFERENCE,
        subject="饮品偏好",
        content="用户喜欢黑咖啡",
        canonical_key_hint="drink:coffee",
        confidence=0.91,
        source_message_ids=("user-1",),
    )
    result = MemoryGovernorResult(
        decision=MemoryGovernorDecision.CREATE,
        reason_code="eligible_shadow_create",
        canonical_key="a" * 64,
        confidence=proposal.confidence,
        redaction_count=0,
    )

    assert proposal.content == "用户喜欢黑咖啡"
    assert "content" not in {field.name for field in fields(MemoryGovernorResult)}
    with pytest.raises(FrozenInstanceError):
        result.decision = MemoryGovernorDecision.REJECT


def test_get_memory_extraction_consent_defaults_to_unknown(client) -> None:
    response = client.get("/api/memories/extraction/consent")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "scope_id": "default",
        "status": "unknown",
        "purpose": None,
        "provider": None,
        "disclosure_version": None,
        "disclosed_fields": [],
        "generation": 0,
        "deployment_route": "none",
        "deployment_provider": "anthropic",
        "deployment_configured": True,
        "created_at": payload["created_at"],
        "updated_at": payload["updated_at"],
    }


def test_memory_extraction_consent_mutations_use_server_policy_and_generation(
    client,
) -> None:
    generations: list[int] = []
    for action, expected_status in (
        ("grant", "granted"),
        ("decline", "declined"),
        ("revoke", "revoked"),
    ):
        response = client.put(
            "/api/memories/extraction/consent",
            json={
                "action": action,
                "disclosure_version": "memory-extraction-disclosure-v1",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == expected_status
        assert payload["purpose"] == (
            "extract durable memory proposals from the current completed turn"
        )
        assert payload["provider"] == "anthropic"
        assert payload["disclosure_version"] == "memory-extraction-disclosure-v1"
        assert payload["disclosed_fields"] == ["user_message", "assistant_message"]
        generations.append(payload["generation"])

    assert generations == [1, 2, 3]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"action": "grant"},
        {
            "action": "grant",
            "disclosure_version": "memory-extraction-disclosure-v1",
            "provider": "anthropic",
        },
    ],
)
def test_memory_extraction_consent_http_input_is_strict(client, payload) -> None:
    assert (
        client.put("/api/memories/extraction/consent", json=payload).status_code == 422
    )


def _seed_completed_memory_jobs(count: int = 3) -> None:
    settings = get_settings()
    with managed_connection(settings.database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        automation = MemoryAutomationRepository(connection)
        session = sessions.create("automation api seed")
        for index in range(count):
            user = messages.add(session.id, ChatRole.USER, f"user seed {index}")
            assistant = messages.add(
                session.id,
                ChatRole.ASSISTANT,
                f"assistant seed {index}",
            )
            job, created = automation.reserve_job(
                turn_id=assistant.id,
                schema_version=MEMORY_EXTRACTION_SCHEMA_VERSION,
                session_id=session.id,
                user_message_id=user.id,
                assistant_message_id=assistant.id,
                mode=MemoryAutomationMode.SHADOW_AUTO,
                extractor_route=MemoryExtractorRoute.LOCAL,
                governor_version="memory-governor-rules-v1",
            )
            assert created
            automation.update_job_status(job.id, status=MemoryJobStatus.RUNNING)
            automation.complete_job_with_audit(
                job.id,
                status=MemoryJobStatus.SUCCEEDED,
                outcome=MemoryJobAuditOutcome.SHADOW_RECORDED,
                decision_counts={},
                reason_counts={},
                proposal_count=0,
                accepted_count=0,
                rejected_count=0,
                redaction_count=0,
                provider="local",
                model="memory-local-rules-v1",
                elapsed_ms=1,
                consent_generation=None,
            )


def test_memory_job_and_audit_lists_are_bounded_sorted_and_metadata_only(client) -> None:
    _seed_completed_memory_jobs(3)
    jobs_response = client.get("/api/memories/jobs?limit=2")
    audits_response = client.get("/api/memories/jobs/audits?limit=2")

    assert jobs_response.status_code == 200
    assert audits_response.status_code == 200
    assert len(jobs_response.json()) == 2
    assert len(audits_response.json()) == 2
    assert jobs_response.json()[0]["created_at"] >= jobs_response.json()[1]["created_at"]
    assert audits_response.json()[0]["created_at"] >= audits_response.json()[1][
        "created_at"
    ]

    forbidden_keys = {
        "content",
        "prompt",
        "response",
        "user_text",
        "assistant_text",
        "proposal",
        "canonical_key",
        "secret",
        "authorization",
        "api_key",
    }
    for payload in (jobs_response.json(), audits_response.json()):
        assert forbidden_keys.isdisjoint(key for item in payload for key in item)


@pytest.mark.parametrize(
    "path",
    [
        "/api/memories/jobs?limit=0",
        "/api/memories/jobs?limit=101",
        "/api/memories/jobs/audits?limit=0",
        "/api/memories/jobs/audits?limit=101",
    ],
)
def test_memory_automation_list_limits_are_strict(client, path: str) -> None:
    assert client.get(path).status_code == 422


class BlockingConsentFenceProvider:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    async def generate(self, messages, options) -> LLMResponse:
        self.calls += 1
        self.started.set()
        await asyncio.to_thread(self.release.wait)
        disclosed = json.loads(messages[1].content)
        return LLMResponse(
            text=json.dumps(
                {
                    "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
                    "proposals": [
                        {
                            "memory_type": "preference",
                            "subject": "drink",
                            "content": "SECRET_SENTINEL_SHOULD_NOT_PERSIST",
                            "canonical_key_hint": None,
                            "confidence": 0.9,
                            "source_message_ids": [disclosed["user_message"]["id"]],
                        }
                    ],
                }
            ),
            provider="blocking-test-provider",
            model=options.model,
        )

    async def aclose(self) -> None:
        return None


def _configure_blocking_remote_app(monkeypatch, tmp_path: Path, *, name: str):
    database_url = f"sqlite:///{tmp_path / f'{name}.db'}"
    for variable, value in {
        "DATABASE_URL": database_url,
        "LLM_PROVIDER": "fake",
        "LLM_MODEL": "test-model",
        "MEMORY_AUTOMATION_MODE": "shadow_auto",
        "MEMORY_EXTRACTOR_ROUTE": "remote",
        "MEMORY_EXTRACTOR_PROVIDER": "anthropic",
        "MEMORY_EXTRACTOR_MODEL": "memory-test-model",
        "ANTHROPIC_API_KEY": "test-anthropic-key",
        "MEMORY_CANDIDATES_ENABLED": "false",
        "EMOTION_ANALYSIS_ENABLED": "false",
        "SESSION_SUMMARY_PROVIDER": "fake",
    }.items():
        monkeypatch.setenv(variable, value)
    get_settings.cache_clear()
    provider = BlockingConsentFenceProvider()
    return provider, create_app(memory_extractor_provider_factory=lambda: provider)


def _start_blocked_shadow_job(test_client: TestClient, provider) -> None:
    grant = test_client.put(
        "/api/memories/extraction/consent",
        json={
            "action": "grant",
            "disclosure_version": "memory-extraction-disclosure-v1",
        },
    )
    assert grant.status_code == 200
    session = test_client.post("/api/sessions", json={"title": "fence"}).json()
    chat = test_client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "我喜欢红茶。"},
    )
    assert chat.status_code == 200
    assert provider.started.wait(timeout=1)


def _release_and_require_revoker_stopped(
    provider,
    revoker: threading.Thread | None,
) -> None:
    provider.release.set()
    if revoker is not None:
        revoker.join(timeout=2)
        assert not revoker.is_alive(), "revoke request thread did not terminate"


def test_inflight_remote_job_cleanup_survives_testclient_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    provider, app = _configure_blocking_remote_app(
        monkeypatch,
        tmp_path,
        name="route-fence-failure",
    )
    revoker: threading.Thread | None = None
    result: dict[str, object] = {}

    try:
        with pytest.raises(RuntimeError, match="forced test failure"):
            with TestClient(app) as test_client:
                try:
                    _start_blocked_shadow_job(test_client, provider)

                    def revoke() -> None:
                        result["response"] = test_client.put(
                            "/api/memories/extraction/consent",
                            json={
                                "action": "revoke",
                                "disclosure_version": "memory-extraction-disclosure-v1",
                            },
                        )

                    revoker = threading.Thread(target=revoke)
                    revoker.start()
                    deadline = time.monotonic() + 2
                    while not app.state.memory_extraction_dispatch_fence.has_pending_consent_mutation():
                        if time.monotonic() >= deadline:
                            raise AssertionError(
                                "revoke did not reach the lifespan fence"
                            )
                        time.sleep(0.01)
                    raise RuntimeError("forced test failure")
                finally:
                    _release_and_require_revoker_stopped(provider, revoker)
    finally:
        get_settings.cache_clear()

    assert provider.release.is_set()
    assert provider.calls == 1
    assert result["response"].status_code == 200


def test_revoke_route_shares_lifespan_fence_with_inflight_remote_job(
    monkeypatch,
    tmp_path: Path,
) -> None:
    provider, app = _configure_blocking_remote_app(
        monkeypatch,
        tmp_path,
        name="route-fence",
    )

    revoker: threading.Thread | None = None
    try:
        with TestClient(app) as test_client:
            try:
                _start_blocked_shadow_job(test_client, provider)

                result: dict[str, object] = {}

                def revoke() -> None:
                    result["response"] = test_client.put(
                        "/api/memories/extraction/consent",
                        json={
                            "action": "revoke",
                            "disclosure_version": "memory-extraction-disclosure-v1",
                        },
                    )

                revoker = threading.Thread(target=revoke)
                revoker.start()
                deadline = time.monotonic() + 2
                while not app.state.memory_extraction_dispatch_fence.has_pending_consent_mutation():
                    if time.monotonic() >= deadline:
                        raise AssertionError("revoke did not reach the lifespan fence")
                    time.sleep(0.01)
                provider.release.set()
                revoker.join(timeout=2)
                assert not revoker.is_alive()
                assert result["response"].status_code == 200

                deadline = time.monotonic() + 2
                while True:
                    jobs = test_client.get("/api/memories/jobs").json()
                    if jobs and jobs[0]["status"] in {
                        "succeeded",
                        "failed",
                        "cancelled",
                    }:
                        break
                    if time.monotonic() >= deadline:
                        raise AssertionError("memory job did not terminate")
                    time.sleep(0.01)
                audits = test_client.get("/api/memories/jobs/audits").json()
            finally:
                _release_and_require_revoker_stopped(provider, revoker)
    finally:
        get_settings.cache_clear()

    assert provider.calls == 1
    assert jobs[0]["outcome"] == "skipped_consent_changed"
    assert audits[0]["outcome"] == "skipped_consent_changed"
    assert audits[0]["proposal_count"] == 0
    assert "SECRET_SENTINEL_SHOULD_NOT_PERSIST" not in repr(jobs)
    assert "SECRET_SENTINEL_SHOULD_NOT_PERSIST" not in repr(audits)
