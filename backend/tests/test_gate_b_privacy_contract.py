from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.logging import SecretRedactionFilter
from app.main import create_app
from app.repositories.memories import MemoryRepository
from app.repositories.sqlite import managed_connection
from app.domain.models import MemoryType
from app.services.memory_source_reference import MemorySourceReferenceService


_FORBIDDEN_RESPONSE_KEYS = {
    "canonical_key_hash",
    "subject_key_hash",
    "canonical_hash",
    "content_hash",
    "source_session_reference_hash",
    "source_message_reference_hash",
    "remote_authority_fingerprint",
    "raw_response",
    "prompt",
    "hidden_reasoning",
    "authorization",
    "api_key",
}
_APPROVED_METADATA_ONLY_TABLES = {
    "memory_jobs",
    "memory_job_audits",
    "memory_write_activities",
    "memory_audit_events",
    "memory_deletion_generations",
    "memory_summary_barrier",
    "memory_summary_source_exclusions",
}


def _walk_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key
            for child in value.values()
            for key in _walk_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _walk_keys(child)}
    return set()


def _privacy_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Settings, TestClient]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'privacy.db'}",
        memory_source_reference_key_path=tmp_path / "source-reference.key",
        llm_provider="fake",
        llm_model="test-model",
        memory_automation_mode="off",
        memory_extractor_route="none",
        session_summary_enabled=False,
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return settings, TestClient(app)


def test_gate_b_api_schema_and_rows_expose_only_allowlisted_privacy_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, test_client = _privacy_client(tmp_path, monkeypatch)
    with test_client as client:
        memory = client.post("/api/memories", json={
            "content": "PRIVACY_API_SENTINEL",
            "memory_type": "preference",
            "importance": 3,
            "confidence": 1,
        }).json()["memory"]
        documents = [
            client.get("/api/memories").json(),
            client.get(f"/api/memories/{memory['id']}/versions").json(),
            client.get(f"/api/memories/{memory['id']}/evidence").json(),
            client.get("/api/memories/conflicts").json(),
            client.get("/api/memories/jobs").json(),
            client.get("/api/memories/jobs/audits").json(),
        ]

    for document in documents:
        assert _FORBIDDEN_RESPONSE_KEYS.isdisjoint(_walk_keys(document))
    with managed_connection(settings.database_url) as connection:
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'memory_%'"
            ).fetchall()
        }
        assert _APPROVED_METADATA_ONLY_TABLES <= table_names
        for table in _APPROVED_METADATA_ONLY_TABLES:
            columns = {
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            assert not ({"content", "subject", "prompt", "raw_response"} & columns)


def test_true_forget_sentinel_is_absent_from_db_api_and_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinel = "PRIVACY_TRUE_FORGET_SENTINEL"
    settings, test_client = _privacy_client(tmp_path, monkeypatch)
    with test_client as client:
        memory = client.post("/api/memories", json={
            "content": sentinel,
            "memory_type": "preference",
            "importance": 3,
            "confidence": 1,
            "metadata": {"nested": {"payload": sentinel}},
        }).json()["memory"]
        assert client.post(f"/api/memories/{memory['id']}/forget").status_code == 200
        responses = (
            client.get("/api/memories").json(),
            client.get("/api/memories", params={"status_filter": "archived"}).json(),
            client.get(f"/api/memories/{memory['id']}/versions").json(),
            client.get(f"/api/memories/{memory['id']}/evidence").json(),
            client.get("/api/memories/audit-events").json(),
        )

    assert all(sentinel not in json.dumps(item, ensure_ascii=False) for item in responses)
    with managed_connection(settings.database_url) as connection:
        readable = "\n".join(
            str(value)
            for table in (
                "memories",
                "memory_versions",
                "memory_evidence",
                "memory_write_activities",
                "memory_audit_events",
                "memory_job_audits",
            )
            for row in connection.execute(f"SELECT * FROM {table}").fetchall()
            for value in row
        )
    assert sentinel not in readable
    assert sentinel not in caplog.text


def _assert_no_hmac_material(
    review_surface: str,
    *,
    key: bytes,
    digests: tuple[str, ...],
) -> None:
    assert key.hex() not in review_surface
    assert all(digest not in review_surface for digest in digests)


def test_hmac_key_and_digest_never_enter_public_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    key = b"gate-b-privacy-contract-key-32b!"
    assert len(key) == 32
    key_path = tmp_path / "privacy-hmac.key"
    key_path.write_bytes(key)
    candidate_sentinel = "CANDIDATE_PROVENANCE_SECRET_SENTINEL"
    raw_hex = key.hex()
    digest = MemorySourceReferenceService(key).message_hash("privacy-message")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'hmac.db'}",
        memory_source_reference_key_path=key_path,
        llm_provider="fake",
        llm_model="test-model",
        memory_automation_mode="off",
        memory_extractor_route="none",
        session_summary_enabled=False,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    with managed_connection(settings.database_url) as connection:
        connection.execute(
            "INSERT INTO sessions VALUES ('candidate-session', 'title', 'now', 'now')"
        )
        candidate, _ = MemoryRepository(
            connection,
            source_references=MemorySourceReferenceService(key),
        ).create_candidate(
            content=candidate_sentinel,
            memory_type=MemoryType.OTHER,
            source_session_id="candidate-session",
            importance=3,
            confidence=0.9,
        )
        reference_hash = connection.execute(
            "SELECT source_session_reference_hash FROM memories WHERE id = ?",
            (candidate.id,),
        ).fetchone()[0]
    with TestClient(app) as client:
        public = json.dumps({
            "memories": client.get("/api/memories").json(),
            "jobs": client.get("/api/memories/jobs").json(),
            "audits": client.get("/api/memories/jobs/audits").json(),
        })

    env_example = Path(__file__).resolve().parents[2] / ".env.example"
    env_text = env_example.read_text(encoding="utf-8")
    assert key not in env_example.read_bytes()
    assert raw_hex not in env_text
    assert digest not in env_text
    assert raw_hex not in public and digest not in public
    assert reference_hash not in public
    assert raw_hex not in caplog.text and digest not in caplog.text
    review_surface = _git_review_surface(Path(__file__).resolve().parents[2])
    _assert_no_hmac_material(
        review_surface,
        key=key,
        digests=(digest, str(reference_hash)),
    )


