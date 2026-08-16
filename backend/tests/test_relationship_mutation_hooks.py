from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from app.domain.models import MemorySource, MemoryType
from app.repositories.memories import MemoryRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.relationship_hooks import (
    NoOpRelationshipChangeNotifier,
    RelationshipChangeNotifier,
)
from app.services.versioned_memory_mutation import VersionedMemoryMutationService

from tests.test_relationship_projector import _BASE_TIME, _insert_persona, _insert_source


def _seed_source(connection, *, subject_code: str = "shared_experience") -> None:
    _insert_persona(connection, "persona-1")
    content = "小雪" if subject_code == "preferred_address" else "一起赏雪"
    _insert_source(
        connection,
        memory_id="memory-1",
        version_id="version-1",
        subject_code=subject_code,
        content=content,
        created_at=_BASE_TIME,
    )
    connection.commit()


def _database(tmp_path: Path, name: str):
    return managed_connection(f"sqlite:///{tmp_path / name}")


def _mutation_service(connection, notifier=None):
    return VersionedMemoryMutationService(
        connection,
        memories=MemoryRepository(connection),
        versioned=VersionedMemoryRepository(connection),
        relationship_notifier=notifier,
    )


def test_noop_notifier_accepts_and_ignores_memory_ids() -> None:
    notifier = NoOpRelationshipChangeNotifier()
    notifier.schedule(("memory-1", "memory-2"))
    assert isinstance(notifier, NoOpRelationshipChangeNotifier)


def test_create_manual_schedules_relationship_change_after_commit(tmp_path: Path) -> None:
    with _database(tmp_path, "hooks-create.db") as connection:
        _seed_source(connection)
        scheduled: list[tuple[str, ...]] = []
        notifier = Mock()
        notifier.schedule.side_effect = lambda ids: scheduled.append(tuple(ids))
        service = _mutation_service(connection, notifier=notifier)

        memory, _conflicts = service.create_manual(
            content="新关系事件",
            memory_type=MemoryType.RELATIONSHIP_EVENT,
            source_session_id=None,
            importance=3,
            confidence=0.9,
            canonical_subject_code="shared_experience",
        )

        assert memory.id
        assert scheduled, "create must notify relationship scheduler"
        assert memory.id in scheduled[0]


def test_update_schedules_relationship_change_after_commit(tmp_path: Path) -> None:
    with _database(tmp_path, "hooks-update.db") as connection:
        _seed_source(connection)
        notifier = Mock()
        service = _mutation_service(connection, notifier=notifier)

        service.update(
            "memory-1",
            content="更新后的关系事件",
            memory_type=None,
            importance=None,
            confidence=None,
            metadata={},
        )

        notifier.schedule.assert_called_once()
        called_ids = notifier.schedule.call_args.args[0]
        assert "memory-1" in called_ids


def test_archive_schedules_relationship_change_after_commit(tmp_path: Path) -> None:
    with _database(tmp_path, "hooks-archive.db") as connection:
        _seed_source(connection)
        notifier = Mock()
        service = _mutation_service(connection, notifier=notifier)

        service.archive("memory-1")

        notifier.schedule.assert_called_once()
        called_ids = notifier.schedule.call_args.args[0]
        assert "memory-1" in called_ids


def test_notifier_failure_is_caught_and_mutation_still_succeeds(tmp_path: Path) -> None:
    with _database(tmp_path, "hooks-fence.db") as connection:
        _seed_source(connection)
        notifier = Mock()
        notifier.schedule.side_effect = RuntimeError("notifier broken")
        service = _mutation_service(connection, notifier=notifier)

        memory, _conflicts = service.create_manual(
            content="另一关系事件",
            memory_type=MemoryType.RELATIONSHIP_EVENT,
            source_session_id=None,
            importance=3,
            confidence=0.9,
            canonical_subject_code="shared_experience",
        )

        assert memory.id
        notifier.schedule.assert_called_once()


def test_default_constructors_remain_compatible_without_notifier(tmp_path: Path) -> None:
    with _database(tmp_path, "hooks-default.db") as connection:
        _seed_source(connection)
        service = VersionedMemoryMutationService(
            connection,
            memories=MemoryRepository(connection),
            versioned=VersionedMemoryRepository(connection),
        )

        memory, _conflicts = service.create_manual(
            content="无 notifier 的关系事件",
            memory_type=MemoryType.RELATIONSHIP_EVENT,
            source_session_id=None,
            importance=3,
            confidence=0.9,
            canonical_subject_code="shared_experience",
        )

        assert memory.id


def test_confirm_candidate_schedules_after_commit_when_no_conflicts(tmp_path: Path) -> None:
    with _database(tmp_path, "hooks-confirm-ok.db") as connection:
        _seed_source(connection)
        candidate, _ = MemoryRepository(connection).create_candidate(
            content="待确认的偏好",
            memory_type=MemoryType.PREFERENCE,
            source_session_id=None,
            importance=3,
            confidence=0.9,
        )
        assert candidate is not None

        notifier = Mock()
        service = _mutation_service(connection, notifier=notifier)
        memory, _conflicts = service.confirm_candidate(
            candidate.id,
            canonical_subject_code="preferred_address",
        )
        assert memory.status.value == "active"
        notifier.schedule.assert_called_once()
        assert candidate.id in notifier.schedule.call_args.args[0]


