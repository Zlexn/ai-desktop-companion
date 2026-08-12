from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import ChatRole
from app.main import create_app
from app.providers.fake_provider import FakeProvider
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.messages import MessageRepository
from app.repositories.session_summaries import SessionSummaryRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.repositories.summary_automation import SummaryAutomationRepository
from app.repositories.summary_public import SummaryPublicRepository
from app.services.session_summary_service import (
    SummaryJobReservationService,
    build_summary_processing_policy,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'summary-api.db'}",
        memory_source_reference_key_path=str(tmp_path / "summary-api.key"),
        session_summary_enabled=True,
        session_summary_provider="fake",
        llm_provider="fake",
        llm_model="fake-model",
    )


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings_override=settings)) as value:
        yield value


def _walk_keys(value) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(key)
            keys.update(_walk_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_walk_keys(item))
    return keys


def _grant_local_authorities(client: TestClient) -> None:
    processing = client.get("/api/summaries/processing-consent").json()
    assert client.put(
        "/api/summaries/processing-consent",
        json={
            "action": "enable_local",
            "expected_generation": processing["generation"],
        },
    ).status_code == 200
    injection = client.get("/api/summaries/injection-consent").json()
    assert client.put(
        "/api/summaries/injection-consent",
        json={
            "action": "enable_local",
            "expected_generation": injection["generation"],
        },
    ).status_code == 200


def _wait_for_summary(
    client: TestClient,
    session_id: str,
) -> dict[str, object]:
    for _ in range(100):
        items = client.get(
            f"/api/summaries?session_id={session_id}&limit=100"
        ).json()["items"]
        if items:
            return items[0]
        time.sleep(0.01)
    raise AssertionError("summary job did not complete")


def _seed_failed_incremental_job(settings: Settings) -> tuple[str, str]:
    with managed_connection(settings.database_url) as connection:
        session = SessionRepository(connection).create("retry API")
        user = MessageRepository(connection).add(
            session.id,
            ChatRole.USER,
            "retry source user",
        )
        _, turn = ChatTurnRepository(connection).append_assistant_turn(
            session_id=session.id,
            user_message_id=user.id,
            content="retry source assistant",
            metadata={},
        )
        reservation = SummaryJobReservationService(
            connection,
            settings=replace(
                settings,
                session_summary_trigger_turn_count=1,
                session_summary_max_input_turns=2,
                session_summary_max_input_messages=4,
            ),
        ).reserve_for_turn(session.id, turn.id)
        assert reservation is not None
        job = reservation[0]
        repository = SummaryAutomationRepository(connection)
        repository.claim_job(job.id, max_attempts=3)
        repository.fail_job(job.id)
        return job.id, session.id


def test_summary_capabilities_and_status_are_safe(client: TestClient) -> None:
    capabilities = client.get("/api/summaries/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json() == {
        "summary_processing": True,
        "summary_injection": True,
        "processing_route": "local",
        "processing_provider": "fake",
        "processing_model": "fake-session-summary-v1",
        "injection_route": "local",
        "injection_provider": "fake",
        "injection_model": "fake-model",
        "remote_summary": "local_summary_available",
    }

    status = client.get("/api/summaries/status")
    assert status.status_code == 200
    assert status.json()["summary_counts"] == {}
    assert status.json()["job_counts"] == {}


def test_processing_and_injection_decisions_are_independent_and_cas_bound(
    client: TestClient,
) -> None:
    processing = client.get("/api/summaries/processing-consent").json()
    injection = client.get("/api/summaries/injection-consent").json()
    assert processing["status"] == "unknown"
    assert injection["status"] == "unknown"
    assert "policy_fingerprint" not in processing
    assert "policy_fingerprint" not in injection

    granted = client.put(
        "/api/summaries/processing-consent",
        json={
            "action": "enable_local",
            "expected_generation": processing["generation"],
        },
    )
    assert granted.status_code == 200
    assert granted.json()["status"] == "granted"
    assert client.get("/api/summaries/injection-consent").json()["status"] == "unknown"

    stale = client.put(
        "/api/summaries/processing-consent",
        json={"action": "disable_local", "expected_generation": 0},
    )
    assert stale.status_code == 409

    enabled = client.put(
        "/api/summaries/injection-consent",
        json={
            "action": "enable_local",
            "expected_generation": injection["generation"],
        },
    )
    assert enabled.status_code == 200
    assert enabled.json()["max_fragment_count"] > 0
    assert enabled.json()["max_fragment_characters"] > 0
    assert enabled.json()["max_total_characters"] > 0


