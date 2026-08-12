from __future__ import annotations

from datetime import UTC, datetime, timedelta
import threading

from fastapi.testclient import TestClient

from app.api.dependencies import get_memory_automation_repository
from app.core.config import get_settings
from app.domain.models import MemoryWriteConsent, MemoryWriteConsentStatus
from app.repositories.sqlite import managed_connection
from app.services.memory_gate_b_contract import (
    MEMORY_ALLOWED_AUTO_TYPES,
    MEMORY_ALLOWED_AUTO_TYPES_VERSION,
    MEMORY_WRITE_POLICY_VERSION,
    MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
)


_NOW = datetime(2026, 7, 21, tzinfo=UTC)


def _create_memory(client: TestClient, content: str = "用户喜欢红茶。") -> dict:
    response = client.post(
        "/api/memories",
        json={
            "content": content,
            "memory_type": "preference",
            "importance": 3,
            "confidence": 1.0,
        },
    )
    assert response.status_code == 201
    return response.json()["memory"]


def _write_consent_payload(action: str) -> dict:
    return {
        "action": action,
        "policy_version": MEMORY_WRITE_POLICY_VERSION,
        "retention_disclosure_version": MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
        "allowed_memory_types_version": MEMORY_ALLOWED_AUTO_TYPES_VERSION,
        "allowed_memory_types": [item.value for item in MEMORY_ALLOWED_AUTO_TYPES],
    }


def _seed_conflicts(count: int, *, status: str = "open") -> None:
    settings = get_settings()
    with managed_connection(settings.database_url) as connection:
        for index in range(count):
            created_at = (_NOW + timedelta(seconds=index)).isoformat()
            left = f"page-left-{status}-{index:03d}"
            right = f"page-right-{status}-{index:03d}"
            for memory_id in (left, right):
                connection.execute(
                    "INSERT INTO memories "
                    "(id, content, memory_type, source, source_session_id, importance, "
                    " confidence, status, metadata_json, created_at, updated_at) "
                    "VALUES (?, 'payload', 'preference', 'manual', NULL, 3, 1.0, "
                    "        'active', '{}', ?, ?)",
                    (memory_id, created_at, created_at),
                )
            connection.execute(
                "INSERT INTO memory_conflicts "
                "(conflict_id, left_memory_id, right_memory_id, status, resolution_kind, "
                " resolved_memory_id, created_at, resolved_at) "
                "VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
                (
                    f"page-conflict-{status}-{index:03d}",
                    left,
                    right,
                    status,
                    "dismiss_both" if status == "resolved" else None,
                    created_at,
                    created_at if status == "resolved" else None,
                ),
            )
        connection.commit()


def test_write_consent_is_independent_and_generation_advances(client: TestClient) -> None:
    initial = client.get("/api/memories/automation/write-consent")
    assert initial.status_code == 200
    initial_body = initial.json()
    assert initial_body["status"] == "unknown"
    assert initial_body["generation"] == 0

    for generation, action, expected in (
        (1, "grant", "granted"),
        (2, "decline", "declined"),
        (3, "revoke", "revoked"),
    ):
        response = client.put(
            "/api/memories/automation/write-consent",
            json=_write_consent_payload(action),
        )
        assert response.status_code == 200
        assert response.json()["status"] == expected
        assert response.json()["generation"] == generation

    remote = client.get("/api/memories/extraction/consent").json()
    assert remote["status"] == "unknown"
    assert client.get("/api/memories").json() == []


def test_write_consent_requires_exact_frozen_disclosure(client: TestClient) -> None:
    payload = _write_consent_payload("grant")
    payload["allowed_memory_types"] = list(reversed(payload["allowed_memory_types"]))
    assert client.put(
        "/api/memories/automation/write-consent", json=payload
    ).status_code == 422


