from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.repositories.sqlite import managed_connection


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        memory_source_reference_key_path=tmp_path / "source-reference.key",
    )


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(settings_override=_settings(tmp_path))) as value:
        yield value


def _config(name: str = "林夕") -> dict[str, object]:
    return {
        "identity": {
            "name": name,
            "species": "原创虚拟角色",
            "role": "陪伴型文字对话伙伴",
        },
        "background": "住在安静书房里的原创虚拟角色。",
        "personality": {
            "core_traits": ["温和", "可靠"],
            "values": ["尊重边界", "准确"],
        },
        "language_style": {
            "tone": "自然、克制",
            "habits": ["简洁中文", "必要时列点"],
        },
        "relationship": {"initial": "刚刚认识。"},
        "additional_prohibitions": ["不得虚构共同经历。"],
    }


def test_persona_api_never_returns_compiled_prompt_or_full_hash(client) -> None:
    current = client.get("/api/persona/current")

    assert current.status_code == 200
    text = current.text
    assert "rendered_system_prompt" not in text
    assert "content_identity_hash" not in text
    assert "behavior_fingerprint" not in text
    assert len(current.json()["fingerprint_prefix"]) == 12
    assert current.json()["active"] is True


def test_persona_list_and_detail_return_bounded_config(client) -> None:
    current = client.get("/api/persona/current").json()

    listing = client.get("/api/persona/artifacts")
    detail = client.get(f"/api/persona/artifacts/{current['id']}")

    assert listing.status_code == 200
    assert listing.json() == [detail.json()]
    assert detail.json()["config"]["identity"]["name"] == "林夕"
    assert "rendered_system_prompt" not in detail.text


def test_persona_create_no_change_then_new_version(client) -> None:
    current = client.get("/api/persona/current").json()
    request = {
        "config": current["config"],
        "expected_artifact_id": current["id"],
        "expected_generation": current["activation_generation"],
    }
    no_change = client.post("/api/persona/artifacts", json=request)

    assert no_change.status_code == 200
    assert no_change.json()["outcome"] == "no_change"
    assert len(client.get("/api/persona/artifacts").json()) == 1

    request["config"] = _config("林月")
    created = client.post("/api/persona/artifacts", json=request)
    assert created.status_code == 200
    assert created.json()["outcome"] == "created"
    assert created.json()["version"] == 2
    assert created.json()["activation_generation"] == 1


