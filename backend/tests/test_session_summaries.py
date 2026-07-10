from pathlib import Path

from app.domain.models import SessionSummary, SessionSummarySource
from app.repositories.sqlite import managed_connection


def test_session_summary_domain_model_supports_manual_source() -> None:
    assert SessionSummarySource.MANUAL.value == "manual"
    assert SessionSummarySource.GENERATED.value == "generated"
    assert SessionSummary.__name__ == "SessionSummary"


def test_session_summaries_table_is_created(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'session_summaries'"
        ).fetchone()
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(session_summaries)").fetchall()
        }

    assert table is not None
    assert columns == {
        "id",
        "session_id",
        "summary_text",
        "source",
        "covered_message_start_id",
        "covered_message_end_id",
        "message_count",
        "metadata_json",
        "created_at",
        "updated_at",
    }
