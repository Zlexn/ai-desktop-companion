import sqlite3
from pathlib import Path

from app.repositories.sqlite import connect, init_db


OLD_ANALYSIS_JOBS_SQL = """
CREATE TABLE emotion_analysis_jobs (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    source_user_message_id TEXT NOT NULL,
    source_assistant_message_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    status TEXT NOT NULL,
    outcome_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source_assistant_message_id, schema_version)
);
"""


def test_init_db_migrates_existing_analysis_jobs_with_base_version(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    connection = connect(database_url)
    try:
        connection.executescript(OLD_ANALYSIS_JOBS_SQL)
        connection.execute(
            """
            INSERT INTO emotion_analysis_jobs (
                id, scope_id, source_session_id, source_user_message_id,
                source_assistant_message_id, schema_version, status,
                outcome_reason, created_at, updated_at
            ) VALUES ('job-1', 'default-companion', 's', 'u', 'a',
                      'emotion_analysis_v1', 'failed', 'interrupted', 'now', 'now')
            """
        )
        connection.commit()

        init_db(connection)

        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(emotion_analysis_jobs)").fetchall()
        }
        assert "base_emotion_version" in columns
        assert connection.execute(
            "SELECT base_emotion_version FROM emotion_analysis_jobs WHERE id = 'job-1'"
        ).fetchone()[0] == 0
    finally:
        connection.close()
