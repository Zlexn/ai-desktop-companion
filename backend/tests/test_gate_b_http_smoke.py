from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.domain.models import MemoryJobStatus
from app.main import create_app
from app.providers.base import LLMResponse
from app.repositories.memory_automation import MemoryAutomationRepository
from app.repositories.sqlite import managed_connection
from app.services.memory_gate_b_contract import (
    MEMORY_ALLOWED_AUTO_TYPES,
    MEMORY_ALLOWED_AUTO_TYPES_VERSION,
    MEMORY_WRITE_POLICY_VERSION,
    MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
)


_WRITE_CONSENT = {
    "action": "grant",
    "policy_version": MEMORY_WRITE_POLICY_VERSION,
    "retention_disclosure_version": MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
    "allowed_memory_types_version": MEMORY_ALLOWED_AUTO_TYPES_VERSION,
    "allowed_memory_types": [item.value for item in MEMORY_ALLOWED_AUTO_TYPES],
}
_TERMINAL_JOB_STATUSES = {
    MemoryJobStatus.SUCCEEDED.value,
    MemoryJobStatus.FAILED.value,
    MemoryJobStatus.CANCELLED.value,
}


class RecordingMemoryProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, messages, options):
        self.calls += 1
        return LLMResponse(
            text=json.dumps({"schema_version": "memory-shadow-schema-v1", "proposals": []}),
            provider="recording-memory",
            model=options.model,
        )

    async def aclose(self) -> None:
        pass


def _settings(
    tmp_path: Path,
    *,
    mode: str = "auto_active",
    route: str = "local",
    emotion_enabled: bool = False,
) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / f'{mode}-{route}.db'}",
        memory_source_reference_key_path=tmp_path / f"{mode}-{route}.key",
        llm_provider="fake",
        llm_model="test-model",
        memory_automation_mode=mode,
        memory_extractor_route=route,
        memory_extractor_provider="anthropic",
        memory_extractor_model="memory-test-model",
        anthropic_api_key=(
            "test-only-never-sent" if route == "remote" else None
        ),
        memory_candidates_enabled=False,
        session_summary_enabled=False,
        emotion_analysis_enabled=emotion_enabled,
        emotion_analysis_provider="deepseek",
        emotion_analysis_model="emotion-test-model",
        deepseek_api_key="test-only-emotion-key" if emotion_enabled else None,
    )


def _client(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    *,
    memory_provider: RecordingMemoryProvider | None = None,
    emotion_provider=None,
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app = create_app(
        memory_extractor_provider_factory=(
            (lambda: memory_provider) if memory_provider is not None else None
        ),
        emotion_analysis_provider_factory=(
            (lambda: emotion_provider) if emotion_provider is not None else None
        ),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return app, TestClient(app)


def _send_turn(client: TestClient, content: str) -> tuple[dict, dict]:
    session = client.post("/api/sessions", json={"title": "Gate B smoke"})
    assert session.status_code == 201
    chat = client.post(
        f"/api/sessions/{session.json()['id']}/messages",
        json={"content": content},
    )
    assert chat.status_code == 200
    return session.json(), chat.json()


def _wait_for_jobs(
    client: TestClient,
    count: int,
    *,
    timeout: float = 3.0,
) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get("/api/memories/jobs", params={"limit": count})
        assert response.status_code == 200
        jobs = response.json()
        if len(jobs) >= count and all(
            job["status"] in _TERMINAL_JOB_STATUSES for job in jobs[:count]
        ):
            return jobs[:count]
        time.sleep(0.01)
    raise AssertionError("memory jobs did not reach terminal states")


def _wait_for_job(client: TestClient, *, timeout: float = 3.0) -> dict:
    return _wait_for_jobs(client, 1, timeout=timeout)[0]


def _memory_counts(database_url: str) -> dict[str, int]:
    with managed_connection(database_url) as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "memories",
                "memory_record_states",
                "memory_versions",
                "memory_evidence",
                "memory_write_activities",
            )
        }


def test_no_write_grant_blocks_extractor_and_active_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, route="remote")
    provider = RecordingMemoryProvider()
    app, test_client = _client(monkeypatch, settings, memory_provider=provider)

    with test_client as client:
        remote = client.put(
            "/api/memories/extraction/consent",
            json={"action": "grant", "disclosure_version": "memory-extraction-disclosure-v1"},
        )
        assert remote.status_code == 200
        _send_turn(client, "我喜欢乌龙茶。")
        job = _wait_for_job(client)

    assert provider.calls == 0
    assert job["outcome"] == "skipped_no_write_consent"
    assert _memory_counts(settings.database_url) == {
        "memories": 0,
        "memory_record_states": 0,
        "memory_versions": 0,
        "memory_evidence": 0,
        "memory_write_activities": 0,
    }
    assert app.state.memory_source_reference_service is not None


