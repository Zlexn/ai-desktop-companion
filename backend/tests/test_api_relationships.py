from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'relationship-api.db'}",
        memory_source_reference_key_path=tmp_path / "source-reference.key",
    )


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(settings_override=_settings(tmp_path))) as value:
        yield value


def _create_relationship_memory(
    client: TestClient,
    *,
    content: str,
    subject_code: str,
) -> dict:
    memory_type = "preference" if subject_code == "preferred_address" else "relationship_event"
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


def _authority_of_apply(client: TestClient, apply_event_id: str) -> dict:
    events = client.get("/api/relationship/events").json()["items"]
    for event in events:
        if event["id"] == apply_event_id:
            return event["authority"]
    raise AssertionError(f"apply event {apply_event_id} not found")


def test_relationship_capabilities_is_local_only(client) -> None:
    response = client.get("/api/relationship/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["local_only"] is True
    assert body["remote_extraction"] is False
    assert body["remote_consent_exists"] is False
    assert body["projection"] is True


def test_projection_neutral_when_no_relationship_memory(client) -> None:
    response = client.get("/api/relationship/projection")

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["projection_id"] is None


def test_reconcile_builds_projection_and_bounded_events(client) -> None:
    _create_relationship_memory(
        client,
        content="一起赏雪",
        subject_code="shared_experience",
    )

    reconcile = client.post("/api/relationship/reconcile", json={})
    assert reconcile.status_code == 200, reconcile.text

    projection = client.get("/api/relationship/projection")
    assert projection.status_code == 200
    body = projection.json()
    assert body["available"] is True
    assert body["projection_id"]
    assert body["projection_version"] >= 1
    assert body["persona_artifact_id"]

    events = client.get("/api/relationship/events").json()
    assert len(events["items"]) >= 1
    apply_events = [e for e in events["items"] if e["event_kind"] == "apply"]
    assert apply_events
    event = apply_events[0]
    assert event["event_type"] == "shared_experience"
    assert event["subject_code"] == "shared_experience"
    assert event["source_memory_id"]  # memory is still readable
    # Never expose raw payload, fingerprints, hashes, or version ids.
    assert "payload_json" not in event
    assert "integrity_fingerprint" not in event
    assert "source_memory_version_id" not in event
    assert "lineage" not in event
    assert "hmac" not in str(event)


def test_events_never_expose_forbidden_fields(client) -> None:
    _create_relationship_memory(
        client,
        content="一起赏雪",
        subject_code="shared_experience",
    )
    client.post("/api/relationship/reconcile", json={})

    response = client.get("/api/relationship/events")
    text = response.text
    for forbidden in (
        "payload_json",
        "integrity_fingerprint",
        "inherited_authority_fingerprint",
        "lineage",
        "hmac",
        "preferred_address_candidate",
    ):
        assert forbidden not in text


def test_jobs_and_audits_are_metadata_only(client) -> None:
    _create_relationship_memory(
        client,
        content="一起赏雪",
        subject_code="shared_experience",
    )
    client.post("/api/relationship/reconcile", json={})

    jobs = client.get("/api/relationship/jobs").json()
    assert jobs["items"]
    job = jobs["items"][0]
    for forbidden in (
        "captured_inherited_authority_fingerprint",
        "payload",
        "integrity_fingerprint",
    ):
        assert forbidden not in str(job)

    audits = client.get("/api/relationship/audits").json()
    assert audits["items"]
    for forbidden in ("payload", "fingerprint", "hmac", "lineage"):
        assert forbidden not in str(audits["items"][0])


def test_suppress_revokes_without_editing_source_memory(client) -> None:
    memory = _create_relationship_memory(
        client,
        content="小雪",
        subject_code="preferred_address",
    )
    client.post("/api/relationship/reconcile", json={})

    events = client.get("/api/relationship/events").json()["items"]
    apply_event = next(
        event for event in events if event["event_kind"] == "apply"
    )
    assert apply_event["address"] == "小雪"
    authority = apply_event["authority"]

    suppress = client.post(
        f"/api/relationship/events/{apply_event['id']}/suppress",
        json={
            "expected_decision_id": authority["decision_id"],
            "expected_decision_generation": authority["generation"],
            "expected_authority_epoch": authority["authority_epoch"],
        },
    )
    assert suppress.status_code == 200, suppress.text
    body = suppress.json()
    assert body["outcome"] == "suppressed"
    assert body["authority"]["suppressed"] is True

    # Source memory is unchanged (relationship-only revoke).
    memory_list = client.get("/api/memories").json()
    assert any(item["id"] == memory["id"] for item in memory_list)

    # Projection no longer exposes the address.
    projection = client.get("/api/relationship/projection").json()
    assert projection["preferred_address"] is None

    # The apply is revoked; address not exposed for the revoked apply.
    events = client.get("/api/relationship/events").json()["items"]
    revoked = [
        e for e in events if e["event_kind"] == "revoke"
    ]
    assert revoked
    assert all(e["address"] is None for e in revoked)


def test_suppress_requires_exact_authority_generation(client) -> None:
    _create_relationship_memory(
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

    stale = client.post(
        f"/api/relationship/events/{apply_event['id']}/suppress",
        json={
            "expected_decision_id": authority["decision_id"],
            "expected_decision_generation": authority["generation"] + 1,
            "expected_authority_epoch": authority["authority_epoch"],
        },
    )
    assert stale.status_code == 409


def test_redact_requires_confirmation_and_clears_address(client) -> None:
    _create_relationship_memory(
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

    # Missing confirm_irreversible is rejected.
    without_confirmation = client.post(
        f"/api/relationship/events/{apply_event['id']}/redact",
        json={
            "expected_decision_id": authority["decision_id"],
            "expected_decision_generation": authority["generation"],
            "expected_authority_epoch": authority["authority_epoch"],
        },
    )
    assert without_confirmation.status_code == 422

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

    projection = client.get("/api/relationship/projection").json()
    assert projection["preferred_address"] is None

    events = client.get("/api/relationship/events").json()["items"]
    redacted = [
        e for e in events
        if e["id"] == apply_event["id"] and e["event_kind"] == "apply"
    ]
    assert redacted
    assert redacted[0]["payload_state"] == "redacted"
    assert redacted[0]["address"] is None


def test_reenable_requires_exact_authority_and_derives_new_apply(client) -> None:
    _create_relationship_memory(
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

    client.post(
        f"/api/relationship/events/{apply_event['id']}/suppress",
        json={
            "expected_decision_id": authority["decision_id"],
            "expected_decision_generation": authority["generation"],
            "expected_authority_epoch": authority["authority_epoch"],
        },
    )
    events = client.get("/api/relationship/events").json()["items"]
    suppressed_authority = events[0]["authority"]
    assert suppressed_authority["suppressed"] is True

    reenable = client.post(
        "/api/relationship/authorities/"
        f"{apply_event['source_memory_id']}/preferred_address/preferred_address/"
        "reenable",
        json={
            "expected_decision_id": suppressed_authority["decision_id"],
            "expected_decision_generation": suppressed_authority["generation"],
            "expected_authority_epoch": suppressed_authority["authority_epoch"],
        },
    )
    assert reenable.status_code == 200, reenable.text
    body = reenable.json()
    assert body["outcome"] == "reenabled"
    assert body["authority"]["suppressed"] is False
    assert body["authority"]["action"] == "reenable"


def test_reenable_stale_generation_is_409(client) -> None:
    _create_relationship_memory(
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

    client.post(
        f"/api/relationship/events/{apply_event['id']}/suppress",
        json={
            "expected_decision_id": authority["decision_id"],
            "expected_decision_generation": authority["generation"],
            "expected_authority_epoch": authority["authority_epoch"],
        },
    )
    events = client.get("/api/relationship/events").json()["items"]
    suppressed_authority = events[0]["authority"]

    stale = client.post(
        "/api/relationship/authorities/"
        f"{apply_event['source_memory_id']}/preferred_address/preferred_address/"
        "reenable",
        json={
            "expected_decision_id": suppressed_authority["decision_id"],
            "expected_decision_generation": (
                suppressed_authority["generation"] + 1
            ),
            "expected_authority_epoch": suppressed_authority["authority_epoch"],
        },
    )
    assert stale.status_code == 409


def test_reconcile_stale_projection_version_is_409(client) -> None:
    _create_relationship_memory(
        client,
        content="一起赏雪",
        subject_code="shared_experience",
    )
    client.post("/api/relationship/reconcile", json={})
    projection = client.get("/api/relationship/projection").json()
    assert projection["available"] is True

    stale = client.post(
        "/api/relationship/reconcile",
        json={"expected_projection_version": projection["projection_version"] + 1},
    )
    assert stale.status_code == 409


def test_mutation_requests_forbid_extra_fields(client) -> None:
    response = client.post(
        "/api/relationship/events/not-real/suppress",
        json={
            "expected_decision_id": None,
            "expected_decision_generation": 0,
            "expected_authority_epoch": 0,
            "unexpected": True,
        },
    )
    assert response.status_code == 422


def test_rebuild_is_idempotent_and_bounded(client) -> None:
    _create_relationship_memory(
        client,
        content="一起赏雪",
        subject_code="shared_experience",
    )
    first = client.post("/api/relationship/rebuild", json={})
    assert first.status_code == 200, first.text

    projection = client.get("/api/relationship/projection").json()
    assert projection["available"] is True
    first_familiarity = projection["familiarity_bucket"]

    second = client.post("/api/relationship/rebuild", json={})
    assert second.status_code == 200
    projection = client.get("/api/relationship/projection").json()
    assert projection["familiarity_bucket"] == first_familiarity


def test_openapi_relationship_schemas_have_no_forbidden_fields(client) -> None:
    openapi = client.get("/openapi.json").json()
    schemas = openapi["components"]["schemas"]
    relationship_schema_names = [
        name for name in schemas if name.startswith("Relationship")
    ]
    assert "RelationshipProjectionResponse" in relationship_schema_names
    assert "RelationshipEventResponse" in relationship_schema_names
    assert "RelationshipJobResponse" in relationship_schema_names
    assert "RelationshipAuditResponse" in relationship_schema_names
    assert "RelationshipCapabilitiesResponse" in relationship_schema_names

    for name in relationship_schema_names:
        properties = schemas[name].get("properties", {})
        for forbidden in (
            "payload_json",
            "integrity_fingerprint",
            "inherited_authority_fingerprint",
            "lineage",
            "hmac",
            "source_memory_version_id",
            "preferred_address_candidate",
        ):
            assert forbidden not in properties, f"{name} exposes {forbidden}"


def test_relationship_routes_exist_in_openapi(client) -> None:
    openapi = client.get("/openapi.json").json()
    paths = openapi["paths"]
    expected = {
        "/api/relationship/capabilities",
        "/api/relationship/projection",
        "/api/relationship/events",
        "/api/relationship/jobs",
        "/api/relationship/audits",
        "/api/relationship/reconcile",
        "/api/relationship/rebuild",
    }
    assert expected.issubset(paths.keys())
