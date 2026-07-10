from fastapi.testclient import TestClient


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


def test_chat_skips_memory_candidates_when_disabled(client: TestClient, monkeypatch) -> None:
    from app.core.config import get_settings

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