def test_persona_activation_cas_conflict_is_409(client) -> None:
    current = client.get("/api/persona/current").json()
    response = client.post(
        "/api/persona/active",
        json={
            "artifact_id": current["id"],
            "expected_artifact_id": "stale",
            "expected_generation": current["activation_generation"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "persona_version_conflict"


def test_persona_redaction_switches_current_and_hides_payload(client) -> None:
    first = client.get("/api/persona/current").json()
    second = client.post(
        "/api/persona/artifacts",
        json={
            "config": _config("林月"),
            "expected_artifact_id": first["id"],
            "expected_generation": first["activation_generation"],
        },
    ).json()

    response = client.post(
        f"/api/persona/artifacts/{second['id']}/redact",
        json={
            "expected_artifact_id": second["id"],
            "expected_generation": second["activation_generation"],
            "replacement_artifact_id": first["id"],
            "confirmation": "redact_persona_payload",
        },
    )

    assert response.status_code == 200
    assert response.json()["redacted"]["payload_state"] == "redacted"
    assert response.json()["redacted"]["config"] is None
    assert response.json()["redacted"]["fingerprint_prefix"] is None
    assert "林月" not in response.text
    detail = client.get(f"/api/persona/artifacts/{second['id']}").json()
    assert detail["config"] is None


def test_safe_historical_redaction_needs_no_replacement(client) -> None:
    first = client.get("/api/persona/current").json()
    second = client.post(
        "/api/persona/artifacts",
        json={
            "config": _config("林月"),
            "expected_artifact_id": first["id"],
            "expected_generation": first["activation_generation"],
        },
    ).json()

    response = client.post(
        f"/api/persona/artifacts/{first['id']}/redact",
        json={
            "expected_artifact_id": second["id"],
            "expected_generation": second["activation_generation"],
            "confirmation": "redact_persona_payload",
        },
    )
    assert response.status_code == 200


def test_current_redaction_without_replacement_is_rejected(client) -> None:
    current = client.get("/api/persona/current").json()
    response = client.post(
        f"/api/persona/artifacts/{current['id']}/redact",
        json={
            "expected_artifact_id": current["id"],
            "expected_generation": current["activation_generation"],
            "confirmation": "redact_persona_payload",
        },
    )
    assert response.status_code == 400


def test_persona_requests_forbid_extra_file_url_and_binary_fields(client) -> None:
    current = client.get("/api/persona/current").json()
    base = {
        "config": current["config"],
        "expected_artifact_id": current["id"],
        "expected_generation": current["activation_generation"],
    }
    for field, value in (
        ("file_path", "C:/private/persona.yaml"),
        ("url", "https://example.invalid/persona"),
        ("binary", "AAEC"),
        ("unexpected", True),
    ):
        response = client.post(
            "/api/persona/artifacts",
            json={**base, field: value},
        )
        assert response.status_code == 422


def test_redact_rejects_both_replacement_mechanisms(client) -> None:
    current = client.get("/api/persona/current").json()
    response = client.post(
        f"/api/persona/artifacts/{current['id']}/redact",
        json={
            "expected_artifact_id": current["id"],
            "expected_generation": current["activation_generation"],
            "replacement_artifact_id": current["id"],
            "replacement_config": _config("林月"),
            "confirmation": "redact_persona_payload",
        },
    )
    assert response.status_code == 422


def test_invalid_nested_persona_content_is_safe_client_error(client) -> None:
    current = client.get("/api/persona/current").json()
    config = _config()
    config["personality"] = {
        **config["personality"],
        "core_traits": ["x" * 41],
    }
    response = client.post(
        "/api/persona/artifacts",
        json={
            "config": config,
            "expected_artifact_id": current["id"],
            "expected_generation": current["activation_generation"],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert "x" * 41 not in response.text


def test_artifact_list_fails_closed_on_corrupt_history(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings_override=settings)) as client:
        first = client.get("/api/persona/current").json()
        client.post(
            "/api/persona/artifacts",
            json={
                "config": _config("林月"),
                "expected_artifact_id": first["id"],
                "expected_generation": first["activation_generation"],
            },
        ).raise_for_status()

    with managed_connection(settings.database_url) as connection:
        connection.execute("DROP TRIGGER trg_persona_artifacts_immutable_update")
        connection.execute(
            "UPDATE persona_artifacts SET behavior_fingerprint=? WHERE id=?",
            ("f" * 64, first["id"]),
        )
        connection.commit()

    with TestClient(create_app(settings_override=settings)) as client:
        response = client.get("/api/persona/artifacts")
        assert response.status_code == 500
        assert "ffffffffffff" not in response.text
        assert first["config"]["identity"]["name"] not in response.text


def test_remote_summary_route_constructs_nothing_before_c2(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'remote-summary.db'}",
        memory_source_reference_key_path=tmp_path / "remote-summary.key",
        session_summary_provider="llm",
        session_summary_llm_provider="deepseek",
    )
    explicit_calls = 0

    def forbidden_explicit_factory():
        nonlocal explicit_calls
        explicit_calls += 1
        raise AssertionError("explicit remote summary provider constructed")

    app = create_app(
        settings_override=settings,
        summary_provider_factory=forbidden_explicit_factory,
    )
    with TestClient(app) as client:
        capabilities = client.get("/api/persona/capabilities").json()
        assert capabilities["remote_summary"] == (
            "remote_summary_available_requires_consent"
        )
        session = client.post("/api/sessions", json={"title": "safe"}).json()
        assert client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "hello"},
        ).status_code == 200
    assert explicit_calls == 0


def test_remote_summary_environment_path_constructs_nothing_before_c2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv(
        "DATABASE_URL",
        f"sqlite:///{tmp_path / 'remote-summary-env.db'}",
    )
    monkeypatch.setenv(
        "MEMORY_SOURCE_REFERENCE_KEY_PATH",
        str(tmp_path / "remote-summary-env.key"),
    )
    monkeypatch.setenv("SESSION_SUMMARY_PROVIDER", "llm")
    monkeypatch.setenv("SESSION_SUMMARY_LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            assert client.get("/api/persona/capabilities").json()[
                "remote_summary"
            ] == "remote_summary_available_requires_consent"
    finally:
        get_settings.cache_clear()


def test_persona_capabilities_are_metadata_only(client) -> None:
    response = client.get("/api/persona/capabilities")
    assert response.status_code == 200
    assert response.json() == {
        "persona_artifacts": True,
        "context_composer": True,
        "summary_processing": True,
        "summary_injection": True,
        "relationship_projection": False,
        "remote_summary": "local_summary_available",
    }
    assert "consent" not in response.text.lower()


def test_persona_api_redacted_payload_absent_from_raw_sqlite(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings_override=settings)) as client:
        first = client.get("/api/persona/current").json()
        second = client.post(
            "/api/persona/artifacts",
            json={
                "config": _config("私密代号"),
                "expected_artifact_id": first["id"],
                "expected_generation": first["activation_generation"],
            },
        ).json()
        client.post(
            f"/api/persona/artifacts/{second['id']}/redact",
            json={
                "expected_artifact_id": second["id"],
                "expected_generation": second["activation_generation"],
                "replacement_artifact_id": first["id"],
                "confirmation": "redact_persona_payload",
            },
        ).raise_for_status()

    with managed_connection(settings.database_url) as connection:
        row = connection.execute(
            "SELECT source_content_json, rendered_system_prompt "
            "FROM persona_artifacts WHERE id=?",
            (second["id"],),
        ).fetchone()
        assert tuple(row) == (None, None)
