from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import threading
import time

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import ChatRole
from app.main import create_app
from app.providers.base import LLMResponse
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.repositories.summary_automation import SummaryAutomationRepository
from app.services.session_summary_provider import SessionSummaryProviderResult
from app.services.session_summary_contract import (
    SUMMARY_JOB_SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
)
from app.services.session_summary_service import (
    SummaryJobReservationService,
    build_summary_processing_policy,
)
from app.services.summary_job_service import SummaryJobService


_TERMINAL_SUMMARY_STATUSES = {
    "succeeded",
    "failed",
    "cancelled",
    "skipped",
}


class RecordingChatProvider:
    provider_name = "deepseek"

    def __init__(self) -> None:
        self.calls = []

    async def generate(self, messages, options):
        self.calls.append(messages)
        return LLMResponse(
            text="Gate C2 safe reply",
            provider=self.provider_name,
            model=options.model,
        )

    async def aclose(self) -> None:
        pass


class RecordingSummaryProvider:
    def __init__(self, text: str = "LOW_TRUST_SUMMARY_MARKER") -> None:
        self.text = text
        self.calls = 0
        self.closed = False

    async def generate(self, messages, options):
        self.calls += 1
        return SessionSummaryProviderResult(
            text=self.text,
            provider="deepseek",
            model="summary-model",
        )

    async def aclose(self) -> None:
        self.closed = True


