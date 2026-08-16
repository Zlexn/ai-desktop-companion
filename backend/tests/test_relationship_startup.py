from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.models import MemoryType
from app.main import create_app
from app.repositories.memories import MemoryRepository
from app.repositories.personas import PersonaRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.relationship_reconciler import RelationshipReconciler
from app.services.relationship_scheduler import RelationshipScheduler
from app.services.versioned_memory_mutation import VersionedMemoryMutationService

from tests.test_relationship_projector import _BASE_TIME, _insert_source


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        memory_source_reference_key_path=tmp_path / "source-reference.key",
    )


def _seed_source(connection, *, memory_id: str = "memory-1", version_id: str = "version-1") -> None:
    _insert_source(
        connection,
        memory_id=memory_id,
        version_id=version_id,
        subject_code="shared_experience",
        content="一起赏雪",
        created_at=_BASE_TIME,
    )
    connection.commit()


def _current_persona_id(database_url: str) -> str:
    with managed_connection(database_url) as connection:
        state = PersonaRepository(connection).current_state()
        assert state is not None
        return state.artifact_id


def test_startup_builds_one_scheduler_and_establishes_projection(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings_override=settings)) as client:
        assert client.get("/health").status_code == 200
        scheduler = getattr(client.app.state, "relationship_scheduler", None)
        assert scheduler is not None
        assert isinstance(scheduler, RelationshipScheduler)

    with managed_connection(settings.database_url) as connection:
        # No relationship sources exist; startup must keep a clean schema.
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_reconcile_jobs"
        ).fetchone()[0] == 0


def test_startup_with_eligible_source_establishes_current_projection(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings_override=settings)) as client:
        client.get("/health")
    persona_id = _current_persona_id(settings.database_url)

    with managed_connection(settings.database_url) as connection:
        _seed_source(connection)
        scheduler = RelationshipScheduler(
            RelationshipReconciler(connection),
            persona_artifact_id=persona_id,
        )
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_projections"
        ).fetchone()[0] == 1

    with TestClient(create_app(settings_override=settings)) as client:
        client.get("/health")
        assert getattr(client.app.state, "relationship_scheduler", None) is not None

    with managed_connection(settings.database_url) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_projections"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='apply'"
        ).fetchone()[0] == 1


def test_startup_recovery_reserves_missing_jobs_without_duplicate_effects(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings_override=settings)) as client:
        client.get("/health")
    persona_id = _current_persona_id(settings.database_url)

    # Simulate a failed notification: the source mutation commits but the
    # relationship notifier fails, so no reconcile job is reserved. Startup
    # recovery must scan the eligible head and converge exactly once.
    with managed_connection(settings.database_url) as connection:
        broken_notifier = Mock()
        broken_notifier.schedule.side_effect = RuntimeError("notifier down")
        service = VersionedMemoryMutationService(
            connection,
            memories=MemoryRepository(connection),
            versioned=VersionedMemoryRepository(connection),
            relationship_notifier=broken_notifier,
        )
        memory, _conflicts = service.create_manual(
            content="一起赏雪",
            memory_type=MemoryType.RELATIONSHIP_EVENT,
            source_session_id=None,
            importance=3,
            confidence=0.9,
            canonical_subject_code="shared_experience",
        )
        assert memory.id
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_reconcile_jobs"
        ).fetchone()[0] == 0

    with TestClient(create_app(settings_override=settings)) as client:
        client.get("/health")

    with managed_connection(settings.database_url) as connection:
        kinds = [
            row["event_kind"]
            for row in connection.execute(
                "SELECT event_kind FROM relationship_events ORDER BY created_at, id"
            )
        ]
        assert kinds.count("apply") == 1
        assert kinds.count("revoke") == 0
        pending = connection.execute(
            "SELECT COUNT(*) FROM relationship_reconcile_jobs WHERE status='pending'"
        ).fetchone()[0]
        assert pending == 0


def test_startup_no_remote_capability_exposed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings_override=settings)) as client:
        assert not hasattr(client.app.state, "relationship_remote_capability")
        scheduler = client.app.state.relationship_scheduler
        assert not hasattr(scheduler, "remote_provider")


def test_startup_clean_shutdown_does_not_error(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings_override=settings)
    with TestClient(app) as client:
        client.get("/health")
    # Context manager exit must not raise.
