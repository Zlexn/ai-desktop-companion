import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def test_send_message_api_returns_reply_and_stores_messages(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "聊天"}).json()

    response = client.post(f"/api/sessions/{session['id']}/messages", json={"content": "你好"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"].startswith("我听见了：你好")
    assert body["metadata"] == {"provider": "fake", "model": "test-model"}

    messages = client.get(f"/api/sessions/{session['id']}/messages").json()
    assert [message["role"] for message in messages] == ["user", "assistant"]


@pytest.mark.parametrize(
    ("mode", "status_code", "error_code", "message"),
    [
        ("error", 502, "provider_error", "模型服务暂时不可用，请稍后重试。"),
        ("timeout", 504, "provider_timeout", "模型服务响应超时，请稍后重试。"),
        ("rate_limit", 429, "provider_rate_limited", "模型服务请求过于频繁，请稍后重试。"),
        ("invalid", 502, "provider_invalid_response", "模型服务返回了无法处理的响应。"),
        ("empty", 502, "provider_invalid_response", "模型服务返回了无法处理的响应。"),
    ],
)
def test_send_message_api_maps_fake_provider_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    status_code: int,
    error_code: str,
    message: str,
) -> None:
    monkeypatch.setenv("FAKE_PROVIDER_MODE", mode)
    get_settings.cache_clear()
    with TestClient(create_app()) as error_client:
        session = error_client.post("/api/sessions", json={"title": "错误"}).json()

        response = error_client.post(f"/api/sessions/{session['id']}/messages", json={"content": "触发错误"})

    assert response.status_code == status_code
    body = response.json()
    assert body == {"error": {"code": error_code, "message": message}}
    serialized = response.text.lower()
    assert "traceback" not in serialized
    assert "anthropic_api_key" not in serialized
    assert "c:\\" not in serialized
    assert "/backend/" not in serialized


def test_send_message_to_missing_session_returns_404(client: TestClient) -> None:
    response = client.post("/api/sessions/missing/messages", json={"content": "你好"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_empty_message_returns_validation_error(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "聊天"}).json()

    response = client.post(f"/api/sessions/{session['id']}/messages", json={"content": ""})

    assert response.status_code == 422