@pytest.mark.parametrize(
    "path",
    [
        "/api/summaries?limit=100",
        "/api/summaries/jobs?limit=100",
        "/api/summaries/audits?limit=100",
    ],
)
def test_summary_public_pages_omit_private_fields(
    client: TestClient,
    path: str,
) -> None:
    response = client.get(path)
    assert response.status_code == 200
    document = response.json()
    assert document == {"items": [], "next_cursor": None}
    forbidden = {
        "source_set_hash",
        "logical_source_identity",
        "attempt_epoch",
        "policy_fingerprint",
        "rebuild_permit_id",
        "raw_response",
        "prompt",
        "source_message_ids",
        "source_turn_ids",
    }
    assert forbidden.isdisjoint(_walk_keys(document))


def test_summary_pages_enforce_bounded_pagination(client: TestClient) -> None:
    assert client.get("/api/summaries?limit=0").status_code == 422
    assert client.get("/api/summaries/jobs?limit=101").status_code == 422
    assert client.get("/api/summaries/audits?cursor=invalid").status_code == 400


def test_summary_mutations_require_exact_schemas(client: TestClient) -> None:
    processing = client.get("/api/summaries/processing-consent").json()
    assert client.put(
        "/api/summaries/processing-consent",
        json={
            "action": "enable_local",
            "expected_generation": processing["generation"],
            "unexpected": True,
        },
    ).status_code == 422

    assert client.post(
        "/api/summaries/missing/redact",
        json={
            "expected_suppression_generation": 0,
            "confirmation": "wrong",
        },
    ).status_code == 422
    assert client.post(
        "/api/summaries/missing/redact",
        json={
            "expected_suppression_generation": 0,
            "confirmation": "redact_summary_payload",
        },
    ).status_code == 404
    assert client.post(
        "/api/summaries/missing/rebuild",
        json={"expected_suppression_generation": 0},
    ).status_code == 404
    assert client.post(
        "/api/summaries/jobs/missing/retry",
        json={"expected_status": "failed"},
    ).status_code == 404
    assert client.post(
        "/api/summaries/jobs/missing/cancel",
        json={"expected_status": "pending"},
    ).status_code == 404


@pytest.mark.parametrize(
    ("authority_path", "changed_settings"),
    [
        (
            "/api/summaries/processing-consent",
            {"session_summary_llm_model": "changed-summary-model"},
        ),
        (
            "/api/summaries/processing-consent",
            {"deepseek_base_url": "https://changed-processing.invalid/v1"},
        ),
        (
            "/api/summaries/injection-consent",
            {"llm_model": "changed-chat-model"},
        ),
        (
            "/api/summaries/injection-consent",
            {"deepseek_base_url": "https://changed-injection.invalid/v1"},
        ),
    ],
)
def test_historical_remote_grant_is_stale_after_current_policy_change(
    tmp_path: Path,
    authority_path: str,
    changed_settings: dict[str, object],
) -> None:
    original = Settings(
        database_url=f"sqlite:///{tmp_path / 'stale-policy.db'}",
        memory_source_reference_key_path=tmp_path / "stale-policy.key",
        session_summary_enabled=True,
        session_summary_provider="llm",
        session_summary_llm_provider="deepseek",
        session_summary_llm_model="summary-model",
        llm_provider="deepseek",
        llm_model="chat-model",
        deepseek_base_url="https://original.invalid/v1",
    )
    app = create_app(
        settings_override=original,
        chat_provider_factory=lambda: FakeProvider(),
    )
    with TestClient(app) as first:
        current = first.get(authority_path).json()
        granted = first.put(
            authority_path,
            json={"action": "grant", "expected_generation": current["generation"]},
        )
        assert granted.status_code == 200
        assert granted.json()["valid_for_current_policy"] is True

    changed = replace(original, **changed_settings)
    changed_app = create_app(
        settings_override=changed,
        chat_provider_factory=lambda: FakeProvider(),
    )
    with TestClient(changed_app) as second:
        response = second.get(authority_path)
        assert response.status_code == 200
        assert response.json()["status"] == "granted"
        assert response.json()["valid_for_current_policy"] is False
        assert response.json()["reason_code"] == "not_granted_for_current_policy"


