from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.domain.models import MemorySource, MemoryType
from app.repositories.memories import MemoryRepository
from app.repositories.personas import PersonaRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.persona_compiler import PersonaCompiler
from app.services.persona_service import PersonaService
from app.services.prompt_renderer import default_prompt_renderer
from app.services.relationship_reconciler import RelationshipReconciler
from app.services.relationship_scheduler import RelationshipScheduler

from tests.test_relationship_projector import _BASE_TIME, _insert_persona


def _database(tmp_path: Path, name: str):
    return managed_connection(f"sqlite:///{tmp_path / name}")


def _seed_apply_with_persona(connection, *, persona_id: str) -> None:
    """Create an eligible source memory and reconcile under persona_id."""
    references = __import__(
        "app.services.memory_source_reference", fromlist=["MemorySourceReferenceService"]
    ).MemorySourceReferenceService(b"q" * 32)
    memories = MemoryRepository(connection, source_references=references)
    memory, _conflicts = memories.create(
        content="一起赏雪",
        memory_type=MemoryType.RELATIONSHIP_EVENT,
        source=MemorySource.MANUAL,
        source_session_id=None,
        importance=3,
        confidence=0.9,
        canonical_subject_code="shared_experience",
    )
    connection.commit()
    reconciler = RelationshipReconciler(connection)
    scheduler = RelationshipScheduler(reconciler, persona_artifact_id=persona_id)
    scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))
    return memory.id


def test_persona_activation_recomputes_projection_with_new_provenance(tmp_path: Path) -> None:
    """Persona activation must not create events and must activate a projection
    referencing the new Persona artifact (design §11)."""
    with _database(tmp_path, "switch.db") as connection:
        compiler = PersonaCompiler(
            template_text=default_prompt_renderer().load_template_text(),
            persona_max_characters=2000,
        )
        repo = PersonaRepository(connection)
        bootstrap = default_prompt_renderer().load_persona_v1_config
        service = PersonaService(
            repo,
            compiler=compiler,
            bootstrap_config=bootstrap,
        )
        # Bootstrap persona-1 (activated).
        first = service.bootstrap()
        first_artifact_id = first.artifact.id

        # Reconcile under persona-1.
        _seed_apply_with_persona(connection, persona_id=first_artifact_id)
        events_before = connection.execute(
            "SELECT COUNT(*) FROM relationship_events"
        ).fetchone()[0]
        projections_before = connection.execute(
            "SELECT COUNT(*) FROM relationship_projections"
        ).fetchone()[0]

        # Activate a new persona-2 via the real service; the injected projection
        # notifier must recompute the projection with the new provenance.
        notifier_called: list[str] = []

        def recompute_projection() -> None:
            notifier_called.append("switch")
            state_after = repo.current_state()
            assert state_after is not None
            # Persona switch only recomputes the projection with the new
            # provenance; it must NOT reserve new reconcile jobs (source facts
            # are unchanged).
            from app.services.relationship_projector import RelationshipProjector

            projector = RelationshipProjector(connection)
            with projector.write_transaction():
                projector.project(
                    persona_artifact_id=state_after.artifact_id,
                    computed_at=_BASE_TIME + timedelta(days=2),
                )

        switching_service = PersonaService(
            repo,
            compiler=compiler,
            bootstrap_config=bootstrap,
            after_pointer_switch=recompute_projection,
        )
        state = repo.current_state()
        assert state is not None
        # Create persona-2 artifact (valid schema) without activating it.
        import copy

        second_config = copy.deepcopy(bootstrap())
        second_config["identity"]["name"] = "雪之下雪乃"
        compiled = compiler.compile(second_config)
        second_artifact_id = repo.insert_artifact(
            compiled,
            artifact_id="persona-switch-2",
            created_at=_BASE_TIME,
        ).id
        connection.commit()

        # Activate persona-2 (real switch triggers the projection recompute).
        switching_service.activate(
            second_artifact_id,
            expected_artifact_id=state.artifact_id,
            expected_generation=state.activation_generation,
        )

        # No new relationship events (persona switch is not a relationship fact).
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events"
        ).fetchone()[0] == events_before
        # The projection must now reference the new persona artifact.
        row = connection.execute(
            "SELECT persona_artifact_id FROM relationship_projection_active_state "
            "JOIN relationship_projections ON "
            "relationship_projections.projection_id = "
            "relationship_projection_active_state.projection_id"
        ).fetchone()
        assert row is not None and row["persona_artifact_id"] == second_artifact_id
        assert projections_before >= 1