def test_write_consent_route_registers_pending_mutation_before_repository_write(
    client: TestClient,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    observed_pending: list[bool] = []
    now = datetime.now(UTC)

    class BlockingAutomation:
        def set_write_consent(self, **_kwargs) -> MemoryWriteConsent:
            observed_pending.append(
                client.app.state.memory_write_dispatch_fence.has_pending_write_consent_mutation()
            )
            entered.set()
            assert release.wait(timeout=2)
            return MemoryWriteConsent(
                scope_id="default",
                status=MemoryWriteConsentStatus.REVOKED,
                purpose="write Governor-approved durable memories to local active storage",
                policy_version=MEMORY_WRITE_POLICY_VERSION,
                retention_disclosure_version=MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
                allowed_memory_types_version=MEMORY_ALLOWED_AUTO_TYPES_VERSION,
                allowed_memory_types=MEMORY_ALLOWED_AUTO_TYPES,
                generation=1,
                granted_at=None,
                created_at=now,
                updated_at=now,
            )

    client.app.dependency_overrides[get_memory_automation_repository] = BlockingAutomation
    result: dict[str, object] = {}

    def request() -> None:
        result["response"] = client.put(
            "/api/memories/automation/write-consent",
            json=_write_consent_payload("revoke"),
        )

    thread = threading.Thread(target=request)
    try:
        thread.start()
        assert entered.wait(timeout=2)
        assert client.app.state.memory_write_dispatch_fence.has_pending_write_consent_mutation()
        release.set()
        thread.join(timeout=2)
        assert not thread.is_alive()
    finally:
        release.set()
        thread.join(timeout=2)
        client.app.dependency_overrides.clear()

    assert observed_pending == [True]
    assert result["response"].status_code == 200
    assert not client.app.state.memory_write_dispatch_fence.has_pending_write_consent_mutation()


def test_history_and_evidence_responses_hide_internal_hashes(client: TestClient) -> None:
    memory = _create_memory(client)
    versions = client.get(f"/api/memories/{memory['id']}/versions")
    evidence = client.get(f"/api/memories/{memory['id']}/evidence")
    assert versions.status_code == evidence.status_code == 200
    assert versions.json()["items"]
    forbidden = {
        "canonical_key_hash",
        "subject_key_hash",
        "canonical_hash",
        "source_session_reference_hash",
        "source_message_reference_hash",
        "content_hash",
        "raw_response",
        "prompt",
        "hidden_reasoning",
    }
    summary = client.get("/api/memories").json()[0]
    assert forbidden.isdisjoint(summary)
    assert forbidden.isdisjoint(versions.json()["items"][0])
    assert evidence.json()["items"] == []


def test_history_cursor_is_bound_to_memory(client: TestClient) -> None:
    first = _create_memory(client, "用户喜欢红茶。")
    second = _create_memory(client, "用户喜欢咖啡。")
    for index in range(2):
        response = client.patch(
            f"/api/memories/{first['id']}",
            json={"content": f"用户喜欢第 {index} 种茶。"},
        )
        assert response.status_code == 200
    page = client.get(
        f"/api/memories/{first['id']}/versions", params={"limit": 1}
    ).json()
    assert page["next_cursor"]
    mismatch = client.get(
        f"/api/memories/{second['id']}/versions",
        params={"limit": 1, "cursor": page["next_cursor"]},
    )
    assert mismatch.status_code == 400
    assert client.get(
        f"/api/memories/{first['id']}/versions", params={"cursor": "not-a-cursor"}
    ).status_code == 400


def test_101_versions_and_evidence_traverse_without_gaps(client: TestClient) -> None:
    memory = _create_memory(client, "用户喜欢初始饮品。")
    for index in range(100):
        response = client.patch(
            f"/api/memories/{memory['id']}",
            json={"content": f"用户喜欢饮品 {index:03d}。"},
        )
        assert response.status_code == 200

    settings = get_settings()
    with managed_connection(settings.database_url) as connection:
        current_version_id = connection.execute(
            "SELECT current_version_id FROM memory_record_states WHERE memory_id = ?",
            (memory["id"],),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) "
            "VALUES ('evidence-session', 'evidence', ?, ?)",
            (_NOW.isoformat(), _NOW.isoformat()),
        )
        for index in range(101):
            observed = (_NOW + timedelta(seconds=index)).isoformat()
            message_id = f"evidence-message-{index:03d}"
            connection.execute(
                "INSERT INTO messages "
                "(id, session_id, role, content, metadata_json, created_at) "
                "VALUES (?, 'evidence-session', 'user', 'source', '{}', ?)",
                (message_id, observed),
            )
            connection.execute(
                "INSERT INTO memory_evidence "
                "(evidence_id, memory_id, memory_version_id, source_session_id, "
                " source_message_id, source_session_reference_hash, "
                " source_message_reference_hash, source_available, source_deleted_at, "
                " relation, observed_at, extractor_kind, extractor_provider, "
                " extractor_model, confidence, created_at) "
                "VALUES (?, ?, ?, 'evidence-session', ?, ?, ?, 1, NULL, "
                "        'supports', ?, 'local', NULL, 'fixture', 1.0, ?)",
                (
                    f"evidence-{index:03d}",
                    memory["id"],
                    current_version_id,
                    message_id,
                    f"session-hash-{index:03d}",
                    f"message-hash-{index:03d}",
                    observed,
                    observed,
                ),
            )
        connection.commit()

    summary = client.get("/api/memories").json()[0]
    assert summary["v2_state"] == "active"
    assert summary["v2_source_kind"] == "user_edit"
    assert summary["version_count"] == 101
    assert summary["evidence_count"] == 101
    assert summary["has_open_conflict"] is False

    for suffix in ("versions", "evidence"):
        seen: list[str] = []
        cursor = None
        while True:
            params = {"limit": 13}
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get(
                f"/api/memories/{memory['id']}/{suffix}", params=params
            )
            assert response.status_code == 200
            page = response.json()
            seen.extend(item["id"] for item in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert len(seen) == len(set(seen)) == 101


def test_101_conflicts_traverse_without_gaps_and_cursor_binds_status(
    client: TestClient,
) -> None:
    _seed_conflicts(101)
    seen: list[str] = []
    cursor = None
    while True:
        params = {"status": "open", "limit": 17}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get("/api/memories/conflicts", params=params)
        assert response.status_code == 200
        page = response.json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 101

    _seed_conflicts(1, status="resolved")
    first_page = client.get(
        "/api/memories/conflicts", params={"status": "open", "limit": 1}
    ).json()
    mismatch = client.get(
        "/api/memories/conflicts",
        params={
            "status": "resolved",
            "limit": 1,
            "cursor": first_page["next_cursor"],
        },
    )
    assert mismatch.status_code == 400


def test_conflict_resolution_schema_is_strict_and_contextual_requires_context(
    client: TestClient,
) -> None:
    invalid_extra = client.post(
        "/api/memories/conflicts/unknown/resolve",
        json={"kind": "choose_left", "content": "不能出现"},
    )
    assert invalid_extra.status_code == 422
    invalid_context = client.post(
        "/api/memories/conflicts/unknown/resolve",
        json={
            "kind": "both_contextual",
            "content": "用户喜欢红茶",
            "subject": "饮品偏好",
            "memory_type": "preference",
        },
    )
    assert invalid_context.status_code in {404, 422}


def test_memory_summary_uses_authoritative_v2_source_and_open_conflict(
    client: TestClient,
) -> None:
    left = _create_memory(client, "用户喜欢红茶。")
    right = _create_memory(client, "用户不喜欢红茶。")
    settings = get_settings()
    with managed_connection(settings.database_url) as connection:
        connection.execute(
            "UPDATE memory_record_states SET source_kind = 'automatic' WHERE memory_id = ?",
            (left["id"],),
        )
        ordered = sorted((left["id"], right["id"]))
        connection.execute(
            "INSERT INTO memory_conflicts "
            "(conflict_id, left_memory_id, right_memory_id, status, resolution_kind, "
            " resolved_memory_id, created_at, resolved_at) "
            "VALUES ('summary-conflict', ?, ?, 'open', NULL, NULL, ?, NULL)",
            (*ordered, _NOW.isoformat()),
        )
        connection.commit()

    summaries = {
        item["id"]: item for item in client.get("/api/memories").json()
    }
    assert summaries[left["id"]]["source"] == "manual"
    assert summaries[left["id"]]["v2_source_kind"] == "automatic"
    assert summaries[left["id"]]["has_open_conflict"] is True
    assert summaries[right["id"]]["has_open_conflict"] is True


def test_archive_legacy_delete_and_true_forget_are_distinct(client: TestClient) -> None:
    explicit = _create_memory(client, "用户喜欢显式归档。")
    assert client.post(f"/api/memories/{explicit['id']}/archive").status_code == 204
    settings = get_settings()
    with managed_connection(settings.database_url) as connection:
        row = connection.execute(
            "SELECT content, status FROM memories WHERE id = ?", (explicit["id"],)
        ).fetchone()
        assert row["status"] == "archived"
        assert row["content"] == "用户喜欢显式归档。"

    legacy = _create_memory(client, "用户喜欢兼容归档。")
    assert client.delete(f"/api/memories/{legacy['id']}").status_code == 204

    forgotten = _create_memory(client, "SENTINEL_TRUE_FORGET")
    response = client.post(f"/api/memories/{forgotten['id']}/forget")
    assert response.status_code == 200
    history = client.get(f"/api/memories/{forgotten['id']}/versions").json()
    assert "SENTINEL_TRUE_FORGET" not in str(history)
    assert all(item["content"] is None for item in history["items"])


def test_scoped_forget_schema_is_strict(client: TestClient) -> None:
    assert client.post(
        "/api/memories/forget", json={"scope": "all", "scope_id": "x"}
    ).status_code == 422
    assert client.post(
        "/api/memories/forget", json={"scope": "session"}
    ).status_code == 422
    assert client.post(
        "/api/memories/forget",
        json={"scope": "memory_type", "scope_id": "invalid"},
    ).status_code == 422