def test_remote_write_grant_without_remote_consent_sends_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, route="remote")
    provider = RecordingMemoryProvider()
    _app, test_client = _client(monkeypatch, settings, memory_provider=provider)

    with test_client as client:
        assert client.put(
            "/api/memories/automation/write-consent", json=_WRITE_CONSENT
        ).status_code == 200
        _send_turn(client, "我喜欢乌龙茶。")
        job = _wait_for_job(client)

    assert provider.calls == 0
    assert job["outcome"] == "skipped_no_consent"
    assert _memory_counts(settings.database_url)["memories"] == 0


def test_local_exact_write_grant_commits_version_evidence_and_activity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    _app, test_client = _client(monkeypatch, settings)

    with test_client as client:
        assert client.put(
            "/api/memories/automation/write-consent", json=_WRITE_CONSENT
        ).status_code == 200
        session, chat = _send_turn(client, "我喜欢乌龙茶。")
        job = _wait_for_job(client)
        memories = client.get("/api/memories").json()
        audits = client.get("/api/memories/jobs/audits", params={"limit": 1}).json()
        versions = client.get(f"/api/memories/{memories[0]['id']}/versions").json()
        evidence = client.get(f"/api/memories/{memories[0]['id']}/evidence").json()

    assert session["id"] and chat["assistant_message_id"] and job["id"]
    assert job["outcome"] == "completed_with_decisions"
    assert audits[0]["outcome_counts"] == {"committed_create": 1}
    assert memories[0]["v2_source_kind"] == "automatic"
    assert memories[0]["version_count"] == 1
    assert memories[0]["evidence_count"] == 1
    assert versions["items"][0]["operation"] == "create"
    assert evidence["items"][0]["relation"] == "supports"
    assert _memory_counts(settings.database_url) == {
        "memories": 1,
        "memory_record_states": 1,
        "memory_versions": 1,
        "memory_evidence": 1,
        "memory_write_activities": 1,
    }


def test_fake_http_create_support_supersede_and_conflict_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DecisionMemoryProvider(RecordingMemoryProvider):
        async def generate(self, messages, options):
            self.calls += 1
            disclosed = json.loads(messages[1].content)
            user = disclosed["user_message"]
            text = user["content"].strip().rstrip("。")
            content = (
                "用户住在海边城市"
                if "海边城市" in text
                else "用户住在山城"
            )
            proposal = {
                "memory_type": "user_fact",
                "subject": "居住地",
                "content": content,
                "canonical_key_hint": None,
                "confidence": 0.9,
                "source_message_ids": [user["id"]],
            }
            return LLMResponse(
                text=json.dumps({
                    "schema_version": "memory-shadow-schema-v1",
                    "proposals": [proposal],
                }, ensure_ascii=False),
                provider="recording-memory",
                model=options.model,
            )

    settings = _settings(tmp_path, route="fake")
    provider = DecisionMemoryProvider()
    monkeypatch.setattr(
        "app.main.MemoryExtractionFakeProvider",
        lambda _settings: provider,
    )
    _app, test_client = _client(monkeypatch, settings)

    with test_client as client:
        assert client.put(
            "/api/memories/automation/write-consent", json=_WRITE_CONSENT
        ).status_code == 200
        session = client.post("/api/sessions", json={"title": "decisions"}).json()
        turns = (
            "我现在住在山城。",
            "我现在住在山城。",
            "更正一下，我现在住在海边城市。",
            "我住在山城。",
        )
        for index, content in enumerate(turns, start=1):
            response = client.post(
                f"/api/sessions/{session['id']}/messages",
                json={"content": content},
            )
            assert response.status_code == 200
            _wait_for_jobs(client, index)

        audits = client.get("/api/memories/jobs/audits", params={"limit": 10}).json()
        conflicts = client.get("/api/memories/conflicts").json()["items"]
        memories = client.get("/api/memories").json()

    outcomes: dict[str, int] = {}
    for audit in audits:
        for key, count in audit["outcome_counts"].items():
            outcomes[key] = outcomes.get(key, 0) + count
    assert outcomes == {
        "committed_create": 1,
        "committed_support": 1,
        "committed_supersede": 1,
        "conflict_recorded": 1,
    }
    assert len(conflicts) == 1
    assert all(item["has_open_conflict"] for item in memories)
    with managed_connection(settings.database_url) as connection:
        relations = {
            row["relation"]
            for row in connection.execute("SELECT relation FROM memory_evidence")
        }
        assert relations == {"supports", "corrects", "contradicts"}
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_write_activities"
        ).fetchone()[0] == 4


