import sqlite3
from pathlib import Path

import pytest

from scripts.verify_stage4c_e2e_database import (
    VerificationError,
    remove_database_files,
    verify_database,
)


FORBIDDEN_MARKERS = (
    "e2e-analysis-secret",
    "e2e-post-revoke-secret",
    "stage4c-e2e-token",
    "我今天很难受",
    "我需要帮助",
)


def _create_database(
    path: Path,
    *,
    job_note: str = "metadata-only",
    audit_note: str = "metadata-only",
    outcome: str = "applied",
    job_count: int = 1,
    audit_count: int = 1,
) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE emotion_analysis_jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                note TEXT NOT NULL
            );
            CREATE TABLE emotion_analysis_audits (
                id TEXT PRIMARY KEY,
                outcome TEXT NOT NULL,
                note TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            "INSERT INTO emotion_analysis_jobs VALUES (?, ?, ?)",
            [(f"job-{index}", "completed", job_note) for index in range(job_count)],
        )
        connection.executemany(
            "INSERT INTO emotion_analysis_audits VALUES (?, ?, ?)",
            [(f"audit-{index}", outcome, audit_note) for index in range(audit_count)],
        )
        connection.commit()
    finally:
        connection.close()


def test_verify_database_accepts_expected_metadata_only_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "safe.db"
    _create_database(database_path)

    verify_database(
        database_path,
        forbidden_markers=FORBIDDEN_MARKERS,
        expected_jobs=1,
        expected_audits=1,
        expected_outcome="applied",
    )


@pytest.mark.parametrize("table", ["job", "audit"])
@pytest.mark.parametrize("marker", FORBIDDEN_MARKERS)
def test_verify_database_rejects_forbidden_markers(
    tmp_path: Path,
    table: str,
    marker: str,
) -> None:
    database_path = tmp_path / f"leak-{table}.db"
    _create_database(
        database_path,
        job_note=marker if table == "job" else "metadata-only",
        audit_note=marker if table == "audit" else "metadata-only",
    )

    with pytest.raises(VerificationError, match="forbidden Stage 4C marker"):
        verify_database(
            database_path,
            forbidden_markers=FORBIDDEN_MARKERS,
            expected_jobs=1,
            expected_audits=1,
            expected_outcome="applied",
        )


@pytest.mark.parametrize(
    ("job_count", "audit_count", "outcome", "message"),
    [
        (0, 1, "applied", "unexpected Stage 4C E2E job/audit counts"),
        (1, 0, "applied", "unexpected Stage 4C E2E job/audit counts"),
        (1, 1, "failed", "unexpected Stage 4C E2E audit outcome"),
    ],
)
def test_verify_database_rejects_wrong_counts_or_outcome(
    tmp_path: Path,
    job_count: int,
    audit_count: int,
    outcome: str,
    message: str,
) -> None:
    database_path = tmp_path / "wrong.db"
    _create_database(
        database_path,
        job_count=job_count,
        audit_count=audit_count,
        outcome=outcome,
    )

    with pytest.raises(VerificationError, match=message):
        verify_database(
            database_path,
            forbidden_markers=FORBIDDEN_MARKERS,
            expected_jobs=1,
            expected_audits=1,
            expected_outcome="applied",
        )


def test_remove_database_files_removes_database_and_sidecars_only(tmp_path: Path) -> None:
    database_path = tmp_path / "e2e.db"
    paths = [database_path, Path(f"{database_path}-wal"), Path(f"{database_path}-shm")]
    other_path = tmp_path / "keep.txt"
    for path in [*paths, other_path]:
        path.write_text("temporary", encoding="utf-8")

    remove_database_files(database_path)

    assert all(not path.exists() for path in paths)
    assert other_path.exists()
