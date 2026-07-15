import sqlite3
from pathlib import Path

import pytest

from scripts.verify_stage4d_e2e_database import VerificationError, verify_database


BASE_COLUMNS = """
    id TEXT PRIMARY KEY,
    assistant_message_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    source_emotion_version INTEGER NOT NULL,
    delivery TEXT NOT NULL,
    rate REAL NOT NULL,
    intensity TEXT NOT NULL,
    created_at TEXT NOT NULL
"""


def create_database(
    path: Path,
    *,
    plan_rows: list[tuple[object, ...]] | None = None,
    message_role: str = "assistant",
    include_messages: bool = True,
    include_plans: bool = True,
    unique: bool = True,
    forbidden_column: str | None = None,
) -> None:
    connection = sqlite3.connect(path)
    try:
        if include_messages:
            connection.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, role TEXT NOT NULL)")
            connection.execute("INSERT INTO messages VALUES ('a1', ?)", (message_role,))
        if include_plans:
            columns = BASE_COLUMNS
            if forbidden_column:
                columns += f", {forbidden_column} TEXT"
            unique_sql = ", UNIQUE (assistant_message_id, schema_version)" if unique else ""
            connection.execute(f"CREATE TABLE expression_plans ({columns}{unique_sql})")
            rows = plan_rows if plan_rows is not None else [
                ("p1", "a1", 1, 3, "warm", 1.04, "medium", "2026-07-14T00:00:00+00:00")
            ]
            placeholders = ",".join("?" for _ in rows[0]) if rows else ""
            if rows:
                column_names = (
                    "id, assistant_message_id, schema_version, source_emotion_version, "
                    "delivery, rate, intensity, created_at"
                )
                connection.executemany(
                    f"INSERT INTO expression_plans ({column_names}) VALUES ({placeholders})",
                    rows,
                )
        connection.commit()
    finally:
        connection.close()


def test_verify_database_accepts_valid_expression_plans(tmp_path: Path) -> None:
    path = tmp_path / "valid.db"
    create_database(path)
    verify_database(path)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"include_plans": False}, "expression_plans table is missing"),
        ({"plan_rows": []}, "contains no plans"),
        ({"plan_rows": [("p1", "missing", 1, 0, "neutral", 1.0, "low", "now")]}, "orphan"),
        ({"message_role": "user"}, "non-assistant"),
        ({
            "unique": False,
            "plan_rows": [
                ("p1", "a1", 1, 0, "neutral", 1.0, "low", "now"),
                ("p2", "a1", 1, 1, "warm", 1.04, "medium", "later"),
            ],
        }, "duplicate"),
        ({"plan_rows": [("p1", "a1", 2, 0, "neutral", 1.0, "low", "now")]}, "schema version"),
        ({"plan_rows": [("p1", "a1", 1, -1, "neutral", 1.0, "low", "now")]}, "source version"),
        ({"plan_rows": [("p1", "a1", 1, 0, "unknown", 1.0, "low", "now")]}, "delivery"),
        ({"plan_rows": [("p1", "a1", 1, 0, "neutral", 1.11, "low", "now")]}, "rate"),
        ({"plan_rows": [("p1", "a1", 1, 0, "neutral", 1.0, "high", "now")]}, "intensity"),
        ({"forbidden_column": "text"}, "forbidden column"),
        ({"forbidden_column": "Content"}, "forbidden column"),
        ({"forbidden_column": "SSML"}, "forbidden column"),
    ],
)
def test_verify_database_rejects_invalid_persistence(
    tmp_path: Path,
    kwargs: dict[str, object],
    message: str,
) -> None:
    path = tmp_path / "invalid.db"
    create_database(path, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(VerificationError, match=message):
        verify_database(path)


def test_verify_database_rejects_missing_database(tmp_path: Path) -> None:
    with pytest.raises(VerificationError, match="does not exist"):
        verify_database(tmp_path / "missing.db")