def test_summary_cursor_is_bound_to_exact_session_filter() -> None:
    cursor_a = SummaryPublicRepository.encode_cursor(
        1,
        kind="summaries",
        filter_value="session-a",
    )
    unfiltered = SummaryPublicRepository.encode_cursor(1, kind="summaries")

    with pytest.raises(ValueError, match="invalid summary cursor"):
        SummaryPublicRepository.decode_cursor(
            cursor_a,
            kind="summaries",
            filter_value="session-b",
        )
    with pytest.raises(ValueError, match="invalid summary cursor"):
        SummaryPublicRepository.decode_cursor(
            cursor_a,
            kind="summaries",
            filter_value=None,
        )
    with pytest.raises(ValueError, match="invalid summary cursor"):
        SummaryPublicRepository.decode_cursor(
            unfiltered,
            kind="summaries",
            filter_value="session-a",
        )


def test_disabled_summary_capabilities_agree_and_grant_no_authority(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'disabled.db'}",
        memory_source_reference_key_path=tmp_path / "disabled.key",
        session_summary_enabled=False,
        session_summary_provider="llm",
        session_summary_llm_provider="deepseek",
        llm_provider="deepseek",
    )
    app = create_app(
        settings_override=settings,
        chat_provider_factory=lambda: FakeProvider(),
    )
    with TestClient(app) as disabled:
        summary = disabled.get("/api/summaries/capabilities").json()
        persona = disabled.get("/api/persona/capabilities").json()
        assert summary["summary_processing"] is False
        assert summary["summary_injection"] is False
        assert summary["remote_summary"] == "summary_disabled"
        assert persona["summary_processing"] is False
        assert persona["summary_injection"] is False
        assert persona["remote_summary"] == "summary_disabled"
        assert disabled.get("/api/summaries/processing-consent").json()[
            "status"
        ] == "unknown"
        assert disabled.get("/api/summaries/injection-consent").json()[
            "status"
        ] == "unknown"
        assert disabled.put(
            "/api/summaries/processing-consent",
            json={"action": "grant", "expected_generation": 0},
        ).status_code == 400
        assert disabled.put(
            "/api/summaries/injection-consent",
            json={"action": "grant", "expected_generation": 0},
        ).status_code == 400


