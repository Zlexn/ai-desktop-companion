import sqlite3
from pathlib import Path

import pytest

from scripts.verify_stage4e_e2e_database import VerificationError, main, verify_database
from tests.test_verify_stage4d_e2e_database import create_database


@pytest.mark.parametrize(
    "table_name",
    [
        "speaking_events",
        "playback_runs",
        "expression_events",
        "animation_states",
        "preview_states",
        "expression_cache",
    ],
)
def test_verify_database_rejects_runtime_presentation_tables(
    tmp_path: Path,
    table_name: str,
) -> None:
    path = tmp_path / "runtime-table.db"
    create_database(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute(f"CREATE TABLE {table_name} (id TEXT PRIMARY KEY)")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(VerificationError, match=table_name):
        verify_database(path)


@pytest.mark.parametrize(
    "column_name",
    [
        "display_label",
        "playback_run_id",
        "speaking_state",
        "prompt",
        "provider_payload",
        "asset_path",
    ],
)
def test_verify_database_rejects_runtime_or_private_expression_columns(
    tmp_path: Path,
    column_name: str,
) -> None:
    path = tmp_path / "runtime-column.db"
    create_database(path, forbidden_column=column_name)

    with pytest.raises(VerificationError, match=column_name):
        verify_database(path)


def test_verify_database_accepts_stage4d_database_without_runtime_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / "valid.db"
    create_database(path)
    verify_database(path)


def test_verify_database_rejects_missing_database(tmp_path: Path) -> None:
    with pytest.raises(VerificationError, match="does not exist"):
        verify_database(tmp_path / "missing.db")


def test_main_prints_pass_for_valid_database(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "valid.db"
    create_database(path)

    assert main(["--database", str(path)]) == 0
    assert capsys.readouterr().out.strip() == (
        "PASS: Stage 4E E2E database contains no persisted runtime presentation state"
    )


def test_main_prints_blocked_for_invalid_database(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "invalid.db"
    create_database(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE speaking_events (id TEXT PRIMARY KEY)")
        connection.commit()
    finally:
        connection.close()

    assert main(["--database", str(path)]) == 1
    assert capsys.readouterr().out.startswith("BLOCKED:")
