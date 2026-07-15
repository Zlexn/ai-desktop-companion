import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_expression_query_service, get_read_only_connection
from app.core.config import get_settings


def create_chat(client: TestClient) -> tuple[str, str]:
    session = client.post("/api/sessions", json={"title": "expression"}).json()
    chat = client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "hello"},
    ).json()
    messages = client.get(f"/api/sessions/{session['id']}/messages").json()
    user_id = next(item["id"] for item in messages if item["role"] == "user")
    return user_id, chat["assistant_message_id"]


def api_database_path(tmp_path: Path) -> Path:
    return tmp_path / "api.db"


def database_snapshot(database_path: Path) -> dict[str, tuple[tuple[object, ...], ...]]:
    with sqlite3.connect(database_path) as connection:
        table_names = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        )
        return {
            table: tuple(
                tuple(row)
                for row in connection.execute(
                    f'SELECT rowid, * FROM "{table}" ORDER BY rowid'
                )
            )
            for table in table_names
        }


def test_read_only_connection_rejects_writes(client: TestClient) -> None:
    generator = get_read_only_connection(get_settings())
    connection = next(generator)
    try:
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("CREATE TABLE forbidden_write (id TEXT)")
        with pytest.raises(sqlite3.OperationalError):
            connection.execute(
                "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                ("forbidden", "write", "now", "now"),
            )
    finally:
        generator.close()


def test_expression_get_returns_minimal_persisted_plan(client: TestClient) -> None:
    _, assistant_id = create_chat(client)

    response = client.get(f"/api/messages/{assistant_id}/expression")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "assistant_message_id",
        "schema_version",
        "delivery",
        "intensity",
        "rate",
        "source",
    }
    assert body["assistant_message_id"] == assistant_id
    assert body["schema_version"] == 1
    assert body["delivery"] in {"neutral", "warm", "reassuring", "reserved", "firm"}
    assert body["intensity"] in {"low", "medium"}
    assert 0.90 <= body["rate"] <= 1.10
    assert body["source"] == "persisted_plan"


def test_expression_get_returns_default_for_history_without_plan(
    client: TestClient,
    tmp_path: Path,
) -> None:
    _, assistant_id = create_chat(client)
    database_path = api_database_path(tmp_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "DELETE FROM expression_plans WHERE assistant_message_id = ?",
            (assistant_id,),
        )
        connection.commit()
    before = database_snapshot(database_path)

    first = client.get(f"/api/messages/{assistant_id}/expression")
    second = client.get(f"/api/messages/{assistant_id}/expression")

    expected = {
        "assistant_message_id": assistant_id,
        "schema_version": 1,
        "delivery": "neutral",
        "intensity": "low",
        "rate": 1.0,
        "source": "default",
    }
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == expected
    assert database_snapshot(database_path) == before
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM expression_plans WHERE assistant_message_id = ?",
            (assistant_id,),
        ).fetchone()[0] == 0


def test_expression_get_has_explicit_404_and_422(client: TestClient) -> None:
    user_id, _ = create_chat(client)

    missing = client.get("/api/messages/missing/expression")
    wrong_role = client.get(f"/api/messages/{user_id}/expression")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert wrong_role.status_code == 422
    assert wrong_role.json()["error"]["code"] == "expression_message_not_assistant"


def test_expression_get_ignores_injected_query_parameters(client: TestClient) -> None:
    _, assistant_id = create_chat(client)
    original = client.get(f"/api/messages/{assistant_id}/expression").json()

    injected = client.get(
        f"/api/messages/{assistant_id}/expression",
        params={
            "delivery": "firm",
            "intensity": "medium",
            "rate": "1.1",
            "ssml": "<break/>",
        },
    )

    assert injected.status_code == 200
    assert injected.json() == original


def test_expression_get_does_not_change_any_application_table(
    client: TestClient,
    tmp_path: Path,
) -> None:
    _, assistant_id = create_chat(client)
    database_path = api_database_path(tmp_path)
    before = database_snapshot(database_path)

    assert client.get(f"/api/messages/{assistant_id}/expression").status_code == 200
    assert client.get(f"/api/messages/{assistant_id}/expression").status_code == 200

    assert database_snapshot(database_path) == before


def test_expression_get_sanitizes_unexpected_infrastructure_error(client: TestClient) -> None:
    class BrokenService:
        def get_for_assistant_message(self, _message_id: str):
            raise sqlite3.OperationalError("private database detail")

    client.app.dependency_overrides[get_expression_query_service] = lambda: BrokenService()
    try:
        response = client.get("/api/messages/assistant-1/expression")
    finally:
        client.app.dependency_overrides.pop(get_expression_query_service, None)

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "请求处理失败，请稍后重试。",
        }
    }
    assert "private database detail" not in response.text
