from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Sequence

ANALYSIS_TABLES = ("emotion_analysis_jobs", "emotion_analysis_audits")


class VerificationError(RuntimeError):
    pass


def verify_database(
    database_path: Path,
    *,
    forbidden_markers: tuple[str, ...],
    expected_jobs: int,
    expected_audits: int,
    expected_outcome: str,
) -> None:
    if not database_path.is_file():
        raise VerificationError("Stage 4C E2E database does not exist")

    connection = sqlite3.connect(database_path)
    try:
        jobs = connection.execute("SELECT * FROM emotion_analysis_jobs").fetchall()
        audits = connection.execute("SELECT * FROM emotion_analysis_audits").fetchall()
        if len(jobs) != expected_jobs or len(audits) != expected_audits:
            raise VerificationError("unexpected Stage 4C E2E job/audit counts")
        if not audits:
            raise VerificationError("unexpected Stage 4C E2E audit outcome")

        audit_columns = [
            item[1]
            for item in connection.execute(
                "PRAGMA table_info(emotion_analysis_audits)"
            ).fetchall()
        ]
        try:
            outcome_index = audit_columns.index("outcome")
        except ValueError as exc:
            raise VerificationError("Stage 4C E2E audit outcome column is missing") from exc
        if audits[0][outcome_index] != expected_outcome:
            raise VerificationError("unexpected Stage 4C E2E audit outcome")

        serialized = repr({"jobs": jobs, "audits": audits})
        if any(marker and marker in serialized for marker in forbidden_markers):
            raise VerificationError(
                "forbidden Stage 4C marker found in analysis metadata tables"
            )
    except sqlite3.Error as exc:
        raise VerificationError("unable to inspect Stage 4C E2E analysis tables") from exc
    finally:
        connection.close()


def remove_database_files(database_path: Path) -> None:
    for path in (
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    ):
        path.unlink(missing_ok=True)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify metadata-only Stage 4C E2E persistence."
    )
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--forbid", action="append", default=[])
    parser.add_argument("--expected-jobs", required=True, type=int)
    parser.add_argument("--expected-audits", required=True, type=int)
    parser.add_argument("--expected-outcome", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        verify_database(
            args.database,
            forbidden_markers=tuple(args.forbid),
            expected_jobs=args.expected_jobs,
            expected_audits=args.expected_audits,
            expected_outcome=args.expected_outcome,
        )
    except VerificationError as exc:
        print(f"BLOCKED: {exc}")
        return 1
    print(
        "PASS: Stage 4C E2E analysis tables are metadata-only "
        f"(jobs={args.expected_jobs}, audits={args.expected_audits}, "
        f"outcome={args.expected_outcome})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
