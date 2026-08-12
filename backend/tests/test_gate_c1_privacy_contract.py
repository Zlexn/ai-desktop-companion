from __future__ import annotations

import json
import logging
from pathlib import Path
import secrets
import subprocess

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import MemoryType
from app.main import create_app
from app.providers.base import LLMResponse
from app.repositories.memories import MemoryRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.memory_source_reference import MemorySourceReferenceService


_FORBIDDEN_PUBLIC_KEYS = {
    "rendered_system_prompt",
    "content_identity_hash",
    "behavior_fingerprint",
    "source_content_json",
    "raw_response",
    "authorization",
    "api_key",
}


def _walk_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for child in value.values() for key in _walk_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _walk_keys(child)}
    return set()


def test_gate_c1_public_persona_and_manifest_are_metadata_only(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'privacy.db'}",
        memory_source_reference_key_path=tmp_path / "privacy.key",
        llm_provider="fake",
        llm_model="test-model",
        session_summary_enabled=False,
    )
    with TestClient(create_app(settings_override=settings)) as client:
        current = client.get("/api/persona/current").json()
        session = client.post("/api/sessions", json={"title": "privacy"}).json()
        reply = client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "hello"},
        )
        assert reply.status_code == 200
        messages = client.get(
            f"/api/sessions/{session['id']}/messages"
        ).json()
        public = {
            "current": current,
            "artifacts": client.get("/api/persona/artifacts").json(),
            "messages": messages,
            "capabilities": client.get("/api/persona/capabilities").json(),
        }

    assert _FORBIDDEN_PUBLIC_KEYS.isdisjoint(_walk_keys(public))
    manifest = messages[-1]["metadata"]["context_manifest"]
    assert "prompt" not in json.dumps(manifest).lower()
    assert set(manifest) == {
        "schema_version",
        "persona_artifact_id",
        "composer_version",
        "encoder_version",
        "selected_recent_message_ids",
        "selected_memory_version_ids",
        "source_emotion_version",
        "relationship_projection_id",
        "relationship_projection_version",
        "selected_summary_ids",
        "selected_counts",
        "trim_reason_counts",
        "provider_character_count",
        "max_characters",
    }


def test_gate_c1_redaction_erases_payload_and_never_returns_sentinel(
    tmp_path: Path,
) -> None:
    sentinel = "PRIVATE_PERSONA_SENTINEL_C1"
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'redaction.db'}",
        memory_source_reference_key_path=tmp_path / "redaction.key",
        llm_provider="fake",
        session_summary_enabled=False,
    )
    with TestClient(create_app(settings_override=settings)) as client:
        first = client.get("/api/persona/current").json()
        replacement = first["config"]
        replacement["background"] = sentinel
        second = client.post(
            "/api/persona/artifacts",
            json={
                "config": replacement,
                "expected_artifact_id": first["id"],
                "expected_generation": first["activation_generation"],
            },
        ).json()
        third_config = second["config"]
        third_config["identity"]["name"] = "安全替代版本"
        third_config["background"] = "替代版本不保留待清除内容。"
        third = client.post(
            "/api/persona/artifacts",
            json={
                "config": third_config,
                "expected_artifact_id": second["id"],
                "expected_generation": second["activation_generation"],
            },
        ).json()
        redacted = client.post(
            f"/api/persona/artifacts/{second['id']}/redact",
            json={
                "expected_artifact_id": third["id"],
                "expected_generation": third["activation_generation"],
                "confirmation": "redact_persona_payload",
            },
        )
        assert redacted.status_code == 200
        public = json.dumps(
            {
                "redacted": redacted.json(),
                "list": client.get("/api/persona/artifacts").json(),
            },
            ensure_ascii=False,
        )

    assert sentinel not in public
    with managed_connection(settings.database_url) as connection:
        row = connection.execute(
            "SELECT source_content_json, rendered_system_prompt "
            "FROM persona_artifacts WHERE id = ?",
            (second["id"],),
        ).fetchone()
        assert row is not None
        assert tuple(row) == (None, None)


def _review_surface(repository_root: Path) -> str:
    tracked = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--", "."],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.splitlines()
    readable = []
    allowed_roots = ("backend/", "frontend/src/", "docs/")
    allowed_names = {"CLAUDE.md", ".env.example"}
    allowed_suffixes = {".py", ".ts", ".tsx", ".md", ".json", ".txt"}
    for relative in untracked:
        normalized = relative.replace("\\", "/")
        if not (
            normalized.startswith(allowed_roots) or normalized in allowed_names
        ):
            continue
        path = repository_root / relative
        if (
            path.is_file()
            and path.suffix.lower() in allowed_suffixes
            and path.stat().st_size <= 1_000_000
        ):
            readable.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join([tracked, *readable])


def test_gate_c1_provider_raw_output_and_credentials_never_reach_db_or_logs(
    tmp_path: Path,
    caplog,
) -> None:
    raw = "GATE_C1_PROVIDER_RAW_SENTINEL"
    key = "GATE_C1_TEST_API_KEY_SENTINEL"

    class MetadataProvider:
        provider_name = "fake"

        async def generate(self, messages, options):
            return LLMResponse(
                text="safe",
                provider="fake",
                model=options.model,
                metadata={"raw_response": raw, "api_key": key},
            )

        async def aclose(self):
            pass

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'provider-metadata.db'}",
        memory_source_reference_key_path=tmp_path / "provider-metadata.key",
        llm_provider="fake",
        session_summary_enabled=False,
    )
    caplog.set_level(logging.DEBUG)
    with TestClient(
        create_app(
            settings_override=settings,
            chat_provider_factory=MetadataProvider,
        )
    ) as client:
        session = client.post("/api/sessions", json={"title": "privacy"}).json()
        response = client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "hello"},
        )
        assert response.status_code == 200
        public = json.dumps(
            client.get(f"/api/sessions/{session['id']}/messages").json()
        )
    with managed_connection(settings.database_url) as connection:
        persisted = "\n".join(
            str(value)
            for row in connection.execute("SELECT * FROM messages").fetchall()
            for value in row
        )
    assert raw not in public and key not in public
    assert raw not in persisted and key not in persisted
    assert raw not in caplog.text and key not in caplog.text


