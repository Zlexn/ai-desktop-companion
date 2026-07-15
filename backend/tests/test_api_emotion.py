from fastapi.testclient import TestClient


def test_emotion_analysis_consent_lifecycle_and_metadata_only_audit(client: TestClient) -> None:
    initial = client.get("/api/emotion/analysis/consent")
    assert initial.status_code == 200
    assert initial.json()["status"] == "unknown"
    assert initial.json()["deployment_enabled"] is False
    assert initial.json()["provider"] is None
    assert initial.json()["deployment_provider"] == "deepseek"

    granted = client.put(
        "/api/emotion/analysis/consent",
        json={"action": "grant", "disclosure_version": "emotion-analysis-disclosure-v1"},
    )
    assert granted.status_code == 200
    assert granted.json()["status"] == "granted"

    revoked = client.put(
        "/api/emotion/analysis/consent",
        json={"action": "revoke", "disclosure_version": "emotion-analysis-disclosure-v1"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    audit = client.get("/api/emotion/analysis/audits")
    assert audit.status_code == 200
    assert audit.json() == []


def test_emotion_analysis_consent_rejects_unknown_actions_extra_fields_and_bad_limits(client: TestClient) -> None:
    assert client.put(
        "/api/emotion/analysis/consent",
        json={"action": "enable", "disclosure_version": "emotion-analysis-disclosure-v1"},
    ).status_code == 422
    assert client.put(
        "/api/emotion/analysis/consent",
        json={
            "action": "grant",
            "disclosure_version": "emotion-analysis-disclosure-v1",
            "enabled": True,
        },
    ).status_code == 422
    assert client.get("/api/emotion/analysis/audits", params={"limit": 0}).status_code == 422
    assert client.get("/api/emotion/analysis/audits", params={"limit": 101}).status_code == 422


    initial = client.get("/api/emotion/state")
    assert initial.status_code == 200
    body = initial.json()
    assert body["scope_id"] == "default-companion"
    assert body["enabled"] is True
    assert body["version"] == 0
    assert body["vector"] == {
        "mood": 0.5,
        "trust": 0.4,
        "concern": 0.2,
        "distance": 0.55,
        "irritation": 0.1,
        "formality": 0.6,
    }

    disabled = client.patch("/api/emotion/settings", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    reset = client.post("/api/emotion/reset")
    assert reset.status_code == 200
    assert reset.json()["vector"] == body["vector"]

    events = client.get("/api/emotion/events", params={"limit": 20})
    assert events.status_code == 200
    assert [event["event_type"] for event in events.json()] == ["reset", "settings"]


def test_emotion_api_rejects_arbitrary_state_edits_and_bad_limits(client: TestClient) -> None:
    assert client.patch("/api/emotion/settings", json={"enabled": True, "trust": 1}).status_code == 422
    assert client.get("/api/emotion/events", params={"limit": 0}).status_code == 422
    assert client.get("/api/emotion/events", params={"limit": 101}).status_code == 422
