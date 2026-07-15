from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.verify_stage4d_e2e_database import (
    VerificationError as Stage4DVerificationError,
    verify_database as verify_stage4d_database,
)


class VerificationError(RuntimeError):
    pass


FORBIDDEN_TABLES = {
    "speaking_events",
    "playback_runs",
    "expression_events",
    "animation_states",
    "preview_states",
    "expression_cache",
}
FORBIDDEN_EXPRESSION_COLUMNS = {
    "display_label",
    "playback_run_id",
    "speaking_state",
    "prompt",
    "provider_payload",
    "asset_path",
}


def verify_database(database_path: Path) -> None:
    if not database_path.is_file():
        raise VerificationError("Stage 4E E2E database does not exist")
    try:
        verify_stage4d_database(database_path)
    except Stage4DVerificationError as exc:
        raise VerificationError(str(exc)) from exc

    try:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise VerificationError("unable to open Stage 4E E2E database read-only") from exc
    try:
        tables = {
            str(row[0]).lower()
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        forbidden_tables = tables & FORBIDDEN_TABLES
        if forbidden_tables:
            raise VerificationError(
                f"database has forbidden runtime presentation table: {sorted(forbidden_tables)[0]}"
            )

        columns = {
            str(row[1]).lower()
            for row in connection.execute("PRAGMA table_info(expression_plans)")
        }
        forbidden_columns = columns & FORBIDDEN_EXPRESSION_COLUMNS
        if forbidden_columns:
            raise VerificationError(
                f"expression_plans has forbidden runtime or private column: {sorted(forbidden_columns)[0]}"
            )
    except sqlite3.Error as exc:
        raise VerificationError("unable to inspect Stage 4E E2E database") from exc
    finally:
        connection.close()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify Stage 4E E2E runtime presentation persistence invariants."
    )
    parser.add_argument("--database", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        verify_database(args.database)
    except VerificationError as exc:
        print(f"BLOCKED: {exc}")
        return 1
    print("PASS: Stage 4E E2E database contains no persisted runtime presentation state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
