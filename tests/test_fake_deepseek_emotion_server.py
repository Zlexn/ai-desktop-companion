import json

from fastapi.testclient import TestClient

from scripts.fake_deepseek_emotion_server import TEST_TOKEN, app


def _request_payload(user_content: str | None = None) -> dict[str, object]:
    analysis_input = {
        "current_turn": {
            "user_message_id": "user-1",
            "user_content": "我今天很难受 [REDACTED]",
            "assistant_message_id": "assistant-1",
            "assistant_content": "我会陪你慢慢说。",
        },
        "recent_messages": [],
        "memories": [],
        "input_characters": 24,
        "redaction_count": 1,
    }
    return {
        "model": "stage4c-e2e-model",
        "messages": [
            {"role": "system", "content": "analysis system"},
            {
                "role": "user",
                "content": user_content or json.dumps(analysis_input, ensure_ascii=False),
            },
        ],
        "max_tokens": 384,
        "stream": False,
        "thinking": {"type": "disabled"},
    }


def test_chat_completion_records_sanitized_request_and_returns_valid_proposal() -> None:
    with TestClient(app) as client:
        client.post("/__test__/reset")
        response = client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
            json=_request_payload(),
        )

        assert response.status_code == 200
        content = json.loads(response.json()["choices"][0]["message"]["content"])
        assert content["source_ids"] == ["user-1", "assistant-1"]
        assert content["schema_version"] == "emotion_analysis_v1"
        state = client.get("/__test__/state").json()
        assert state["request_count"] == 1
        assert TEST_TOKEN not in json.dumps(state)
        assert state["requests"][0]["messages"][1]["role"] == "user"


def test_chat_completion_rejects_invalid_token() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/chat/completions",
            headers={"Authorization": "Bearer wrong"},
            json=_request_payload(),
        )

    assert response.status_code == 401


def test_chat_completion_rejects_malformed_analysis_payload() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
            json=_request_payload("not-json"),
        )

    assert response.status_code == 422


def test_reset_clears_recorded_requests() -> None:
    with TestClient(app) as client:
        client.post("/__test__/reset")
        client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
            json=_request_payload(),
        )
        assert client.get("/__test__/state").json()["request_count"] == 1

        response = client.post("/__test__/reset")

        assert response.status_code == 200
        assert client.get("/__test__/state").json() == {
            "request_count": 0,
            "requests": [],
        }
