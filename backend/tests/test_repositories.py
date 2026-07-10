from collections.abc import Iterator
from pathlib import Path

import pytest

from app.domain.models import ChatRole, MemoryAuditOperation, MemorySource, MemoryStatus, MemoryType
from app.repositories.memory_audit import MemoryAuditRepository
from app.repositories.memories import MemoryRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.repositories.sqlite import managed_connection


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test.db'}"


def test_create_list_get_and_delete_session(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        created = sessions.create("测试会话")

        assert created.title == "测试会话"
        assert sessions.get(created.id) == created
        assert sessions.list() == [created]
        assert sessions.delete(created.id) is True
        assert sessions.get(created.id) is None
        assert sessions.delete(created.id) is False


def test_messages_persist_after_reconnect(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("持久化会话")
        messages.add(session.id, ChatRole.USER, "你好")
        messages.add(session.id, ChatRole.ASSISTANT, "你好，我在。", {"provider": "fake"})

    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        loaded_session = sessions.get(session.id)
        loaded_messages = messages.list(session.id)

        assert loaded_session is not None
        assert loaded_session.title == "持久化会话"
        assert [message.content for message in loaded_messages] == ["你好", "你好，我在。"]
        assert loaded_messages[1].metadata == {"provider": "fake"}


def test_delete_session_cascades_messages(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("待删除")
        messages.add(session.id, ChatRole.USER, "删除测试")

        assert len(messages.list(session.id)) == 1
        assert sessions.delete(session.id) is True
        assert messages.list(session.id) == []


def test_recent_messages_are_bounded_and_chronological(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("上下文")
        for index in range(5):
            messages.add(session.id, ChatRole.USER, f"消息 {index}")

        recent = messages.list_recent(session.id, 3)

        assert [message.content for message in recent] == ["消息 2", "消息 3", "消息 4"]


def test_system_messages_are_not_persisted_as_chat_history(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        session = sessions.create("系统消息")

        with pytest.raises(ValueError, match="System prompts are not persisted"):
            messages.add(session.id, ChatRole.SYSTEM, "system prompt")


def test_create_list_get_and_archive_memory(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        created, conflicts = memories.create(
            content="用户偏好中文回复。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={"note": "manual test"},
        )

        assert conflicts == []
        assert created.content == "用户偏好中文回复。"
        assert created.memory_type == MemoryType.PREFERENCE
        assert created.source == MemorySource.MANUAL
        assert created.status == MemoryStatus.ACTIVE
        assert created.importance == 3
        assert created.confidence == 1.0
        assert created.metadata == {"note": "manual test"}
        assert memories.get(created.id) == created
        assert memories.list() == [created]

        assert memories.archive(created.id) is True
        archived = memories.require(created.id)
        assert archived.status == MemoryStatus.ARCHIVED
        assert memories.list() == []
        assert memories.list(status=MemoryStatus.ARCHIVED) == [archived]


def test_create_pending_candidate_memory(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)

        candidate, conflicts = memories.create_candidate(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={"candidate_reason": "explicit_like_statement"},
        )

        assert conflicts == []
        assert candidate is not None
        assert candidate.content == "用户喜欢红茶。"
        assert candidate.source == MemorySource.CANDIDATE
        assert candidate.status == MemoryStatus.PENDING
        assert candidate.metadata["candidate_reason"] == "explicit_like_statement"
        assert memories.list(status=MemoryStatus.PENDING) == [candidate]
        assert memories.list_for_context(limit=8) == []


def test_sqlite_migrates_stage3a_memory_constraints(database_url: str) -> None:
    from app.repositories.sqlite import connect, init_db

    connection = connect(database_url)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            memory_type TEXT NOT NULL CHECK (memory_type IN ('user_fact', 'preference', 'long_term_goal', 'important_event', 'relationship_event', 'other')),
            source TEXT NOT NULL CHECK (source IN ('manual')),
            source_session_id TEXT,
            importance INTEGER NOT NULL CHECK (importance >= 1 AND importance <= 5),
            confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
            status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.commit()
    init_db(connection)

    memories = MemoryRepository(connection)
    candidate, conflicts = memories.create_candidate(
        content="用户喜欢红茶。",
        memory_type=MemoryType.PREFERENCE,
        source_session_id=None,
        importance=3,
        confidence=0.7,
        metadata={},
    )

    assert conflicts == []
    assert candidate is not None
    assert candidate.status == MemoryStatus.PENDING
    connection.close()


def test_confirm_candidate_activates_memory_and_records_metadata(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        candidate, _ = memories.create_candidate(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={"candidate_reason": "explicit_like_statement"},
        )
        assert candidate is not None

        confirmed, conflicts = memories.confirm_candidate(candidate.id)

        assert conflicts == []
        assert confirmed.status == MemoryStatus.ACTIVE
        assert confirmed.source == MemorySource.CANDIDATE
        assert "confirmed_at" in confirmed.metadata
        assert memories.list(status=MemoryStatus.PENDING) == []
        assert [memory.id for memory in memories.list_for_context(limit=8)] == [candidate.id]


def test_dismiss_candidate_excludes_it_from_pending_and_context(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        candidate, _ = memories.create_candidate(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={},
        )
        assert candidate is not None

        dismissed = memories.dismiss_candidate(candidate.id)

        assert dismissed.status == MemoryStatus.DISMISSED
        assert "dismissed_at" in dismissed.metadata
        assert memories.list(status=MemoryStatus.PENDING) == []
        assert memories.list_for_context(limit=8) == []


def test_candidate_duplicate_active_or_pending_is_not_created(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        active, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        duplicate_active, active_conflicts = memories.create_candidate(
            content=" 用户喜欢红茶。 ",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={},
        )

        assert duplicate_active is None
        assert [memory.id for memory in active_conflicts] == [active.id]

        pending, _ = memories.create_candidate(
            content="用户不喜欢咖啡。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={},
        )
        assert pending is not None

        duplicate_pending, pending_conflicts = memories.create_candidate(
            content="用户不喜欢咖啡。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={},
        )

        assert duplicate_pending is None
        assert [memory.id for memory in pending_conflicts] == [pending.id]
        assert len(memories.list(status=MemoryStatus.PENDING)) == 1


def test_relevant_memory_outranks_unrelated_high_importance_memory(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        unrelated, _ = memories.create(
            content="用户正在构建本地 AI 桌宠。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )
        relevant, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=2,
            confidence=0.8,
            metadata={},
        )

        results = memories.list_relevant_for_context("我喜欢什么饮料？", limit=4, fallback_limit=2)

        assert [memory.id for memory in results] == [relevant.id]
        assert unrelated.id not in [memory.id for memory in results]


def test_relevant_context_excludes_non_active_memories(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        active, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        pending, _ = memories.create_candidate(
            content="用户喜欢咖啡。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={},
        )
        assert pending is not None
        dismissed, _ = memories.create_candidate(
            content="用户喜欢牛奶。",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.7,
            metadata={},
        )
        assert dismissed is not None
        memories.dismiss_candidate(dismissed.id)
        archived, _ = memories.create(
            content="用户喜欢果汁。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        memories.archive(archived.id)

        results = memories.list_relevant_for_context("我喜欢什么？", limit=8, fallback_limit=3)

        assert [memory.id for memory in results] == [active.id]


def test_type_hint_boosts_matching_memory_type(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        preference, _ = memories.create(
            content="用户喜欢桌宠项目。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        goal, _ = memories.create(
            content="用户的目标是完成桌宠项目。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        results = memories.list_relevant_for_context("我的目标计划和桌宠项目是什么？", limit=2, fallback_limit=1)

        assert [memory.id for memory in results][:2] == [goal.id, preference.id]


def test_relevance_falls_back_to_small_high_priority_set_when_no_match(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        first, _ = memories.create(
            content="用户正在构建本地 AI 桌宠。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )
        second, _ = memories.create(
            content="用户偏好中文回复。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=4,
            confidence=1.0,
            metadata={},
        )
        third, _ = memories.create(
            content="用户住在上海。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        results = memories.list_relevant_for_context("今天天气怎么样？", limit=8, fallback_limit=2)

        assert [memory.id for memory in results] == [first.id, second.id]
        assert third.id not in [memory.id for memory in results]


def test_memories_persist_after_reconnect(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        created, _ = memories.create(
            content="用户正在构建本地 AI 桌宠。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=5,
            confidence=1.0,
            metadata={},
        )

    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        loaded = memories.require(created.id)
        assert loaded.content == "用户正在构建本地 AI 桌宠。"
        assert loaded.memory_type == MemoryType.LONG_TERM_GOAL


def test_chat_messages_are_not_memories(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        sessions = SessionRepository(connection)
        messages = MessageRepository(connection)
        memories = MemoryRepository(connection)
        session = sessions.create("聊天不是记忆")
        messages.add(session.id, ChatRole.USER, "我喜欢雪天。")

        assert memories.list() == []


def test_duplicate_same_type_memory_returns_conflict_without_overwrite(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        first, first_conflicts = memories.create(
            content="用户喜欢中文回复。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        second, second_conflicts = memories.create(
            content=" 用户喜欢中文回复。 ",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=2,
            confidence=0.8,
            metadata={},
        )

        assert first_conflicts == []
        assert [memory.id for memory in second_conflicts] == [first.id]
        assert memories.require(first.id).content == "用户喜欢中文回复。"
        assert memories.require(second.id).content == "用户喜欢中文回复。"
        assert len(memories.list()) == 2


def test_same_content_different_memory_type_is_not_conflict(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户喜欢雪。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )
        _, conflicts = memories.create(
            content="用户喜欢雪。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []


def test_opposite_preference_polarity_returns_conflict(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        like, _ = memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        dislike, conflicts = memories.create(
            content="用户不喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert [memory.id for memory in conflicts] == [like.id]
        assert memories.require(dislike.id).content == "用户不喜欢红茶。"


def test_different_preference_values_do_not_conflict(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户喜欢红茶。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户喜欢咖啡。",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []


def test_residence_single_value_fact_conflicts_when_value_changes(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        shanghai, _ = memories.create(
            content="用户住在上海。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户住在北京。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert [memory.id for memory in conflicts] == [shanghai.id]


def test_residence_and_occupation_do_not_conflict(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户住在上海。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户的职业是工程师。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []


def test_occupation_single_value_fact_conflicts_when_value_changes(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        student, _ = memories.create(
            content="用户的职业是学生。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户的职业是工程师。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert [memory.id for memory in conflicts] == [student.id]


def test_name_single_value_fact_conflicts_when_value_changes(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        zhang, _ = memories.create(
            content="用户的名字是张三。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户叫李四。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert [memory.id for memory in conflicts] == [zhang.id]


def test_school_single_value_fact_conflicts_when_value_changes(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        fudan, _ = memories.create(
            content="用户就读于复旦大学。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户在上海交通大学读书。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert [memory.id for memory in conflicts] == [fudan.id]


def test_company_single_value_fact_conflicts_when_value_changes(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        old_company, _ = memories.create(
            content="用户就职于甲公司。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户的公司是乙公司。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert [memory.id for memory in conflicts] == [old_company.id]


def test_historical_residence_does_not_conflict_with_current_residence(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户住在以前的北京。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户住在上海。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []


def test_historical_school_does_not_conflict_with_current_school(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户就读于曾经的复旦大学。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户就读于上海交通大学。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []


def test_historical_company_does_not_conflict_with_current_company(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户就职于去年的甲公司。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户就职于乙公司。",
            memory_type=MemoryType.USER_FACT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []


def test_goal_and_preparation_overlap_returns_conflict(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        goal, _ = memories.create(
            content="用户的目标是完成桌宠项目。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户正在准备完成桌宠项目。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert [memory.id for memory in conflicts] == [goal.id]


def test_different_goals_do_not_conflict(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        memories = MemoryRepository(connection)
        memories.create(
            content="用户的目标是完成桌宠项目。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        _, conflicts = memories.create(
            content="用户正在准备考试。",
            memory_type=MemoryType.LONG_TERM_GOAL,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=1.0,
            metadata={},
        )

        assert conflicts == []


def test_memory_audit_repository_records_conflict_event(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        audit = MemoryAuditRepository(connection)

        event = audit.record_conflict(
            memory_id="target-memory",
            related_memory_ids=["existing-1", "existing-2"],
            operation=MemoryAuditOperation.CREATE,
            metadata={"source": "api_test"},
        )

        assert event.event_type == "conflict_detected"
        assert event.memory_id == "target-memory"
        assert event.related_memory_ids == ["existing-1", "existing-2"]
        assert event.operation == MemoryAuditOperation.CREATE
        assert event.metadata == {"source": "api_test"}

        loaded = audit.list_recent(limit=10)
        assert [item.id for item in loaded] == [event.id]
        assert loaded[0].related_memory_ids == ["existing-1", "existing-2"]


def test_memory_audit_repository_lists_recent_events_newest_first(database_url: str) -> None:
    with managed_connection(database_url) as connection:
        audit = MemoryAuditRepository(connection)

        first = audit.record_conflict(
            memory_id="first",
            related_memory_ids=["a"],
            operation=MemoryAuditOperation.CREATE,
            metadata={},
        )
        second = audit.record_conflict(
            memory_id="second",
            related_memory_ids=["b"],
            operation=MemoryAuditOperation.UPDATE,
            metadata={},
        )
        third = audit.record_conflict(
            memory_id="third",
            related_memory_ids=["c"],
            operation=MemoryAuditOperation.CONFIRM_CANDIDATE,
            metadata={},
        )

        loaded = audit.list_recent(limit=2)

        assert [event.id for event in loaded] == [third.id, second.id]
        assert first.id not in [event.id for event in loaded]
