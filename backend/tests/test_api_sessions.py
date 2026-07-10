from fastapi.testclient import TestClient


def test_create_list_get_and_delete_session_api(client: TestClient) -> None:
    create_response = client.post("/api/sessions", json={"title": "API 会话"})
    assert create_response.status_code == 201
    session = create_response.json()
    assert session["title"] == "API 会话"

    list_response = client.get("/api/sessions")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [session["id"]]

    get_response = client.get(f"/api/sessions/{session['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == session["id"]

    delete_response = client.delete(f"/api/sessions/{session['id']}")
    assert delete_response.status_code == 204

    missing_response = client.get(f"/api/sessions/{session['id']}")
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "not_found"


def test_missing_session_delete_returns_404(client: TestClient) -> None:
    response = client.delete("/api/sessions/missing")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "会话不存在。"