def _git_review_surface(repository_root: Path) -> str:
    tracked = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--", "."],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    metadata = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.splitlines()
    chunks = [tracked]
    for relative in metadata:
        if not (
            relative.startswith("backend/")
            or relative.startswith("frontend/src/")
            or relative.startswith("docs/")
            or relative in {"CLAUDE.md", ".env.example"}
        ):
            continue
        path = repository_root / relative
        if path.is_file() and path.stat().st_size <= 1_000_000:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def test_complete_git_review_surface_excludes_persisted_hmac_material(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    key = b"review-surface-persisted-key-32b"
    assert len(key) == 32
    key_path = tmp_path / "review-surface.key"
    key_path.write_bytes(key)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'review-surface.db'}",
        memory_source_reference_key_path=key_path,
        llm_provider="fake",
        llm_model="test-model",
        memory_automation_mode="off",
        memory_extractor_route="none",
        session_summary_enabled=False,
    )
    references = MemorySourceReferenceService(key)
    with managed_connection(settings.database_url) as connection:
        connection.execute(
            "INSERT INTO sessions VALUES ('review-session', 'title', 'now', 'now')"
        )
        candidate, _ = MemoryRepository(
            connection,
            source_references=references,
        ).create_candidate(
            content="review surface candidate",
            memory_type=MemoryType.OTHER,
            source_session_id="review-session",
            importance=3,
            confidence=0.9,
        )
        persisted_digest = connection.execute(
            "SELECT source_session_reference_hash FROM memories WHERE id = ?",
            (candidate.id,),
        ).fetchone()[0]

    _assert_no_hmac_material(
        _git_review_surface(repository_root),
        key=key,
        digests=(str(persisted_digest),),
    )


def test_secret_redaction_filter_removes_key_and_digest_from_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_key = "privacy-log-key-sentinel"
    digest = hashlib.sha256(raw_key.encode()).hexdigest()
    logger = logging.getLogger("gate-b-privacy-contract")
    logger.setLevel(logging.INFO)
    logger.addFilter(SecretRedactionFilter((raw_key, digest)))
    try:
        with caplog.at_level(logging.INFO, logger=logger.name):
            logger.info("key=%s digest=%s", raw_key, digest)
    finally:
        logger.filters.clear()
    assert raw_key not in caplog.text
    assert digest not in caplog.text
