"""Gate C3 HTTP smoke across the safe relationship API surface.

Drive the full relationship router through a real FastAPI app with a seeded
relationship memory: capabilities, projection, events, jobs, audits, reconcile,
rebuild, suppress, redact, re-enable, and chat survival under relationship
neutrality.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'gate-c3-http-smoke.db'}",
        memory_source_reference_key_path=tmp_path / "source-reference.key",
    )


def _create_memory(client: TestClient, *, content: str, subject_code: str) -> dict:
    memory_type = (
        "preference"
        if subject_code == "preferred_address"
        else "relationship_event"
    )
    response = client.post(
        "/api/memories",
        json={
            "content": content,
            "memory_type": memory_type,
            "importance": 3,
            "confidence": 0.9,
            "canonical_subject_code": subject_code,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["memory"]


def test_relationship_http_smoke_full_surface(tmp_path: Path) -> None:
    with TestClient(create_app(settings_override=_settings(tmp_path))) as client:
        capabilities = client.get("/api/relationship/capabilities")
        assert capabilities.status_code == 200
        assert capabilities.json()["local_only"] is True
        assert capabilities.json()["remote_extraction"] is False

        projection = client.get("/api/relationship/projection")
        assert projection.status_code == 200
        assert projection.json()["available"] is False

        _create_memory(
            client,
            content="小雪",
            subject_code="preferred_address",
        )

        reconcile = client.post("/api/relationship/reconcile", json={})
        assert reconcile.status_code == 200, reconcile.text

        projection = client.get("/api/relationship/projection").json()
        assert projection["available"] is True
        assert projection["preferred_address"] == "小雪"

        events = client.get("/api/relationship/events").json()["items"]
        apply_event = next(
            event for event in events if event["event_kind"] == "apply"
        )
        assert apply_event["address"] == "小雪"
        authority = apply_event["authority"]

        jobs = client.get("/api/relationship/jobs").json()["items"]
        assert jobs

        audits = client.get("/api/relationship/audits").json()["items"]
        assert audits

        # Rebuild is idempotent.
        rebuild = client.post("/api/relationship/rebuild", json={})
        assert rebuild.status_code == 200
        assert client.get("/api/relationship/projection").json()["available"] is True

        # Suppress: relationship-only revoke; source memory unchanged.
        suppress = client.post(
            f"/api/relationship/events/{apply_event['id']}/suppress",
            json={
                "expected_decision_id": authority["decision_id"],
                "expected_decision_generation": authority["generation"],
                "expected_authority_epoch": authority["authority_epoch"],
            },
        )
        assert suppress.status_code == 200, suppress.text
        assert suppress.json()["outcome"] == "suppressed"
        assert suppress.json()["projection"]["preferred_address"] is None
        assert client.get("/api/memories").json()  # source memory still exists

        # Re-enable with the suppressed authority snapshot.
        events = client.get("/api/relationship/events").json()["items"]
        suppressed_authority = events[0]["authority"]
        assert suppressed_authority["suppressed"] is True
        reenable = client.post(
            f"/api/relationship/authorities/{apply_event['source_memory_id']}/"
            "preferred_address/preferred_address/reenable",
            json={
                "expected_decision_id": suppressed_authority["decision_id"],
                "expected_decision_generation": suppressed_authority["generation"],
                "expected_authority_epoch": suppressed_authority["authority_epoch"],
            },
        )
        assert reenable.status_code == 200, reenable.text
        assert reenable.json()["outcome"] == "reenabled"


def test_relationship_http_smoke_redact_is_irreversible(tmp_path: Path) -> None:
    with TestClient(create_app(settings_override=_settings(tmp_path))) as client:
        _create_memory(
            client,
            content="小雪",
            subject_code="preferred_address",
        )
        client.post("/api/relationship/reconcile", json={})
        events = client.get("/api/relationship/events").json()["items"]
        apply_event = next(
            event for event in events if event["event_kind"] == "apply"
        )
        authority = apply_event["authority"]

        redact = client.post(
            f"/api/relationship/events/{apply_event['id']}/redact",
            json={
                "expected_decision_id": authority["decision_id"],
                "expected_decision_generation": authority["generation"],
                "expected_authority_epoch": authority["authority_epoch"],
                "confirm_irreversible": True,
            },
        )
        assert redact.status_code == 200, redact.text
        assert redact.json()["outcome"] == "redacted"
        assert redact.json()["projection"]["preferred_address"] is None

        events = client.get("/api/relationship/events").json()["items"]
        redacted = [
            e for e in events
            if e["id"] == apply_event["id"] and e["event_kind"] == "apply"
        ]
        assert redacted
        assert redacted[0]["payload_state"] == "redacted"
        assert redacted[0]["address"] is None


def test_relationship_http_smoke_chat_survives_relationship_neutrality(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(settings_override=_settings(tmp_path))) as client:
        session = client.post("/api/sessions", json={"title": "smoke"}).json()

        # Chat succeeds even with no relationship state at all.
        reply = client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "你好"},
        )
        assert reply.status_code == 200, reply.text
        assert reply.json()["reply"]

        # Chat succeeds with a relationship memory present.
        _create_memory(
            client,
            content="一起赏雪",
            subject_code="shared_experience",
        )
        client.post("/api/relationship/reconcile", json={})
        reply = client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "再聊"},
        )
        assert reply.status_code == 200, reply.text
        assert reply.json()["reply"]
