from pathlib import Path

import pytest

from app.domain.models import ChatRole, MemorySource, MemoryType, SessionSummary, SessionSummarySource
from app.repositories.memories import MemoryRepository
from app.repositories.messages import MessageRepository
from app.repositories.session_summaries import SessionSummaryRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection
from app.services.memory_source_reference import MemorySourceReferenceService


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
        "observed_memory_summary_barrier",
        "payload_state",
        "source_set_hash",
        "summarizer_schema_version",
        "injection_schema_version",
        "replaces_summary_id",
        "provenance_state",
        "redacted_at",
        "redaction_reason_code",
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


def test_delete_redacts_summary_payload_instead_of_removing_row(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        summaries = SessionSummaryRepository(connection)
        session = sessions.create("delete summary")
        summary = summaries.create(session_id=session.id, summary_text="可删除摘要")

        assert summaries.delete(summary.id) is True
        assert summaries.delete(summary.id) is False
        retained = summaries.list_for_session(session.id)
        assert len(retained) == 1
        assert retained[0].summary_text is None
        raw = connection.execute(
            "SELECT payload_state, redaction_reason_code FROM session_summaries "
            "WHERE id=?",
            (summary.id,),
        ).fetchone()
        assert tuple(raw) == ("redacted", "legacy_manual_redaction")


@pytest.mark.asyncio
async def test_legacy_delete_cannot_redact_exact_generated_summary(
    tmp_path: Path,
) -> None:
    from test_summary_rebuild import _generated_summary

    database_url = f"sqlite:///{tmp_path / 'exact-delete.db'}"
    _, _, summary = await _generated_summary(database_url)

    with managed_connection(database_url) as connection:
        summaries = SessionSummaryRepository(connection)
        with pytest.raises(ValueError, match="invalidation service"):
            summaries.delete(summary["id"])
        row = connection.execute(
            "SELECT summary_text, payload_state FROM session_summaries WHERE id=?",
            (summary["id"],),
        ).fetchone()
        assert row["summary_text"] is not None
        assert row["payload_state"] == "active"
        assert connection.execute(
            "SELECT 1 FROM summary_source_suppressions WHERE session_id=? "
            "AND source_set_hash=?",
            (summary["session_id"], summary["source_set_hash"]),
        ).fetchone() is None



def test_redacted_summary_reader_preserves_unavailable_payload(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'redacted-summary.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        summaries = SessionSummaryRepository(connection)
        session = sessions.create("redacted summary")
        summary = summaries.create(session_id=session.id, summary_text="private payload")
        connection.execute(
            "UPDATE session_summaries "
            "SET summary_text=NULL, payload_state='redacted', "
            "provenance_state='legacy_unverified', redacted_at='now', "
            "redaction_reason_code='user_privacy_redaction' WHERE id=?",
            (summary.id,),
        )
        connection.commit()

        listed = summaries.list_for_session(session.id)

    assert len(listed) == 1
    assert listed[0].summary_text is None


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


def test_deleting_session_cascades_session_summaries(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        summaries = SessionSummaryRepository(connection)
        session = sessions.create("cascade")
        summaries.create(session_id=session.id, summary_text="删除会话时应删除摘要")

        assert summaries.list_for_session(session.id)
        assert sessions.delete(session.id) is True
        assert summaries.list_for_session(session.id) == []


def test_session_summaries_do_not_create_long_term_memories(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'summaries.db'}"

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        summaries = SessionSummaryRepository(connection)
        memories = MemoryRepository(
            connection,
            source_references=MemorySourceReferenceService(b"s" * 32),
        )
        session = sessions.create("separation")

        summaries.create(session_id=session.id, summary_text="这是会话摘要，不是长期记忆。")
        memory, conflicts = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=session.id,
            importance=3,
            confidence=0.8,
        )

        listed_summaries = summaries.list_for_session(session.id)
        listed_memories = memories.list()

    assert len(listed_summaries) == 1
    assert listed_summaries[0].summary_text == "这是会话摘要，不是长期记忆。"
    assert conflicts == []
    assert listed_memories == [memory]