def test_persisted_grants_become_invalid_and_inert_when_capability_is_disabled(
    tmp_path: Path,
) -> None:
    enabled = Settings(
        database_url=f"sqlite:///{tmp_path / 'disable-after-grant.db'}",
        memory_source_reference_key_path=tmp_path / "disable-after-grant.key",
        session_summary_enabled=True,
        session_summary_provider="fake",
        session_summary_trigger_turn_count=1,
        session_summary_max_input_turns=2,
        session_summary_max_input_messages=4,
        summary_injection_min_lexical_relevance=0.0,
        llm_provider="fake",
        llm_model="fake-model",
    )
    source_session_id: str
    failed_job_id: str
    summary_id: str
    with TestClient(create_app(settings_override=enabled)) as first:
        _grant_local_authorities(first)
        source = first.post("/api/sessions", json={"title": "source"}).json()
        source_session_id = source["id"]
        assert first.post(
            f"/api/sessions/{source_session_id}/messages",
            json={"content": "persisted disabled summary marker"},
        ).status_code == 200
        summary_id = str(_wait_for_summary(first, source_session_id)["id"])
        failed_job_id, _ = _seed_failed_incremental_job(enabled)

    disabled = replace(enabled, session_summary_enabled=False)
    chat_provider = FakeProvider()
    app = create_app(
        settings_override=disabled,
        chat_provider_factory=lambda: chat_provider,
    )
    with TestClient(app) as second:
        processing = second.get("/api/summaries/processing-consent").json()
        injection = second.get("/api/summaries/injection-consent").json()
        assert processing["status"] == "granted"
        assert injection["status"] == "granted"
        assert processing["valid_for_current_policy"] is False
        assert injection["valid_for_current_policy"] is False

        active = second.post("/api/sessions", json={"title": "active"}).json()
        chat = second.post(
            f"/api/sessions/{active['id']}/messages",
            json={"content": "persisted disabled summary marker"},
        )
        assert chat.status_code == 200
        messages = second.get(
            f"/api/sessions/{active['id']}/messages"
        ).json()
        assert messages[-1]["metadata"]["context_manifest"][
            "selected_summary_ids"
        ] == []
        assert all(
            "persisted disabled summary marker" not in message.content
            for message in chat_provider.calls[0]
            if message.role is not ChatRole.USER
        )

        before_jobs = second.get("/api/summaries/jobs?limit=100").json()["items"]
        retry = second.post(
            f"/api/summaries/jobs/{failed_job_id}/retry",
            json={"expected_status": "failed"},
        )
        rebuild = second.post(
            f"/api/summaries/{summary_id}/rebuild",
            json={"expected_suppression_generation": 0},
        )
        assert retry.status_code == 409
        assert rebuild.status_code == 400
        after_jobs = second.get("/api/summaries/jobs?limit=100").json()["items"]
        assert [item["id"] for item in after_jobs] == [
            item["id"] for item in before_jobs
        ]

        assert second.put(
            "/api/summaries/processing-consent",
            json={
                "action": "disable_local",
                "expected_generation": processing["generation"],
            },
        ).status_code == 200
        assert second.put(
            "/api/summaries/injection-consent",
            json={
                "action": "disable_local",
                "expected_generation": injection["generation"],
            },
        ).status_code == 200


def test_stale_barrier_redaction_has_safe_public_label(settings: Settings) -> None:
    with TestClient(create_app(settings_override=settings)) as api:
        session = api.post("/api/sessions", json={"title": "stale"}).json()
        with managed_connection(settings.database_url) as connection:
            summary = SessionSummaryRepository(connection).create(
                session_id=session["id"],
                summary_text="STALE_PRIVATE_PAYLOAD",
            )
            connection.execute(
                "INSERT INTO summary_redaction_guards (summary_id) VALUES (?)",
                (summary.id,),
            )
            connection.execute(
                "UPDATE session_summaries SET summary_text=NULL, "
                "metadata_json='{}', payload_state='redacted', "
                "provenance_state='legacy_unverified', source_set_hash=NULL, "
                "summarizer_schema_version=NULL, injection_schema_version=NULL, "
                "redacted_at='2026-07-25T00:00:00+00:00', "
                "redaction_reason_code='migration_stale_barrier' WHERE id=?",
                (summary.id,),
            )
            connection.commit()

        public = api.get(f"/api/summaries/{summary.id}")
        assert public.status_code == 200
        assert public.json()["summary_text"] is None
        assert public.json()["unavailable_label"] == "状态已过期"
        assert "redaction_reason_code" not in public.json()
        assert "STALE_PRIVATE_PAYLOAD" not in public.text



