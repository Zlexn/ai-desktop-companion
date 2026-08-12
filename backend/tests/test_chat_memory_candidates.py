import threading

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_settings
from app.core.config import Settings
from app.domain.models import (
    MemoryAutomationMode,
    MemoryExtractorRoute,
    MemoryJobStatus,
    MemorySource,
    MemoryStatus,
    MemoryType,
)
from app.main import create_app
from app.repositories.memories import MemoryRepository
from app.repositories.memory_automation import MemoryAutomationRepository
from app.repositories.sqlite import managed_connection
from app.services.memory_gate_b_contract import (
    MEMORY_ALLOWED_AUTO_TYPES,
    MEMORY_ALLOWED_AUTO_TYPES_VERSION,
    MEMORY_WRITE_POLICY_VERSION,
    MEMORY_WRITE_PURPOSE,
    MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
)
from app.domain.models import MemoryWriteConsentStatus


def test_chat_creates_pending_memory_candidate(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "候选记忆"}).json()

    response = client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "我喜欢红茶。"},
    )

    assert response.status_code == 200
    candidates_response = client.get("/api/memories", params={"status_filter": "pending"})
    assert candidates_response.status_code == 200
    candidates = candidates_response.json()
    assert len(candidates) == 1
    assert candidates[0]["content"] == "用户喜欢红茶。"
    assert candidates[0]["memory_type"] == "preference"
    assert candidates[0]["source"] == "candidate"
    assert candidates[0]["status"] == "pending"
    assert candidates[0]["source_session_id"] == session["id"]



@pytest.mark.parametrize(
    ("mode", "route", "candidates_enabled", "expected_jobs", "expected_new_pending"),
    [
        ("off", "none", True, 0, 0),
        ("candidate_confirmation", "none", True, 0, 1),
        ("candidate_confirmation", "none", False, 0, 0),
        ("shadow_auto", "fake", True, 1, 0),
        ("auto_active", "local", True, 1, 0),
    ],
)
def test_http_memory_mode_matrix_preserves_existing_memory_rows(
    monkeypatch,
    tmp_path,
    mode,
    route,
    candidates_enabled,
    expected_jobs,
    expected_new_pending,
) -> None:
    database_url = f"sqlite:///{tmp_path / f'{mode}-{route}-{candidates_enabled}.db'}"
    settings = Settings(
        database_url=database_url,
        llm_provider="fake",
        llm_model="test-model",
        memory_automation_mode=mode,
        memory_extractor_route=route,
        memory_extractor_model="memory-test-model",
        memory_candidates_enabled=candidates_enabled,
    )
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        active, _ = memories.create(
            content="seed active", memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL, source_session_id=None,
            importance=3, confidence=1.0,
        )
        pending, _ = memories.create_candidate(
            content="seed pending", memory_type=MemoryType.PREFERENCE,
            source_session_id=None, importance=2, confidence=0.9,
        )
        dismissed, _ = memories.create_candidate(
            content="seed dismissed", memory_type=MemoryType.LONG_TERM_GOAL,
            source_session_id=None, importance=2, confidence=0.9,
        )
        assert pending is not None and dismissed is not None
        memories.dismiss_candidate(dismissed.id)
        archived, _ = memories.create(
            content="seed archived", memory_type=MemoryType.OTHER,
            source=MemorySource.MANUAL, source_session_id=None,
            importance=1, confidence=1.0,
        )
        memories.archive(archived.id)
        if mode == "auto_active":
            MemoryAutomationRepository(connection).set_write_consent(
                status=MemoryWriteConsentStatus.GRANTED,
                purpose=MEMORY_WRITE_PURPOSE,
                policy_version=MEMORY_WRITE_POLICY_VERSION,
                allowed_memory_types_version=MEMORY_ALLOWED_AUTO_TYPES_VERSION,
                allowed_memory_types=MEMORY_ALLOWED_AUTO_TYPES,
                retention_disclosure_version=(
                    MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION
                ),
            )
        before = [tuple(row) for row in connection.execute(
            "SELECT id, content, status, metadata_json FROM memories ORDER BY id"
        ).fetchall()]

    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        session = test_client.post("/api/sessions", json={"title": "matrix"}).json()
        response = test_client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "我喜欢红茶。"},
        )
        assert response.status_code == 200
        if expected_jobs:
            for _ in range(100):
                with managed_connection(database_url) as connection:
                    jobs = MemoryAutomationRepository(connection).list_jobs(limit=10)
                if len(jobs) == expected_jobs and all(
                    job.status in {MemoryJobStatus.SUCCEEDED, MemoryJobStatus.FAILED, MemoryJobStatus.CANCELLED}
                    for job in jobs
                ):
                    break
                threading.Event().wait(0.01)
            else:
                raise AssertionError("shadow job did not finish")

    with managed_connection(database_url) as connection:
        after = [tuple(row) for row in connection.execute(
            "SELECT id, content, status, metadata_json FROM memories ORDER BY id"
        ).fetchall()]
        jobs = MemoryAutomationRepository(connection).list_jobs(limit=10)
    assert {row[0]: row[1:] for row in after if row[0] in {item[0] for item in before}} == {
        row[0]: row[1:] for row in before
    }
    assert len(after) == (
        len(before)
        + expected_new_pending
        + (1 if mode == "auto_active" else 0)
    )
    assert len(jobs) == expected_jobs


def test_chat_skips_memory_candidates_when_disabled(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMORY_CANDIDATES_ENABLED", "false")
    get_settings.cache_clear()
    disabled_client = TestClient(client.app)
    session = disabled_client.post("/api/sessions", json={"title": "候选关闭"}).json()

    response = disabled_client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "我喜欢红茶。"},
    )

    assert response.status_code == 200
    assert disabled_client.get("/api/memories", params={"status_filter": "pending"}).json() == []
    get_settings.cache_clear()
