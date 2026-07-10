from pathlib import Path

import pytest

from app.domain.models import ChatRole, SessionSummary, SessionSummarySource
from app.repositories.messages import MessageRepository
from app.repositories.session_summaries import SessionSummaryRepository
from app.repositories.sessions import SessionRepository
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


def test_create_and_list_session_summaries(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        summaries = SessionSummaryRepository(connection)
        session = sessions.create("summary scope")
        first_message = messages.add(session.id, ChatRole.USER, "第一条消息")
        last_message = messages.add(session.id, ChatRole.ASSISTANT, "第二条消息")

        summary = summaries.create(
            session_id=session.id,
            summary_text="用户问候，助手回应。",
            covered_message_start_id=first_message.id,
            covered_message_end_id=last_message.id,
            message_count=2,
            metadata={"note": "synthetic"},
        )
        listed = summaries.list_for_session(session.id)

    assert summary.session_id == session.id
    assert summary.summary_text == "用户问候，助手回应。"
    assert summary.source == SessionSummarySource.MANUAL
    assert summary.covered_message_start_id == first_message.id
    assert summary.covered_message_end_id == last_message.id
    assert summary.message_count == 2
    assert summary.metadata == {"note": "synthetic"}
    assert listed == [summary]


def test_latest_for_session_returns_newest_summary(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        summaries = SessionSummaryRepository(connection)
        session = sessions.create("latest summary")
        first = summaries.create(session_id=session.id, summary_text="第一段摘要")
        second = summaries.create(session_id=session.id, summary_text="第二段摘要")

        latest = summaries.latest_for_session(session.id)
        missing = summaries.latest_for_session("missing-session")

    assert latest == second
    assert latest != first
    assert missing is None


def test_delete_session_summary_returns_whether_row_was_deleted(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        summaries = SessionSummaryRepository(connection)
        session = sessions.create("delete summary")
        summary = summaries.create(session_id=session.id, summary_text="可删除摘要")

        assert summaries.delete(summary.id) is True
        assert summaries.delete(summary.id) is False
        assert summaries.list_for_session(session.id) == []


def test_session_summary_rejects_empty_text_and_negative_message_count(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        summaries = SessionSummaryRepository(connection)
        session = sessions.create("validation")

        with pytest.raises(ValueError, match="summary_text must not be empty"):
            summaries.create(session_id=session.id, summary_text="   ")
        with pytest.raises(ValueError, match="message_count must be non-negative"):
            summaries.create(session_id=session.id, summary_text="摘要", message_count=-1)