def test_summary_http_cursor_rejects_cross_filter_reuse(
    settings: Settings,
) -> None:
    with TestClient(create_app(settings_override=settings)) as api:
        first = api.post("/api/sessions", json={"title": "A"}).json()
        second = api.post("/api/sessions", json={"title": "B"}).json()
        with managed_connection(settings.database_url) as connection:
            summaries = SessionSummaryRepository(connection)
            summaries.create(session_id=first["id"], summary_text="first")
            summaries.create(session_id=first["id"], summary_text="second")
            summaries.create(session_id=second["id"], summary_text="other")

        page = api.get(
            f"/api/summaries?session_id={first['id']}&limit=1"
        ).json()
        assert page["next_cursor"] is not None
        assert api.get(
            f"/api/summaries?session_id={second['id']}&limit=1"
            f"&cursor={page['next_cursor']}"
        ).status_code == 400
        assert api.get(
            f"/api/summaries?limit=1&cursor={page['next_cursor']}"
        ).status_code == 400

        unfiltered = api.get("/api/summaries?limit=1").json()
        assert unfiltered["next_cursor"] is not None
        assert api.get(
            f"/api/summaries?session_id={first['id']}&limit=1"
            f"&cursor={unfiltered['next_cursor']}"
        ).status_code == 400


def test_incremental_retry_deduplicates_unchanged_epoch(
    settings: Settings,
) -> None:
    with TestClient(create_app(settings_override=settings)) as api:
        _grant_local_authorities(api)
        job_id, _ = _seed_failed_incremental_job(settings)
        response = api.post(
            f"/api/summaries/jobs/{job_id}/retry",
            json={"expected_status": "failed"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "outcome": "retry_deduplicated",
            "summary_id": None,
            "job_id": job_id,
            "status": "failed",
            "suppression_generation": None,
            "suppression_state": None,
        }


def test_incremental_retry_uses_new_authority_epoch_and_completes(
    settings: Settings,
) -> None:
    with TestClient(create_app(settings_override=settings)) as api:
        _grant_local_authorities(api)
        job_id, session_id = _seed_failed_incremental_job(settings)
        current = api.get("/api/summaries/processing-consent").json()
        assert api.put(
            "/api/summaries/processing-consent",
            json={
                "action": "disable_local",
                "expected_generation": current["generation"],
            },
        ).status_code == 200
        disabled = api.get("/api/summaries/processing-consent").json()
        assert api.put(
            "/api/summaries/processing-consent",
            json={
                "action": "enable_local",
                "expected_generation": disabled["generation"],
            },
        ).status_code == 200

        response = api.post(
            f"/api/summaries/jobs/{job_id}/retry",
            json={"expected_status": "failed"},
        )
        assert response.status_code == 200
        assert response.json()["outcome"] == "retry_scheduled"
        assert response.json()["job_id"] != job_id

        retried = None
        summaries = []
        for _ in range(100):
            jobs = api.get("/api/summaries/jobs?limit=100").json()["items"]
            retried = next(
                item for item in jobs if item["id"] == response.json()["job_id"]
            )
            if retried["status"] != "pending":
                summaries = api.get(
                    f"/api/summaries?session_id={session_id}"
                ).json()["items"]
                break
            time.sleep(0.01)
        assert retried is not None
        assert retried["status"] == "succeeded"
        assert len(summaries) == 1
        assert summaries[0]["summary_text"]


def test_incremental_retry_fails_closed_without_current_authority(
    settings: Settings,
) -> None:
    with TestClient(create_app(settings_override=settings)) as api:
        _grant_local_authorities(api)
        job_id, _ = _seed_failed_incremental_job(settings)
        current = api.get("/api/summaries/processing-consent").json()
        assert api.put(
            "/api/summaries/processing-consent",
            json={
                "action": "disable_local",
                "expected_generation": current["generation"],
            },
        ).status_code == 200

        response = api.post(
            f"/api/summaries/jobs/{job_id}/retry",
            json={"expected_status": "failed"},
        )
        assert response.status_code == 409
        with managed_connection(settings.database_url) as connection:
            jobs = SummaryAutomationRepository(connection).list_jobs()
            assert [job.id for job in jobs] == [job_id]