class BlockingChatProvider(RecordingChatProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    async def generate(self, messages, options):
        self.calls.append(messages)
        self.started.set()
        released = await asyncio.to_thread(self.release.wait, 5)
        if not released:
            raise TimeoutError("HTTP smoke did not release chat Provider")
        return LLMResponse(
            text="Gate C2 reply after disclosure mutation",
            provider=self.provider_name,
            model=options.model,
        )

    async def aclose(self) -> None:
        self.release.set()


class BlockingSummaryProvider(RecordingSummaryProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    async def generate(self, messages, options):
        self.calls += 1
        self.started.set()
        released = await asyncio.to_thread(self.release.wait, 5)
        if not released:
            raise TimeoutError("HTTP smoke did not release summary Provider")
        return SessionSummaryProviderResult(
            text=self.text,
            provider="deepseek",
            model="summary-model",
        )



def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "database_url": f"sqlite:///{tmp_path / 'gate-c2-http-smoke.db'}",
        "memory_source_reference_key_path": tmp_path / "gate-c2-source.key",
        "llm_provider": "deepseek",
        "llm_model": "chat-model",
        "deepseek_api_key": "test-only-never-sent",
        "session_summary_enabled": True,
        "session_summary_provider": "llm",
        "session_summary_llm_provider": "deepseek",
        "session_summary_llm_model": "summary-model",
        "session_summary_trigger_turn_count": 1,
        "session_summary_max_input_turns": 3,
        "session_summary_max_input_messages": 6,
        "summary_injection_min_lexical_relevance": 0.0,
        "summary_rebuild_min_safe_turns": 1,
    }
    values.update(overrides)
    return Settings(**values)



def _grant(client: TestClient, path: str) -> dict:
    current = client.get(path).json()
    response = client.put(
        path,
        json={"action": "grant", "expected_generation": current["generation"]},
    )
    assert response.status_code == 200
    assert response.json()["valid_for_current_policy"] is True
    return response.json()



def _mutate(client: TestClient, path: str, action: str) -> dict:
    current = client.get(path).json()
    response = client.put(
        path,
        json={"action": action, "expected_generation": current["generation"]},
    )
    assert response.status_code == 200
    return response.json()



def _send_turn(client: TestClient, session_id: str, content: str) -> dict:
    response = client.post(
        f"/api/sessions/{session_id}/messages",
        json={"content": content},
    )
    assert response.status_code == 200
    return response.json()



def _wait_for_job(
    client: TestClient,
    *,
    job_id: str | None = None,
    after_id: str | None = None,
) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get("/api/summaries/jobs", params={"limit": 100})
        assert response.status_code == 200
        jobs = response.json()["items"]
        selected = (
            next((job for job in jobs if job["id"] == job_id), None)
            if job_id is not None
            else next(
                (job for job in jobs if after_id is None or job["id"] != after_id),
                None,
            )
        )
        if selected is not None and selected["status"] in _TERMINAL_SUMMARY_STATUSES:
            return selected
        time.sleep(0.01)
    raise AssertionError("summary job did not reach a terminal state")



def _wait_for_summary(client: TestClient, session_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(
            "/api/summaries",
            params={"session_id": session_id, "limit": 100},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        if items:
            return items[0]
        time.sleep(0.01)
    raise AssertionError("summary was not generated")



def _manifest(client: TestClient, session_id: str) -> dict:
    messages = client.get(f"/api/sessions/{session_id}/messages").json()
    return messages[-1]["metadata"]["context_manifest"]



def test_remote_processing_and_injection_require_independent_exact_grants(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    chat_provider = RecordingChatProvider()
    summary_provider = RecordingSummaryProvider()
    summary_factory_calls = 0

    def summary_factory():
        nonlocal summary_factory_calls
        summary_factory_calls += 1
        return summary_provider

    with TestClient(
        create_app(
            settings_override=settings,
            chat_provider_factory=lambda: chat_provider,
            summary_provider_factory=summary_factory,
        )
    ) as client:
        source = client.post("/api/sessions", json={"title": "summary source"}).json()
        _send_turn(client, source["id"], "summary continuity marker")
        skipped = _wait_for_job(client)
        assert skipped["status"] == "skipped"
        assert skipped["reason_code"] == "skipped_no_consent"
        assert summary_factory_calls == 0
        assert summary_provider.calls == 0

        _grant(client, "/api/summaries/processing-consent")
        _send_turn(client, source["id"], "summary continuity marker")
        completed = _wait_for_job(client, after_id=skipped["id"])
        if completed["status"] != "succeeded":
            raise AssertionError(repr(completed))
        summary = _wait_for_summary(client, source["id"])
        assert summary_provider.calls == 1

        active = client.post("/api/sessions", json={"title": "active chat"}).json()
        _send_turn(client, active["id"], "summary continuity marker")
        assert _manifest(client, active["id"])["selected_summary_ids"] == []

        _grant(client, "/api/summaries/injection-consent")
        _send_turn(client, active["id"], "summary continuity marker")
        assert _manifest(client, active["id"])["selected_summary_ids"] == [
            summary["id"]
        ]
        assert any(
            "LOW_TRUST_SUMMARY_MARKER" in message.content
            for message in chat_provider.calls[-1]
        )

        _mutate(client, "/api/summaries/injection-consent", "revoke")
        _send_turn(client, active["id"], "summary continuity marker")
        assert _manifest(client, active["id"])["selected_summary_ids"] == []
        assert all(
            "LOW_TRUST_SUMMARY_MARKER" not in message.content
            for message in chat_provider.calls[-1]
        )



def test_policy_changes_invalidate_processing_and_every_injection_bound(
    tmp_path: Path,
) -> None:
    original = _settings(tmp_path)
    with TestClient(
        create_app(
            settings_override=original,
            chat_provider_factory=RecordingChatProvider,
            summary_provider_factory=RecordingSummaryProvider,
        )
    ) as first:
        _grant(first, "/api/summaries/processing-consent")
        _grant(first, "/api/summaries/injection-consent")

    variants = (
        replace(original, session_summary_llm_model="changed-summary-model"),
        replace(original, summary_injection_max_fragments=1),
        replace(original, summary_injection_max_fragment_characters=999),
        replace(original, summary_injection_max_total_characters=1599),
        replace(original, llm_model="changed-chat-model"),
    )
    for index, changed in enumerate(variants):
        chat_provider = RecordingChatProvider()
        with TestClient(
            create_app(
                settings_override=changed,
                chat_provider_factory=lambda: chat_provider,
                summary_provider_factory=RecordingSummaryProvider,
            )
        ) as client:
            processing = client.get("/api/summaries/processing-consent").json()
            injection = client.get("/api/summaries/injection-consent").json()
            if index == 0:
                assert processing["valid_for_current_policy"] is False
            else:
                assert injection["valid_for_current_policy"] is False
            active = client.post(
                "/api/sessions", json={"title": f"changed policy {index}"}
            ).json()
            _send_turn(client, active["id"], "summary continuity marker")
            if index != 0:
                assert _manifest(client, active["id"])["selected_summary_ids"] == []



def test_processing_revoke_before_dispatch_blocks_remote_provider_construction(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    summary_factory_calls = 0

    def forbidden_factory():
        nonlocal summary_factory_calls
        summary_factory_calls += 1
        raise AssertionError("revoke must win before Provider construction")

    with TestClient(
        create_app(
            settings_override=settings,
            chat_provider_factory=RecordingChatProvider,
            summary_provider_factory=forbidden_factory,
        )
    ) as client:
        _grant(client, "/api/summaries/processing-consent")
        with managed_connection(settings.database_url) as connection:
            session = SessionRepository(connection).create("revoke before dispatch")
            user = MessageRepository(connection).add(
                session.id,
                ChatRole.USER,
                "revoke before dispatch marker",
            )
            _, turn = ChatTurnRepository(connection).append_assistant_turn(
                session_id=session.id,
                user_message_id=user.id,
                content="safe reply",
                metadata={},
            )
            reservation = SummaryJobReservationService(
                connection,
                settings=settings,
            ).reserve_for_turn(session.id, turn.id)
            assert reservation is not None
            job = reservation[0]

        _mutate(client, "/api/summaries/processing-consent", "revoke")
        terminal_job = asyncio.run(
            SummaryJobService(
                database_url=settings.database_url,
                settings=settings,
                processing_fence=client.app.state.summary_processing_fence,
                remote_provider_factory=forbidden_factory,
            ).process(job.id)
        )
        assert terminal_job is not None
        terminal = _wait_for_job(client, job_id=job.id)
        assert terminal["status"] == "skipped"
        assert terminal["reason_code"] == "discarded_processing_authority_changed"
        assert summary_factory_calls == 0



def test_inflight_processing_mutations_discard_remote_payload(tmp_path: Path) -> None:
    for mutation in ("revoke", "barrier", "exclusion"):
        settings = _settings(
            tmp_path,
            database_url=f"sqlite:///{tmp_path / f'inflight-{mutation}.db'}",
            memory_source_reference_key_path=tmp_path / f"inflight-{mutation}.key",
        )
        provider = BlockingSummaryProvider()
        with TestClient(
            create_app(
                settings_override=settings,
                chat_provider_factory=RecordingChatProvider,
                summary_provider_factory=lambda: provider,
            )
        ) as client:
            _grant(client, "/api/summaries/processing-consent")
            source = client.post(
                "/api/sessions", json={"title": f"inflight {mutation}"}
            ).json()
            result: dict[str, object] = {}

            def send() -> None:
                result["response"] = client.post(
                    f"/api/sessions/{source['id']}/messages",
                    json={"content": f"inflight {mutation} marker"},
                )

            sender = threading.Thread(target=send, daemon=True)
            sender.start()
            assert provider.started.wait(5)
            with managed_connection(settings.database_url) as connection:
                if mutation == "revoke":
                    repository = SummaryAutomationRepository(connection)
                    current = repository.get_processing_authority()
                    repository.mutate_processing(
                        action="revoke",
                        expected_generation=current.generation,
                        policy=build_summary_processing_policy(settings),
                    )
                elif mutation == "barrier":
                    connection.execute(
                        "UPDATE memory_summary_barrier "
                        "SET generation=generation+1 WHERE singleton_id=1"
                    )
                    connection.commit()
                else:
                    message_id = connection.execute(
                        "SELECT source.message_id FROM summary_job_sources AS source "
                        "JOIN summary_jobs AS job ON job.id=source.job_id "
                        "WHERE job.session_id=? ORDER BY source.source_order LIMIT 1",
                        (source["id"],),
                    ).fetchone()[0]
                    connection.execute(
                        "INSERT INTO memory_summary_source_exclusions "
                        "(source_message_id, reason_code, created_at) "
                        "VALUES (?, 'http_smoke', '2026-07-25T00:00:00+00:00')",
                        (message_id,),
                    )
                    connection.commit()
            provider.release.set()
            sender.join(5)
            assert getattr(result["response"], "status_code") == 200
            job = _wait_for_job(client)
            assert job["status"] == "skipped"
            assert job["reason_code"].startswith("discarded_")
            assert client.get(
                "/api/summaries", params={"session_id": source["id"]}
            ).json()["items"] == []



def test_redaction_removes_summary_before_next_chat_send_and_source_deletion_falls_back(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    seed_chat = RecordingChatProvider()
    with TestClient(
        create_app(
            settings_override=settings,
            chat_provider_factory=lambda: seed_chat,
            summary_provider_factory=RecordingSummaryProvider,
        )
    ) as client:
        _grant(client, "/api/summaries/processing-consent")
        _grant(client, "/api/summaries/injection-consent")
        source = client.post("/api/sessions", json={"title": "source"}).json()
        _send_turn(client, source["id"], "summary continuity marker")
        summary = _wait_for_summary(client, source["id"])
        active = client.post("/api/sessions", json={"title": "active"}).json()

        redacted = client.post(
            f"/api/summaries/{summary['id']}/redact",
            json={
                "expected_suppression_generation": summary[
                    "suppression_generation"
                ],
                "confirmation": "redact_summary_payload",
            },
        )
        assert redacted.status_code == 200
        _send_turn(client, active["id"], "summary continuity marker")
        assert _manifest(client, active["id"])["selected_summary_ids"] == []

        replacement_source = client.post(
            "/api/sessions", json={"title": "other source"}
        ).json()
        _send_turn(client, replacement_source["id"], "another continuity marker")
        replacement_summary = _wait_for_summary(client, replacement_source["id"])
        assert client.delete(
            f"/api/sessions/{replacement_source['id']}"
        ).status_code == 204
        client.app.state.llm_provider = seed_chat
        _send_turn(client, active["id"], "another continuity marker")
        assert replacement_summary["id"] not in _manifest(client, active["id"])[
            "selected_summary_ids"
        ]



def test_deleted_active_chat_session_calls_no_chat_provider(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    provider = RecordingChatProvider()
    with TestClient(
        create_app(
            settings_override=settings,
            chat_provider_factory=lambda: provider,
            summary_provider_factory=RecordingSummaryProvider,
        )
    ) as client:
        active = client.post("/api/sessions", json={"title": "delete active"}).json()
        assert client.delete(f"/api/sessions/{active['id']}").status_code == 204
        response = client.post(
            f"/api/sessions/{active['id']}/messages",
            json={"content": "send after delete"},
        )
        assert response.status_code == 404
        assert provider.calls == []
        with managed_connection(settings.database_url) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id=?",
                (active["id"],),
            ).fetchone()[0] == 0



def test_true_forget_closes_echo_turn_redacts_and_rebuilds_only_safe_turn(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, session_summary_trigger_turn_count=2)
    with TestClient(
        create_app(
            settings_override=settings,
            chat_provider_factory=RecordingChatProvider,
            summary_provider_factory=RecordingSummaryProvider,
        )
    ) as client:
        _grant(client, "/api/summaries/processing-consent")
        source = client.post("/api/sessions", json={"title": "forget source"}).json()
        first = _send_turn(client, source["id"], "SECRET_ECHO_SENTINEL")
        _send_turn(client, source["id"], "SAFE_REMAINING_TURN")
        summary = _wait_for_summary(client, source["id"])
        memory = client.post(
            "/api/memories",
            json={
                "content": "private derived memory",
                "memory_type": "preference",
                "source_session_id": source["id"],
                "importance": 3,
                "confidence": 0.9,
            },
        ).json()["memory"]
        with managed_connection(settings.database_url) as connection:
            version_id = connection.execute(
                "SELECT id FROM memory_versions WHERE memory_id=? "
                "ORDER BY version_number DESC LIMIT 1",
                (memory["id"],),
            ).fetchone()[0]
            user_id = connection.execute(
                "SELECT user_message_id FROM chat_turns "
                "WHERE assistant_message_id=?",
                (first["assistant_message_id"],),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO memory_evidence ("
                "evidence_id, memory_id, memory_version_id, source_session_id, "
                "source_message_id, source_session_reference_hash, "
                "source_message_reference_hash, source_available, relation, "
                "observed_at, extractor_kind, confidence, created_at"
                ") VALUES ("
                "'gate-c2-forget-evidence', ?, ?, ?, ?, 'session-hash', "
                "'message-hash', 1, 'supports', '2026-07-25T00:00:00+00:00', "
                "'manual', 0.9, '2026-07-25T00:00:00+00:00'"
                ")",
                (memory["id"], version_id, source["id"], user_id),
            )
            connection.commit()

        forgotten = client.post(f"/api/memories/{memory['id']}/forget")
        assert forgotten.status_code == 200
        with managed_connection(settings.database_url) as connection:
            row = connection.execute(
                "SELECT summary_text, payload_state FROM session_summaries WHERE id=?",
                (summary["id"],),
            ).fetchone()
            assert tuple(row) == (None, "redacted")
            excluded = {
                row[0]
                for row in connection.execute(
                    "SELECT source_message_id FROM memory_summary_source_exclusions"
                )
            }
            assert user_id in excluded
            assert first["assistant_message_id"] in excluded

        public = client.get(f"/api/summaries/{summary['id']}").json()
        rebuilt = client.post(
            f"/api/summaries/{summary['id']}/rebuild",
            json={
                "expected_suppression_generation": public["suppression_generation"]
            },
        )
        assert rebuilt.status_code == 200
        job = _wait_for_job(client, job_id=rebuilt.json()["job_id"])
        assert job["status"] == "succeeded"
        with managed_connection(settings.database_url) as connection:
            contents = [
                row[0]
                for row in connection.execute(
                    "SELECT message.content FROM summary_job_sources AS source "
                    "JOIN messages AS message ON message.id=source.message_id "
                    "WHERE source.job_id=? ORDER BY source.source_order",
                    (job["id"],),
                )
            ]
        assert contents == ["SAFE_REMAINING_TURN", "Gate C2 safe reply"]
        assert all("SECRET_ECHO_SENTINEL" not in content for content in contents)



def test_restart_recovery_deduplicates_compatible_and_terminalizes_incompatible(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    with TestClient(
        create_app(
            settings_override=settings,
            chat_provider_factory=RecordingChatProvider,
            summary_provider_factory=RecordingSummaryProvider,
        )
    ) as client:
        _grant(client, "/api/summaries/processing-consent")

    with managed_connection(settings.database_url) as connection:
        session = SessionRepository(connection).create("recovery")
        user = MessageRepository(connection).add(
            session.id, ChatRole.USER, "recovery source"
        )
        _, turn = ChatTurnRepository(connection).append_assistant_turn(
            session_id=session.id,
            user_message_id=user.id,
            content="recovery reply",
            metadata={},
        )
        reservation = SummaryJobReservationService(
            connection, settings=settings
        ).reserve_for_turn(session.id, turn.id)
        assert reservation is not None
        compatible = reservation[0]
        duplicate = SummaryJobReservationService(
            connection, settings=settings
        ).reserve_for_turn(session.id, turn.id)
        assert duplicate is not None
        assert duplicate[0].id == compatible.id
        incompatible_session = SessionRepository(connection).create(
            "incompatible recovery"
        )
        incompatible_user = MessageRepository(connection).add(
            incompatible_session.id,
            ChatRole.USER,
            "incompatible source",
        )
        _, incompatible_turn = ChatTurnRepository(connection).append_assistant_turn(
            session_id=incompatible_session.id,
            user_message_id=incompatible_user.id,
            content="incompatible reply",
            metadata={},
        )
        snapshot = ChatTurnRepository(connection).snapshot_generation_sources(
            session_id=incompatible_session.id,
            after_turn_order=0,
            max_turns=1,
            max_messages=2,
            max_characters=10_000,
        )
        incompatible_job, _ = SummaryAutomationRepository(connection).reserve_job(
            snapshot=snapshot,
            job_kind=compatible.job_kind,
            route="remote",
            provider="deepseek",
            model="summary-model",
            summarizer_schema_version="unsupported",
            processing_consent_generation=compatible.captured_processing_consent_generation,
            processing_policy_fingerprint=compatible.captured_processing_policy_fingerprint,
            provider_policy_fingerprint="unsupported-provider-policy",
            session_deletion_generation=0,
            suppression_generation=0,
            rebuild_authorization_generation=0,
            rebuild_permit_id=None,
        )
        assert incompatible_turn.id
        repository = SummaryAutomationRepository(connection)
        recoverable, incompatible = repository.prepare_recovery_jobs(
            stale_before=replace_time_for_recovery(),
            job_schema_version=SUMMARY_JOB_SCHEMA_VERSION,
            summarizer_schema_version=SUMMARY_SCHEMA_VERSION,
            max_attempts=settings.summary_job_max_attempts,
        )
        assert [job.id for job in recoverable] == [compatible.id]
        assert incompatible == [incompatible_job.id]
        repository.fail_incompatible_job(incompatible_job.id)
        assert (
            repository.require_job(incompatible_job.id).reason_code
            == "incompatible_recovery"
        )



def replace_time_for_recovery():
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) + timedelta(seconds=1)



def test_fake_route_reports_local_semantics_and_never_constructs_remote(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path,
        session_summary_provider="fake",
        llm_provider="fake",
        llm_model="fake-model",
    )
    remote_factory_calls = 0

    def forbidden_factory():
        nonlocal remote_factory_calls
        remote_factory_calls += 1
        raise AssertionError("fake route must not construct remote Provider")

    with TestClient(
        create_app(
            settings_override=settings,
            summary_provider_factory=forbidden_factory,
        )
    ) as client:
        capabilities = client.get("/api/summaries/capabilities").json()
        assert capabilities == {
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
        processing = client.get("/api/summaries/processing-consent").json()
        assert client.put(
            "/api/summaries/processing-consent",
            json={
                "action": "enable_local",
                "expected_generation": processing["generation"],
            },
        ).status_code == 200
        source = client.post("/api/sessions", json={"title": "local fake"}).json()
        _send_turn(client, source["id"], "local fake marker")
        assert _wait_for_job(client)["status"] == "succeeded"
    assert remote_factory_calls == 0
