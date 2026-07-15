from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Sequence


class VerificationError(RuntimeError):
    pass


FORBIDDEN_COLUMNS = {
    "text",
    "content",
    "style",
    "ssml",
    "provider_options",
    "vendor_options",
    "emotion_vector",
}
VALID_DELIVERIES = {"neutral", "warm", "reassuring", "reserved", "firm"}
VALID_INTENSITIES = {"low", "medium"}


def verify_database(database_path: Path) -> None:
    if not database_path.is_file():
        raise VerificationError("Stage 4D E2E database does not exist")
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'expression_plans'"
        ).fetchone()
        if table is None:
            raise VerificationError("expression_plans table is missing")
        columns = {
            str(row[1]).lower()
            for row in connection.execute("PRAGMA table_info(expression_plans)")
        }
        forbidden = columns & FORBIDDEN_COLUMNS
        if forbidden:
            raise VerificationError(f"expression_plans has forbidden column: {sorted(forbidden)[0]}")
        rows = connection.execute(
            """
            SELECT p.assistant_message_id, p.schema_version, p.source_emotion_version,
                   p.delivery, p.rate, p.intensity, m.id, m.role
            FROM expression_plans AS p
            LEFT JOIN messages AS m ON m.id = p.assistant_message_id
            """
        ).fetchall()
        if not rows:
            raise VerificationError("expression_plans contains no plans")
        duplicate = connection.execute(
            """
            SELECT assistant_message_id, schema_version, COUNT(*)
            FROM expression_plans
            GROUP BY assistant_message_id, schema_version
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        ).fetchone()
        if duplicate is not None:
            raise VerificationError("duplicate message/schema expression plans found")
        for row in rows:
            message_id, schema_version, source_version, delivery, rate, intensity, joined_id, role = row
            if joined_id is None:
                raise VerificationError(f"orphan expression plan for {message_id}")
            if role != "assistant":
                raise VerificationError("expression plan has non-assistant message relation")
            if type(schema_version) is not int or schema_version != 1:
                raise VerificationError("invalid expression plan schema version")
            if type(source_version) is not int or source_version < 0:
                raise VerificationError("invalid expression plan source version")
            if delivery not in VALID_DELIVERIES:
                raise VerificationError("invalid expression delivery")
            if type(rate) not in {int, float} or not 0.90 <= rate <= 1.10:
                raise VerificationError("invalid expression rate")
            if intensity not in VALID_INTENSITIES:
                raise VerificationError("invalid expression intensity")
    except sqlite3.Error as exc:
        raise VerificationError("unable to inspect Stage 4D E2E expression plans") from exc
    finally:
        connection.close()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Stage 4D E2E expression plans.")
    parser.add_argument("--database", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        verify_database(args.database)
    except VerificationError as exc:
        print(f"BLOCKED: {exc}")
        return 1
    print("PASS: Stage 4D E2E expression plans satisfy persistence invariants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
