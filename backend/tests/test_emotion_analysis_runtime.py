import json
import sqlite3
import time
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.domain.models import ChatRole
from app.main import create_app
from app.providers.base import LLMResponse


class RecordingEmotionAnalysisProvider:
    provider_name = "recording-analysis"

    def __init__(self) -> None:
        self.called = Event()
        self.calls = []

    async def generate(self, messages, options):
        self.calls.append((messages, options))
        self.called.set()
        current_turn = json.loads(messages[1].content)["current_turn"]
        return LLMResponse(
            text=json.dumps(
                {
                    "schema_version": "emotion_analysis_v1",
                    "should_apply": True,
                    "signals": ["distress"],
                    "proposed_delta": {
                        "mood": -0.02,
                        "trust": 0.0,
                        "concern": 0.04,
                        "distance": 0.0,
                        "irritation": 0.0,
                        "formality": 0.0,
                    },
                    "source_ids": [
                        current_turn["user_message_id"],
                        current_turn["assistant_message_id"],
                    ],
                    "reason_codes": ["user_distress"],
                }
            ),
            provider=self.provider_name,
            model=options.model,
        )


def test_fake_runtime_applies_consented_analysis_and_persists_metadata_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "runtime.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("EMOTION_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv("EMOTION_ANALYSIS_PROVIDER", "deepseek")
    monkeypatch.setenv("EMOTION_ANALYSIS_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "runtime-test-key")
    get_settings.cache_clear()
    provider = RecordingEmotionAnalysisProvider()
    app = create_app(emotion_analysis_provider_factory=lambda: provider)

    with TestClient(app) as client:
        consent = client.put(
            "/api/emotion/analysis/consent",
            json={
                "action": "grant",
                "disclosure_version": "emotion-analysis-disclosure-v1",
            },
        )
        assert consent.status_code == 200
        session = client.post("/api/sessions", json={"title": "runtime"}).json()
        chat = client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "我今天很难受 token=runtime-super-secret"},
        )
        assert chat.status_code == 200
        assert provider.called.wait(timeout=2.0)

        deadline = time.monotonic() + 2.0
        audits = []
        while time.monotonic() < deadline:
            audits = client.get("/api/emotion/analysis/audits").json()
            if audits:
                break
            time.sleep(0.01)

        assert len(provider.calls) == 1
        messages, _options = provider.calls[0]
        assert [message.role for message in messages] == [ChatRole.SYSTEM, ChatRole.USER]
        assert "runtime-super-secret" not in messages[1].content
        assert audits[0]["outcome"] == "applied"
        assert audits[0]["redaction_count"] >= 1
        events = client.get("/api/emotion/events").json()
        assert any(event["engine"] == "llm_assisted" for event in events)

        before_revoke = client.get("/api/emotion/state").json()
        revoke = client.put(
            "/api/emotion/analysis/consent",
            json={
                "action": "revoke",
                "disclosure_version": "emotion-analysis-disclosure-v1",
            },
        )
        assert revoke.status_code == 200
        second_chat = client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "我需要帮助 token=runtime-post-revoke-secret"},
        )
        assert second_chat.status_code == 200
        assert len(provider.calls) == 1
        after_revoke = client.get("/api/emotion/state").json()
        assert (
            after_revoke["vector"]["concern"]
            > before_revoke["vector"]["concern"]
        )
        assert len(client.get("/api/emotion/analysis/audits").json()) == 1

    connection = sqlite3.connect(database_path)
    try:
        for table in ("emotion_analysis_jobs", "emotion_analysis_audits"):
            rows = connection.execute(f"SELECT * FROM {table}").fetchall()
            assert "runtime-super-secret" not in repr(rows)
            assert "runtime-post-revoke-secret" not in repr(rows)
            assert "runtime-test-key" not in repr(rows)
            assert "我今天很难受" not in repr(rows)
            assert "我需要帮助" not in repr(rows)
    finally:
        connection.close()
        get_settings.cache_clear()
