from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.repositories.memory_embeddings import MemoryEmbeddingRepository
from app.repositories.sqlite import managed_connection


def test_gate_c3_memory_openapi_exposes_explicit_classification_contract(
    client: TestClient,
) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    subject_enum = (
        "preferred_address",
        "shared_experience",
        "non_external_commitment",
    )

    for schema_name in (
        "CreateMemoryRequest",
        "UpdateMemoryRequest",
        "ConfirmMemoryCandidateRequest",
        "ReplaceConflictRequest",
        "MemoryResponse",
        "MemoryVersionResponse",
    ):
        document = str(schemas[schema_name])
        assert "canonical_subject_code" in document
        for value in subject_enum:
            assert value in document
    assert set(
        schemas["ConfirmMemoryCandidateRequest"]["properties"]
    ) == {"canonical_subject_code"}


def test_gate_c3_memory_contract_rejects_invalid_classification_pairs(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/memories",
        json={
            "content": "错误分类",
            "memory_type": "preference",
            "canonical_subject_code": "shared_experience",
        },
    )

    assert response.status_code == 422


def test_gate_c3_manual_classification_lifecycle_is_visible_in_current_api(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/memories",
        json={
            "content": "小雪",
            "memory_type": "preference",
            "canonical_subject_code": "preferred_address",
        },
    )
    assert created.status_code == 201
    memory = created.json()["memory"]
    assert memory["canonical_subject_code"] == "preferred_address"
    assert client.get("/api/memories").json()[0]["canonical_subject_code"] == (
        "preferred_address"
    )

    preserved = client.patch(
        f"/api/memories/{memory['id']}",
        json={"importance": 4},
    )
    assert preserved.status_code == 200
    assert preserved.json()["memory"]["canonical_subject_code"] == (
        "preferred_address"
    )

    cleared = client.patch(
        f"/api/memories/{memory['id']}",
        json={"content": "普通偏好", "canonical_subject_code": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["memory"]["canonical_subject_code"] is None

    versions = client.get(f"/api/memories/{memory['id']}/versions").json()["items"]
    assert [version["canonical_subject_code"] for version in versions] == [
        None,
        "preferred_address",
        "preferred_address",
    ]


def test_gate_c3_candidate_confirm_persists_only_explicit_classification(
    client: TestClient,
) -> None:
    settings = get_settings()
    with managed_connection(settings.database_url) as connection:
        from app.domain.models import MemoryType
        from app.repositories.memories import MemoryRepository

        first, _ = MemoryRepository(connection).create_candidate(
            content="小雪",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.9,
        )
        second, _ = MemoryRepository(connection).create_candidate(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.9,
        )
    assert first is not None and second is not None

    classified = client.post(
        f"/api/memories/{first.id}/confirm",
        json={"canonical_subject_code": "preferred_address"},
    )
    assert classified.status_code == 200
    assert classified.json()["memory"]["canonical_subject_code"] == (
        "preferred_address"
    )

    uncoded = client.post(f"/api/memories/{second.id}/confirm")
    assert uncoded.status_code == 200
    assert uncoded.json()["memory"]["canonical_subject_code"] is None


def test_create_list_update_and_delete_memory_api(client: TestClient) -> None:
    create_response = client.post(
        "/api/memories",
        json={
            "content": "用户偏好中文回复。",
            "memory_type": "preference",
            "importance": 3,
            "confidence": 1.0,
        },
    )
    assert create_response.status_code == 201
    created_body = create_response.json()
    memory = created_body["memory"]
    assert created_body["conflicts"] == []
    assert memory["content"] == "用户偏好中文回复。"
    assert memory["source"] == "manual"
    assert memory["status"] == "active"
    assert memory["v2_state"] == "active"
    assert memory["v2_source_kind"] == "manual"
    assert memory["version_count"] == 1
    assert memory["evidence_count"] == 0
    assert memory["has_open_conflict"] is False
    assert memory["can_undo_latest_auto"] is False

    list_response = client.get("/api/memories")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [memory["id"]]
    assert list_response.json()[0]["v2_source_kind"] == "manual"
    assert list_response.json()[0]["version_count"] == 1

    update_response = client.patch(
        f"/api/memories/{memory['id']}",
        json={"content": "用户偏好简洁中文回复。", "importance": 4, "confidence": 0.9},
    )
    assert update_response.status_code == 200
    updated = update_response.json()["memory"]
    assert updated["content"] == "用户偏好简洁中文回复。"
    assert updated["importance"] == 4
    assert updated["confidence"] == 0.9
    assert updated["v2_state"] == "active"
    assert updated["v2_source_kind"] == "user_edit"
    assert updated["version_count"] == 2
    assert updated["evidence_count"] == 0
    assert updated["has_open_conflict"] is False
    assert updated["can_undo_latest_auto"] is False

    delete_response = client.delete(f"/api/memories/{memory['id']}")
    assert delete_response.status_code == 204
    assert client.get("/api/memories").json() == []


def test_delete_conflicted_memory_requires_resolution(client: TestClient) -> None:
    created = client.post(
        "/api/memories",
        json={
            "content": "用户喜欢雪。",
            "memory_type": "preference",
            "importance": 3,
            "confidence": 1.0,
        },
    ).json()["memory"]
    settings = get_settings()
    with managed_connection(settings.database_url) as connection:
        connection.execute(
            "UPDATE memory_record_states SET state = 'conflicted' WHERE memory_id = ?",
            (created["id"],),
        )
        connection.commit()

    response = client.delete(f"/api/memories/{created['id']}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict_requires_resolution"


def test_patch_conflicted_memory_requires_resolution(client: TestClient) -> None:
    created = client.post(
        "/api/memories",
        json={
            "content": "用户喜欢雪。",
            "memory_type": "preference",
            "importance": 3,
            "confidence": 1.0,
        },
    ).json()["memory"]
    settings = get_settings()
    with managed_connection(settings.database_url) as connection:
        connection.execute(
            "UPDATE memory_record_states SET state = 'conflicted' WHERE memory_id = ?",
            (created["id"],),
        )
        connection.commit()

    response = client.patch(
        f"/api/memories/{created['id']}",
        json={"content": "用户喜欢冰雪。"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict_requires_resolution"


def test_memory_api_rejects_invalid_fields(client: TestClient) -> None:
    response = client.post(
        "/api/memories",
        json={"content": "x", "memory_type": "preference", "importance": 6, "confidence": 1.0},
    )

    assert response.status_code == 422


def test_memory_api_rejects_missing_source_session(client: TestClient) -> None:
    response = client.post(
        "/api/memories",
        json={
            "content": "来自不存在会话的记忆。",
            "memory_type": "important_event",
            "source_session_id": "missing",
            "importance": 3,
            "confidence": 1.0,
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "会话不存在。"


def test_duplicate_memory_api_returns_conflicts_without_overwriting(client: TestClient) -> None:
    first = client.post(
        "/api/memories",
        json={"content": "用户喜欢雪。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    ).json()["memory"]

    second_response = client.post(
        "/api/memories",
        json={"content": " 用户喜欢雪。 ", "memory_type": "preference", "importance": 2, "confidence": 0.8},
    )

    assert second_response.status_code == 201
    second_body = second_response.json()
    assert [item["id"] for item in second_body["conflicts"]] == [first["id"]]
    assert len(client.get("/api/memories").json()) == 2


def test_duplicate_memory_api_records_conflict_audit_event(client: TestClient) -> None:
    first = client.post(
        "/api/memories",
        json={"content": "用户喜欢雪。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    ).json()["memory"]

    second = client.post(
        "/api/memories",
        json={"content": " 用户喜欢雪。 ", "memory_type": "preference", "importance": 2, "confidence": 0.8},
    ).json()["memory"]

    audit_response = client.get("/api/memories/audit-events")

    assert audit_response.status_code == 200
    events = audit_response.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "conflict_detected"
    assert events[0]["operation"] == "create"
    assert events[0]["memory_id"] == second["id"]
    assert events[0]["related_memory_ids"] == [first["id"]]


def test_semantic_memory_conflict_api_records_audit_event(client: TestClient) -> None:
    first = client.post(
        "/api/memories",
        json={"content": "用户喜欢红茶。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    ).json()["memory"]

    second_response = client.post(
        "/api/memories",
        json={"content": "用户不喜欢红茶。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    )

    assert second_response.status_code == 201
    second_body = second_response.json()
    assert [item["id"] for item in second_body["conflicts"]] == [first["id"]]
    events = client.get("/api/memories/audit-events").json()
    assert len(events) == 1
    assert events[0]["operation"] == "create"
    assert events[0]["memory_id"] == second_body["memory"]["id"]
    assert events[0]["related_memory_ids"] == [first["id"]]


def test_non_conflicting_same_type_memory_api_does_not_record_audit_event(client: TestClient) -> None:
    client.post(
        "/api/memories",
        json={"content": "用户喜欢红茶。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    )

    second_response = client.post(
        "/api/memories",
        json={"content": "用户喜欢咖啡。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    )

    assert second_response.status_code == 201
    assert second_response.json()["conflicts"] == []
    assert client.get("/api/memories/audit-events").json() == []


def test_non_conflicting_memory_api_does_not_record_audit_event(client: TestClient) -> None:
    client.post(
        "/api/memories",
        json={"content": "用户喜欢雪。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    )

    audit_response = client.get("/api/memories/audit-events")

    assert audit_response.status_code == 200
    assert audit_response.json() == []


def test_update_memory_api_records_conflict_audit_event(client: TestClient) -> None:
    first = client.post(
        "/api/memories",
        json={"content": "用户喜欢雪。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    ).json()["memory"]
    second = client.post(
        "/api/memories",
        json={"content": "用户喜欢雨。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    ).json()["memory"]

    update_response = client.patch(
        f"/api/memories/{second['id']}",
        json={"content": " 用户喜欢雪。 "},
    )

    assert update_response.status_code == 200
    assert [item["id"] for item in update_response.json()["conflicts"]] == [first["id"]]
    events = client.get("/api/memories/audit-events").json()
    assert len(events) == 1
    assert events[0]["operation"] == "update"
    assert events[0]["memory_id"] == second["id"]
    assert events[0]["related_memory_ids"] == [first["id"]]


def test_confirm_candidate_conflict_records_audit_event_and_keeps_candidate_pending(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "候选冲突"}).json()
    client.post(f"/api/sessions/{session['id']}/messages", json={"content": "我喜欢红茶。"})
    candidate = client.get("/api/memories", params={"status_filter": "pending"}).json()[0]
    active = client.post(
        "/api/memories",
        json={"content": "用户喜欢红茶。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    ).json()["memory"]

    confirm_response = client.post(f"/api/memories/{candidate['id']}/confirm")

    assert confirm_response.status_code == 200
    confirm_body = confirm_response.json()
    assert confirm_body["memory"]["status"] == "pending"
    assert [item["id"] for item in confirm_body["conflicts"]] == [active["id"]]
    events = client.get("/api/memories/audit-events").json()
    assert len(events) == 1
    assert events[0]["operation"] == "confirm_candidate"
    assert events[0]["memory_id"] == candidate["id"]
    assert events[0]["related_memory_ids"] == [active["id"]]


def test_memory_audit_events_limit_is_bounded(client: TestClient) -> None:
    too_large = client.get("/api/memories/audit-events", params={"limit": 101})
    too_small = client.get("/api/memories/audit-events", params={"limit": 0})

    assert too_large.status_code == 422
    assert too_small.status_code == 422


def test_memory_api_lists_confirms_and_dismisses_candidates(client: TestClient) -> None:
    session = client.post("/api/sessions", json={"title": "候选 API"}).json()
    client.post(f"/api/sessions/{session['id']}/messages", json={"content": "我喜欢红茶。"})

    pending_response = client.get("/api/memories", params={"status_filter": "pending"})
    assert pending_response.status_code == 200
    pending = pending_response.json()
    assert len(pending) == 1
    candidate = pending[0]
    assert candidate["status"] == "pending"

    confirm_response = client.post(f"/api/memories/{candidate['id']}/confirm")
    assert confirm_response.status_code == 200
    confirm_body = confirm_response.json()
    assert confirm_body["conflicts"] == []
    confirmed = confirm_body["memory"]
    assert confirmed["status"] == "active"
    assert confirmed["source"] == "candidate"
    assert "confirmed_at" in confirmed["metadata"]
    assert client.get("/api/memories", params={"status_filter": "pending"}).json() == []
    assert [item["id"] for item in client.get("/api/memories").json()] == [candidate["id"]]

    client.post(f"/api/sessions/{session['id']}/messages", json={"content": "我不喜欢咖啡。"})
    next_candidate = client.get("/api/memories", params={"status_filter": "pending"}).json()[0]
    dismiss_response = client.post(f"/api/memories/{next_candidate['id']}/dismiss")
    assert dismiss_response.status_code == 200
    dismissed = dismiss_response.json()
    assert dismissed["status"] == "dismissed"
    assert "dismissed_at" in dismissed["metadata"]
    assert client.get("/api/memories", params={"status_filter": "pending"}).json() == []


def test_memory_api_rejects_confirming_active_memory(client: TestClient) -> None:
    created = client.post(
        "/api/memories",
        json={"content": "用户喜欢雪。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
    ).json()["memory"]

    response = client.post(f"/api/memories/{created['id']}/confirm")

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "只能确认待确认记忆。"


def test_memory_api_create_update_and_delete_maintains_embeddings(tmp_path, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.main import create_app

    database_url = f"sqlite:///{tmp_path / 'api-embedding.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("MEMORY_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("MEMORY_RETRIEVAL_MODE", "embedding")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/api/memories",
            json={"content": "用户喜欢红茶。", "memory_type": "preference", "importance": 3, "confidence": 1.0},
        ).json()["memory"]
        with managed_connection(database_url) as connection:
            embeddings = MemoryEmbeddingRepository(connection)
            first_embedding = embeddings.get(created["id"])
            assert first_embedding is not None
            first_hash = first_embedding.content_hash

        updated = client.patch(f"/api/memories/{created['id']}", json={"content": "用户喜欢咖啡。"}).json()["memory"]
        assert updated["content"] == "用户喜欢咖啡。"
        with managed_connection(database_url) as connection:
            embeddings = MemoryEmbeddingRepository(connection)
            refreshed_embedding = embeddings.get(created["id"])
            assert refreshed_embedding is not None
            assert refreshed_embedding.content_hash != first_hash

        delete_response = client.delete(f"/api/memories/{created['id']}")
        assert delete_response.status_code == 204
        with managed_connection(database_url) as connection:
            embeddings = MemoryEmbeddingRepository(connection)
            assert embeddings.get(created["id"]) is None
    get_settings.cache_clear()


def test_confirm_candidate_creates_embedding_when_enabled(tmp_path, monkeypatch) -> None:
    from app.core.config import get_settings
    from app.main import create_app

    database_url = f"sqlite:///{tmp_path / 'api-confirm-embedding.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("MEMORY_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("MEMORY_RETRIEVAL_MODE", "embedding")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"title": "候选嵌入"}).json()
        client.post(f"/api/sessions/{session['id']}/messages", json={"content": "我喜欢红茶。"})
        candidate = client.get("/api/memories", params={"status_filter": "pending"}).json()[0]
        with managed_connection(database_url) as connection:
            embeddings = MemoryEmbeddingRepository(connection)
            assert embeddings.get(candidate["id"]) is None

        confirm_response = client.post(f"/api/memories/{candidate['id']}/confirm")

        assert confirm_response.status_code == 200
        assert confirm_response.json()["memory"]["status"] == "active"
        with managed_connection(database_url) as connection:
            embeddings = MemoryEmbeddingRepository(connection)
            assert embeddings.get(candidate["id"]) is not None
    get_settings.cache_clear()
