from __future__ import annotations

import json
import logging
from pathlib import Path
import secrets
import subprocess
import time

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.providers.base import LLMResponse
from app.repositories.sqlite import managed_connection
from app.services.session_summary_provider import LLMSessionSummaryProvider
from app.services.summary_rebuild import SummaryRebuildService


_FORBIDDEN_PUBLIC_KEYS = {
    "source_set_hash",
    "logical_source_identity",
    "attempt_epoch",
    "policy_fingerprint",
    "rebuild_permit_id",
    "raw_response",
    "prompt",
    "source_message_ids",
    "source_turn_ids",
    "authorization",
    "api_key",
}
_METADATA_ONLY_TABLES = (
    "summary_authority_audits",
    "summary_job_audits",
    "summary_suppression_audits",
    "summary_payload_audits",
)


def _walk_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for child in value.values() for key in _walk_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _walk_keys(child)}
    return set()


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
    readable: list[str] = []
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


def _wait_for_summary(client: TestClient, session_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(
            "/api/summaries",
            params={"session_id": session_id, "limit": 100},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        if items:
            return items[0]
        time.sleep(0.01)
    raise AssertionError("privacy-contract summary was not generated")


def _grant_remote(client: TestClient, path: str) -> None:
    current = client.get(path).json()
    response = client.put(
        path,
        json={"action": "grant", "expected_generation": current["generation"]},
    )
    assert response.status_code == 200
    assert response.json()["valid_for_current_policy"] is True


class RuntimeMetadataLLM:
    provider_name = "deepseek"

    def __init__(self, *, safe_summary: str, provider_raw: str, api_key: str) -> None:
        self.safe_summary = safe_summary
        self.provider_raw = provider_raw
        self.api_key = api_key

    async def generate(self, messages, options):
        assert messages
        return LLMResponse(
            text=self.safe_summary,
            provider="deepseek",
            model=options.model,
            metadata={
                "raw_response": self.provider_raw,
                "api_key": self.api_key,
            },
        )

    async def aclose(self) -> None:
        pass


def test_gate_c2_runtime_private_values_never_reach_public_surfaces_or_audits(
    tmp_path: Path,
    caplog,
) -> None:
    root = Path(__file__).resolve().parents[2]
    source_text = f"source-{secrets.token_hex(24)}"
    deleted_payload = f"deleted-summary-{secrets.token_hex(24)}"
    provider_raw = f"provider-raw-{secrets.token_hex(24)}"
    api_key = f"sk-runtime-{secrets.token_hex(24)}"
    hmac_key = secrets.token_bytes(32)
    key_path = tmp_path / "runtime-summary-source.key"
    key_path.write_bytes(hmac_key)
    private_asset = str(
        tmp_path / f"private-assets-{secrets.token_hex(12)}" / "voice-reference.wav"
    )
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'gate-c2-privacy.db'}",
        memory_source_reference_key_path=key_path,
        llm_provider="deepseek",
        llm_model="chat-model",
        deepseek_api_key=api_key,
        session_summary_enabled=True,
        session_summary_provider="llm",
        session_summary_llm_provider="deepseek",
        session_summary_llm_model="summary-model",
        session_summary_trigger_turn_count=1,
        session_summary_max_input_turns=2,
        session_summary_max_input_messages=4,
        summary_injection_min_lexical_relevance=0.0,
        summary_rebuild_min_safe_turns=1,
    )
    runtime_llm = RuntimeMetadataLLM(
        safe_summary=deleted_payload,
        provider_raw=provider_raw,
        api_key=api_key,
    )
    caplog.set_level(logging.DEBUG)

    with TestClient(
        create_app(
            settings_override=settings,
            chat_provider_factory=lambda: RuntimeMetadataLLM(
                safe_summary="safe chat reply",
                provider_raw=provider_raw,
                api_key=api_key,
            ),
            summary_provider_factory=lambda: LLMSessionSummaryProvider(
                llm_provider=runtime_llm,
                model=settings.session_summary_llm_model,
            ),
        )
    ) as client:
        _grant_remote(client, "/api/summaries/processing-consent")
        source = client.post(
            "/api/sessions", json={"title": "C2 privacy source"}
        ).json()
        chat = client.post(
            f"/api/sessions/{source['id']}/messages",
            json={"content": source_text},
        )
        assert chat.status_code == 200
        summary = _wait_for_summary(client, source["id"])
        assert summary["summary_text"] == deleted_payload

        redacted = client.post(
            f"/api/summaries/{summary['id']}/redact",
            json={
                "expected_suppression_generation": summary[
                    "suppression_generation"
                ],
                "confirmation": "redact_summary_payload",
            },
        )
        assert redacted.status_code == 200
        redacted_summary = client.get(f"/api/summaries/{summary['id']}").json()
        assert redacted_summary["summary_text"] is None

        permit = SummaryRebuildService(
            settings.database_url,
            settings=settings,
        ).authorize(
            summary_id=summary["id"],
            expected_suppression_generation=redacted.json()[
                "suppression_generation"
            ],
        )
        public_document = {
            "capabilities": client.get("/api/summaries/capabilities").json(),
            "processing": client.get(
                "/api/summaries/processing-consent"
            ).json(),
            "injection": client.get("/api/summaries/injection-consent").json(),
            "status": client.get("/api/summaries/status").json(),
            "summaries": client.get("/api/summaries?limit=100").json(),
            "jobs": client.get("/api/summaries/jobs?limit=100").json(),
            "audits": client.get("/api/summaries/audits?limit=100").json(),
            "detail": client.get(f"/api/summaries/{summary['id']}").json(),
        }
        public_api_json = json.dumps(public_document, ensure_ascii=False)
        hmac_digest = client.app.state.memory_source_reference_service.session_hash(
            source["id"]
        )

    with managed_connection(settings.database_url) as connection:
        row = connection.execute(
            "SELECT summary_text, payload_state FROM session_summaries WHERE id=?",
            (summary["id"],),
        ).fetchone()
        assert tuple(row) == (None, "redacted")
        private_row = connection.execute(
            "SELECT source_set_hash FROM session_summaries WHERE id=?",
            (summary["id"],),
        ).fetchone()
        assert private_row is not None
        source_set_hash = str(private_row["source_set_hash"])
        processing_fingerprint = str(
            connection.execute(
                "SELECT policy_fingerprint FROM summary_processing_consents "
                "WHERE scope_id='default'"
            ).fetchone()[0]
        )
        suppression = connection.execute(
            "SELECT rebuild_permit_id FROM summary_source_suppressions "
            "WHERE session_id=?",
            (source["id"],),
        ).fetchone()
        assert suppression is not None
        assert suppression["rebuild_permit_id"] == permit.permit_id

        for table in _METADATA_ONLY_TABLES:
            columns = {
                str(info[1])
                for info in connection.execute(f"PRAGMA table_info({table})")
            }
            assert not {
                "summary_text",
                "source_text",
                "prompt",
                "raw_response",
                "source_message_ids",
                "source_turn_ids",
            }.intersection(columns)
            persisted = "\n".join(
                str(value)
                for audit_row in connection.execute(f"SELECT * FROM {table}")
                for value in audit_row
            )
            assert source_text not in persisted
            assert deleted_payload not in persisted
            assert provider_raw not in persisted
            assert api_key not in persisted

    assert _FORBIDDEN_PUBLIC_KEYS.isdisjoint(_walk_keys(public_document))
    frontend_fixture = (
        root / "frontend" / "src" / "components" / "SummaryPanel.test.tsx"
    ).read_text(encoding="utf-8")
    review_surface = _review_surface(root)
    sensitive_values = (
        source_text,
        deleted_payload,
        provider_raw,
        api_key,
        hmac_key.hex(),
        hmac_digest,
        source_set_hash,
        processing_fingerprint,
        permit.permit_id,
        private_asset,
    )
    for value in sensitive_values:
        assert value not in public_api_json
        assert value not in caplog.text
        assert value not in frontend_fixture
        assert value not in review_surface


def test_gate_c2_frontend_contract_has_no_private_summary_identifiers() -> None:
    root = Path(__file__).resolve().parents[2]
    frontend = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            root / "frontend" / "src" / "api" / "types.ts",
            root / "frontend" / "src" / "api" / "client.ts",
            root / "frontend" / "src" / "components" / "SummaryPanel.tsx",
        )
    )
    for private_name in _FORBIDDEN_PUBLIC_KEYS:
        assert private_name not in frontend
    assert "type=\"file\"" not in frontend
    assert "accept=" not in frontend