def test_true_forget_is_unreadable_and_same_fact_does_not_revive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinel = "FORGOTTEN_HTTP_SENTINEL"
    settings = _settings(tmp_path)
    _app, test_client = _client(monkeypatch, settings)

    with test_client as client:
        assert client.put(
            "/api/memories/automation/write-consent", json=_WRITE_CONSENT
        ).status_code == 200
        session = client.post("/api/sessions", json={"title": "forget"}).json()
        first = client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": f"我喜欢{sentinel}。"},
        )
        assert first.status_code == 200
        _wait_for_job(client)
        memory = client.get("/api/memories").json()[0]
        forgotten = client.post(f"/api/memories/{memory['id']}/forget")
        assert forgotten.status_code == 200
        history = client.get(f"/api/memories/{memory['id']}/versions").json()
        evidence = client.get(f"/api/memories/{memory['id']}/evidence").json()
        assert sentinel not in json.dumps(history, ensure_ascii=False)
        assert sentinel not in json.dumps(evidence, ensure_ascii=False)
        second = client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": f"我喜欢{sentinel}。"},
        )
        assert second.status_code == 200
        _wait_for_jobs(client, 2)
        assert client.get("/api/memories").json() == []

    with managed_connection(settings.database_url) as connection:
        readable = "\n".join(
            str(value)
            for table in (
                "memories",
                "memory_versions",
                "memory_evidence",
                "memory_write_activities",
                "memory_audit_events",
                "memory_job_audits",
            )
            for row in connection.execute(f"SELECT * FROM {table}").fetchall()
            for value in row
        )
        assert sentinel not in readable
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_tombstones WHERE source_memory_id = ?",
            (memory["id"],),
        ).fetchone()[0] >= 1
        latest = connection.execute(
            "SELECT outcome FROM memory_write_activities "
            "ORDER BY created_at DESC, op_id DESC LIMIT 1"
        ).fetchone()
        assert latest["outcome"] == "skipped_tombstone"
    assert sentinel not in caplog.text


def test_open_conflict_is_absent_from_chat_and_emotion_provider_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingEmotionProvider:
        def __init__(self) -> None:
            self.inputs: list[str] = []

        async def generate(self, messages, options):
            self.inputs.append(messages[1].content)
            disclosed = json.loads(messages[1].content)
            current = disclosed["current_turn"]
            return LLMResponse(
                text=json.dumps({
                    "schema_version": "emotion_analysis_v1",
                    "should_apply": False,
                    "signals": [],
                    "proposed_delta": {
                        "mood": 0, "trust": 0, "concern": 0,
                        "distance": 0, "irritation": 0, "formality": 0,
                    },
                    "source_ids": [
                        current["user_message_id"],
                        current["assistant_message_id"],
                    ],
                    "reason_codes": ["no_change"],
                }),
                provider="recording-emotion",
                model=options.model,
            )

        async def aclose(self) -> None:
            pass

    settings = _settings(tmp_path, mode="off", route="none", emotion_enabled=True)
    emotion_provider = RecordingEmotionProvider()
    app, test_client = _client(monkeypatch, settings, emotion_provider=emotion_provider)

    with test_client as client:
        first = client.post("/api/memories", json={
            "content": "CONFLICT_LEFT_SENTINEL", "memory_type": "preference",
            "importance": 3, "confidence": 1,
        }).json()["memory"]
        second = client.post("/api/memories", json={
            "content": "CONFLICT_RIGHT_SENTINEL", "memory_type": "preference",
            "importance": 3, "confidence": 1,
        }).json()["memory"]
        with managed_connection(settings.database_url) as connection:
            left, right = sorted((first["id"], second["id"]))
            connection.execute(
                "INSERT INTO memory_conflicts "
                "(conflict_id, left_memory_id, right_memory_id, status, created_at) "
                "VALUES ('smoke-conflict', ?, ?, 'open', ?)",
                (left, right, "2026-07-21T00:00:00+00:00"),
            )
            connection.commit()
        assert client.put(
            "/api/emotion/analysis/consent",
            json={"action": "grant", "disclosure_version": "emotion-analysis-disclosure-v1"},
        ).status_code == 200
        _send_turn(client, "请谈谈我的偏好。")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not emotion_provider.inputs:
            time.sleep(0.01)

    chat_text = "\n".join(
        message.content
        for call in app.state.llm_provider.calls
        for message in call
    )
    assert "CONFLICT_LEFT_SENTINEL" not in chat_text
    assert "CONFLICT_RIGHT_SENTINEL" not in chat_text
    assert emotion_provider.inputs
    assert "CONFLICT_LEFT_SENTINEL" not in emotion_provider.inputs[0]
    assert "CONFLICT_RIGHT_SENTINEL" not in emotion_provider.inputs[0]


def test_shadow_auto_http_remains_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, mode="shadow_auto", route="local")
    _app, test_client = _client(monkeypatch, settings)

    with test_client as client:
        _send_turn(client, "我喜欢乌龙茶。")
        job = _wait_for_job(client)

    counts = _memory_counts(settings.database_url)
    assert job["outcome"] == "shadow_recorded"
    assert counts["memories"] == 0
    assert counts["memory_versions"] == 0
    assert counts["memory_evidence"] == 0
    assert counts["memory_write_activities"] == 0
