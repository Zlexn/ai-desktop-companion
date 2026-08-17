"""Gate C3 independence matrix.

Prove:
- Stage 4 emotion changes do not change relationship events/projection;
- C2 summaries do not source relationship state;
- assistant text and raw messages do not source relationship state;
- Persona switches preserve event-derived numerical state;
- relationship operations do not mutate memory, summary, Persona, or emotion
  records (design 18.5).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.domain.models import MemorySource, MemoryType
from app.repositories.emotions import EmotionRepository
from app.repositories.memories import MemoryRepository
from app.repositories.sqlite import managed_connection
from app.repositories.versioned_memories import VersionedMemoryRepository
from app.services.emotion_policy import EmotionPolicy
from app.services.emotion_service import EmotionService
from app.services.memory_source_reference import MemorySourceReferenceService
from app.services.relationship_api import RelationshipApiService
from app.services.relationship_reconciler import RelationshipReconciler
from app.services.relationship_scheduler import RelationshipScheduler

from tests.test_relationship_projector import (
    _BASE_TIME,
    _insert_persona,
    _insert_source,
)

def _database(tmp_path: Path, name: str):
    return managed_connection(f"sqlite:///{tmp_path / name}")


def _seed(connection, *, subject_code: str = "shared_experience") -> str:
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
    return "memory-1"


def _scheduler(connection) -> RelationshipScheduler:
    return RelationshipScheduler(
        RelationshipReconciler(connection),
        persona_artifact_id="persona-1",
    )


def _snapshot(connection) -> dict[str, object]:
    tables = (
        "memories",
        "memory_versions",
        "memory_evidence",
        "memory_write_activities",
        "session_summaries",
        "persona_artifacts",
        "emotion_states",
        "emotion_events",
    )
    return {
        table: [
            tuple(row)
            for row in connection.execute(
                f"SELECT * FROM {table} ORDER BY 1"
            ).fetchall()
        ]
        for table in tables
    }


def _projection_semantics(connection) -> tuple[object, ...]:
    return connection.execute(
        "SELECT familiarity, preferred_address_event_id, relationship_summary_code "
        "FROM relationship_projections ORDER BY version"
    ).fetchall()


def test_emotion_mutation_has_zero_relationship_effect(tmp_path: Path) -> None:
    with _database(tmp_path, "independence-emotion.db") as connection:
        _seed(connection)
        scheduler = _scheduler(connection)
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))
        before = _projection_semantics(connection)

        connection.execute(
            "INSERT INTO emotion_states "
            "(scope_id, enabled, mood, trust, concern, distance, irritation, "
            " formality, version, updated_at) "
            "VALUES ('default', 1, 0.9, 0.8, 0.1, 0.2, 0.3, 0.4, 1, ?)",
            ((_BASE_TIME + timedelta(days=2)).isoformat(),),
        )
        connection.commit()
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=3))

        assert _projection_semantics(connection) == before
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events"
        ).fetchone()[0] == 1


def test_summary_mutation_has_zero_relationship_effect(tmp_path: Path) -> None:
    with _database(tmp_path, "independence-summary.db") as connection:
        _seed(connection)
        scheduler = _scheduler(connection)
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))
        before = _projection_semantics(connection)

        now = (_BASE_TIME + timedelta(days=2)).isoformat()
        connection.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES ('session-x', 't', ?, ?)",
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO session_summaries (
                id, session_id, summary_text, source, message_count,
                metadata_json, created_at, updated_at,
                observed_memory_summary_barrier, payload_state, source_set_hash,
                summarizer_schema_version, injection_schema_version,
                replaces_summary_id, provenance_state, redacted_at,
                redaction_reason_code
            ) VALUES ('summary-1', 'session-x', '无关的会话概述', 'generated', 2,
                      '{}', ?, ?, 0, 'active', NULL, 'session-summary-v2',
                      'summary-injection-v1', NULL, 'legacy_unverified', NULL, NULL)
            """,
            (now, now),
        )
        connection.commit()
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=3))

        assert _projection_semantics(connection) == before
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events"
        ).fetchone()[0] == 1