def test_gate_c1_bounded_review_surface_excludes_runtime_private_material(
    tmp_path: Path,
    caplog,
) -> None:
    root = Path(__file__).resolve().parents[2]
    key = secrets.token_bytes(32)
    key_path = tmp_path / "runtime-source-reference.key"
    key_path.write_bytes(key)
    source_references = MemorySourceReferenceService(key)
    provider_raw = f"provider-raw-{secrets.token_hex(24)}"
    api_key = f"sk-runtime-{secrets.token_hex(24)}"
    deleted_payload = f"deleted-persona-{secrets.token_hex(24)}"
    private_asset = str(
        tmp_path / f"private-assets-{secrets.token_hex(12)}" / "voice-reference.wav"
    )

    class RuntimeMetadataProvider:
        provider_name = "fake"

        async def generate(self, messages, options):
            return LLMResponse(
                text="safe",
                provider="fake",
                model=options.model,
                metadata={"raw_response": provider_raw, "api_key": api_key},
            )

        async def aclose(self):
            pass

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'runtime-private.db'}",
        memory_source_reference_key_path=key_path,
        llm_provider="fake",
        session_summary_enabled=False,
    )
    with managed_connection(settings.database_url) as connection:
        source_session = SessionRepository(connection).create("HMAC source")
        candidate, _ = MemoryRepository(
            connection,
            source_references=source_references,
        ).create_candidate(
            content="runtime HMAC source",
            memory_type=MemoryType.OTHER,
            source_session_id=source_session.id,
            importance=3,
            confidence=0.9,
        )
        hmac_digest = str(
            connection.execute(
                "SELECT source_session_reference_hash FROM memories WHERE id=?",
                (candidate.id,),
            ).fetchone()[0]
        )
    caplog.set_level(logging.DEBUG)
    with TestClient(
        create_app(
            settings_override=settings,
            chat_provider_factory=RuntimeMetadataProvider,
        )
    ) as client:
        first = client.get("/api/persona/current").json()
        private_config = first["config"]
        private_config["background"] = deleted_payload
        private = client.post(
            "/api/persona/artifacts",
            json={
                "config": private_config,
                "expected_artifact_id": first["id"],
                "expected_generation": first["activation_generation"],
            },
        ).json()
        replacement_config = private["config"]
        replacement_config["background"] = "不包含已删除内容的安全替代版本。"
        replacement_config["identity"]["name"] = "审阅面安全替代角色"
        replacement = client.post(
            "/api/persona/artifacts",
            json={
                "config": replacement_config,
                "expected_artifact_id": private["id"],
                "expected_generation": private["activation_generation"],
            },
        ).json()
        assert client.post(
            f"/api/persona/artifacts/{private['id']}/redact",
            json={
                "expected_artifact_id": replacement["id"],
                "expected_generation": replacement["activation_generation"],
                "confirmation": "redact_persona_payload",
            },
        ).status_code == 200
        session = client.post(
            "/api/sessions", json={"title": "bounded privacy"}
        ).json()
        assert client.post(
            f"/api/sessions/{session['id']}/messages",
            json={"content": "privacy check"},
        ).status_code == 200
        public = json.dumps(
            {
                "current": client.get("/api/persona/current").json(),
                "artifacts": client.get("/api/persona/artifacts").json(),
                "messages": client.get(
                    f"/api/sessions/{session['id']}/messages"
                ).json(),
            },
            ensure_ascii=False,
        )

    with managed_connection(settings.database_url) as connection:
        private_row = connection.execute(
            "SELECT content_identity_hash, behavior_fingerprint, "
            "source_content_json, rendered_system_prompt "
            "FROM persona_artifacts WHERE id=?",
            (private["id"],),
        ).fetchone()
        replacement_row = connection.execute(
            "SELECT content_identity_hash, behavior_fingerprint, "
            "rendered_system_prompt FROM persona_artifacts WHERE id=?",
            (replacement["id"],),
        ).fetchone()
    assert private_row is not None and replacement_row is not None
    assert private_row["source_content_json"] is None
    assert private_row["rendered_system_prompt"] is None

    full_fingerprints = (
        str(private_row["content_identity_hash"]),
        str(private_row["behavior_fingerprint"]),
        str(replacement_row["content_identity_hash"]),
        str(replacement_row["behavior_fingerprint"]),
    )
    compiled_prompt = str(replacement_row["rendered_system_prompt"])
    review_surface = _review_surface(root)
    frontend_fixture = (
        root / "frontend" / "src" / "components" / "PersonaPanel.test.tsx"
    ).read_text(encoding="utf-8")
    sensitive_values = (
        *full_fingerprints,
        compiled_prompt,
        key.hex(),
        hmac_digest,
        provider_raw,
        api_key,
        deleted_payload,
        private_asset,
    )
    for value in sensitive_values:
        assert value not in public
        assert value not in caplog.text
        assert value not in frontend_fixture
        assert value not in review_surface


def test_gate_c1_frontend_fixture_never_contains_private_redacted_payload() -> None:
    component = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "components"
        / "PersonaPanel.tsx"
    ).read_text(encoding="utf-8")
    assert "PRIVATE_PERSONA_SENTINEL_C1" not in component
    assert "rendered_system_prompt" not in component
    assert "behavior_fingerprint" not in component