def test_confirm_candidate_schedules_after_commit_even_with_conflicts(tmp_path: Path) -> None:
    with _database(tmp_path, "hooks-confirm-conflict.db") as connection:
        _seed_source(connection)
        memories = MemoryRepository(connection)
        active, _ = memories.create(
            content="用户喜欢红茶",
            memory_type=MemoryType.PREFERENCE,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=0.9,
        )
        # A pending candidate whose content conflicts with the active memory.
        candidate_id = "candidate-conflict"
        connection.execute(
            """
            INSERT INTO memories (
                id, content, memory_type, source, source_session_id,
                importance, confidence, status, metadata_json, created_at,
                updated_at
            ) VALUES (?, '用户喜欢红茶', 'preference', 'candidate', NULL,
                      2, 0.8, 'pending', '{}',
                      '2026-07-20T00:00:00+00:00',
                      '2026-07-20T00:00:00+00:00')
            """,
            (candidate_id,),
        )
        connection.commit()
        candidate = memories.get(candidate_id)
        assert candidate is not None

        notifier = Mock()
        service = _mutation_service(connection, notifier=notifier)
        memory, conflicts = service.confirm_candidate(
            candidate.id,
            canonical_subject_code="preferred_address",
        )
        assert any(conflict.id == active.id for conflict in conflicts)
        # Notification must still fire after the transaction commits.
        notifier.schedule.assert_called_once()
        assert candidate.id in notifier.schedule.call_args.args[0]


def test_commit_one_schedules_created_memory_after_commit(tmp_path: Path) -> None:
    """The auto-active write path must notify the created memory identity."""
    from unittest.mock import Mock

    from app.repositories.versioned_memories import VersionedMemoryRepository
    from app.services.memory_commit_policy import MemoryCommitPolicy
    from app.services.memory_source_reference import MemorySourceReferenceService
    from app.services.versioned_memory_commit import VersionedMemoryCommitService

    from tests.test_versioned_memory_commit import (
        _proposal,
        _request,
        _seed_turn,
    )

    with _database(tmp_path, "hooks-commit.db") as connection:
        # _seed_turn seeds the write authority itself.
        _seed_turn(connection, user_text="我喜欢晨间散步。")

        notifier = Mock()
        service = VersionedMemoryCommitService(
            connection,
            versioned=VersionedMemoryRepository(connection),
            policy=MemoryCommitPolicy(),
            source_references=MemorySourceReferenceService(b"r" * 32),
            relationship_notifier=notifier,
        )
        result = service.commit_one(
            _request(
                _proposal(
                    memory_type=MemoryType.PREFERENCE,
                    subject="生活习惯",
                    content="用户喜欢晨间散步",
                ),
                user_text="我喜欢晨间散步。",
            )
        )

        assert result.memory_id is not None
        notifier.schedule.assert_called_once()
        assert result.memory_id in notifier.schedule.call_args.args[0]


def test_relationship_notifier_impl_runs_reserved_jobs(tmp_path: Path) -> None:
    """RelationshipChangeNotifierImpl must reserve AND run the job so the
    projection converges within the session (design §8.3)."""
    from app.repositories.personas import PersonaRepository
    from app.services.relationship_hooks import RelationshipChangeNotifierImpl

    database_url = f"sqlite:///{tmp_path / 'hooks-run.db'}"
    with _database(tmp_path, "hooks-run.db") as connection:
        # Bootstrap persona (empty DB) and seed an eligible source memory.
        from app.repositories.memories import MemoryRepository
        from app.services.persona_compiler import PersonaCompiler
        from app.services.persona_service import PersonaService
        from app.services.prompt_renderer import default_prompt_renderer

        compiler = PersonaCompiler(
            template_text=default_prompt_renderer().load_template_text(),
            persona_max_characters=2000,
        )
        service = PersonaService(
            PersonaRepository(connection),
            compiler=compiler,
            bootstrap_config=default_prompt_renderer().load_persona_v1_config,
        )
        service.bootstrap()
        persona_id = PersonaRepository(connection).current_state().artifact_id
        memory, _conflicts = MemoryRepository(connection).create(
            content="一起赏雪",
            memory_type=MemoryType.RELATIONSHIP_EVENT,
            source=MemorySource.MANUAL,
            source_session_id=None,
            importance=3,
            confidence=0.9,
            canonical_subject_code="shared_experience",
        )
        memory_id = memory.id
        connection.commit()

    notifier = RelationshipChangeNotifierImpl(
        database_url=database_url,
        persona_artifact_id=persona_id,
    )
    notifier.schedule((memory_id,))

    with _database(tmp_path, "hooks-run.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='apply'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_projections"
        ).fetchone()[0] == 1