def test_message_and_assistant_text_have_zero_relationship_effect(
    tmp_path: Path,
) -> None:
    with _database(tmp_path, "independence-messages.db") as connection:
        _seed(connection)
        scheduler = _scheduler(connection)
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))
        before = _projection_semantics(connection)

        now = (_BASE_TIME + timedelta(days=2)).isoformat()
        connection.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES ('s1', 't', ?, ?)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO messages (id, session_id, role, content, metadata_json, created_at) "
            "VALUES ('m1', 's1', 'user', '无关消息', '{}', ?)",
            (now,),
        )
        connection.execute(
            "INSERT INTO messages (id, session_id, role, content, metadata_json, created_at) "
            "VALUES ('m2', 's1', 'assistant', '无关回复文本', '{}', ?)",
            (now,),
        )
        connection.commit()
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=3))

        assert _projection_semantics(connection) == before
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events"
        ).fetchone()[0] == 1


def test_relationship_actions_do_not_mutate_other_tables(tmp_path: Path) -> None:
    with _database(tmp_path, "independence-actions.db") as connection:
        memory_id = _seed(connection, subject_code="preferred_address")
        references = MemorySourceReferenceService(b"q" * 32)
        versioned = VersionedMemoryRepository(connection)
        versioned.bootstrap_legacy(memory_id, source_references=references)
        scheduler = _scheduler(connection)
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))

        before = _snapshot(connection)

        api = RelationshipApiService(connection)
        now = _BASE_TIME + timedelta(days=2)
        events = api.event_items()
        apply_event = next(
            (event for event in events if event["event_kind"] == "apply"),
            None,
        )
        assert apply_event is not None
        authority = apply_event["authority"]

        api.reconcile(now=now)
        api.rebuild(now=now)
        api.suppress(
            apply_event_id=apply_event["id"],
            expected_decision_id=authority["decision_id"],
            expected_decision_generation=authority["generation"],
            expected_authority_epoch=authority["authority_epoch"],
            now=now,
        )

        after = _snapshot(connection)
        # Only relationship tables changed; memory/summary/Persona/emotion are untouched.
        assert after["memories"] == before["memories"]
        assert after["memory_versions"] == before["memory_versions"]
        assert after["memory_evidence"] == before["memory_evidence"]
        assert after["session_summaries"] == before["session_summaries"]
        assert after["persona_artifacts"] == before["persona_artifacts"]
        assert after["emotion_states"] == before["emotion_states"]
        assert after["emotion_events"] == before["emotion_events"]


def test_persona_switch_preserves_event_derived_numerical_state(
    tmp_path: Path,
) -> None:
    from app.repositories.personas import PersonaRepository
    from app.services.persona_compiler import PersonaCompiler
    from app.services.persona_service import PersonaService
    from app.services.prompt_renderer import default_prompt_renderer

    with _database(tmp_path, "independence-persona.db") as connection:
        renderer = default_prompt_renderer()
        repo = PersonaRepository(connection)
        compiler = PersonaCompiler(
            template_text=renderer.load_template_text(),
            persona_max_characters=2000,
        )
        personas = PersonaService(
            repo,
            compiler=compiler,
            bootstrap_config=renderer.load_persona_v1_config,
        )
        first = personas.bootstrap()
        _insert_source(
            connection,
            memory_id="memory-1",
            version_id="version-1",
            subject_code="shared_experience",
            content="一起赏雪",
            created_at=_BASE_TIME,
        )
        connection.commit()
        scheduler = RelationshipScheduler(
            RelationshipReconciler(connection),
            persona_artifact_id=first.artifact.id,
        )
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=1))
        before = _projection_semantics(connection)

        # Activate a second persona with a different config: numerical state
        # must be preserved and no new relationship events invented.
        config = renderer.load_persona_v1_config()
        config = {**config, "identity": {**config["identity"], "name": "切换测试角色"}}
        second = personas.create_and_activate(
            config,
            expected_artifact_id=first.artifact.id,
            expected_generation=0,
        )
        assert second.artifact.id != first.artifact.id
        connection.commit()
        scheduler.full_reconcile(now=_BASE_TIME + timedelta(days=2))

        after = _projection_semantics(connection)
        assert after == before
        # No new relationship events on Persona switch.
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_events WHERE event_kind='apply'"
        ).fetchone()[0] == 1
