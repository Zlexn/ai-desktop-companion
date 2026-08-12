from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.domain.relationship import RelationshipEventType
from app.repositories.relationship_ledger import RelationshipLedgerRepository
from app.services.relationship_projector import RelationshipProjector

from test_relationship_projector import (
    _BASE_TIME,
    _database,
    _insert_persona,
    _insert_source,
    _append_apply,
)


def _build_in_order(tmp_path: Path, name: str, order: tuple[str, ...]):
    with _database(tmp_path, name) as connection:
        _insert_persona(connection, "persona-1")
        definitions = {
            "shared-a": (
                "memory-a",
                "version-a",
                "shared_experience",
                "一起赏雪",
                RelationshipEventType.SHARED_EXPERIENCE,
                0,
            ),
            "shared-b": (
                "memory-b",
                "version-b",
                "shared_experience",
                "一起读书",
                RelationshipEventType.SHARED_EXPERIENCE,
                1,
            ),
            "commitment": (
                "memory-c",
                "version-c",
                "non_external_commitment",
                "会记得整理书架",
                RelationshipEventType.NON_EXTERNAL_COMMITMENT,
                2,
            ),
        }
        for key in definitions:
            memory_id, version_id, subject, content, _, minute = definitions[key]
            _insert_source(
                connection,
                memory_id=memory_id,
                version_id=version_id,
                subject_code=subject,
                content=content,
                created_at=_BASE_TIME + timedelta(minutes=minute),
            )
        connection.commit()
        for key in order:
            memory_id, _, _, _, event_type, _ = definitions[key]
            _append_apply(
                connection,
                memory_id=memory_id,
                event_type=event_type,
            )
        projector = RelationshipProjector(connection)
        with projector.write_transaction():
            snapshot = projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=5),
            )
        return (
            snapshot.projection_id,
            snapshot.familiarity,
            snapshot.relationship_summary_code,
            snapshot.source_relationship_event_ids,
            snapshot.integrity_fingerprint,
        )


def test_projection_semantics_ignore_insertion_order(tmp_path: Path) -> None:
    first = _build_in_order(
        tmp_path,
        "order-a.db",
        ("shared-a", "shared-b", "commitment"),
    )
    second = _build_in_order(
        tmp_path,
        "order-b.db",
        ("commitment", "shared-b", "shared-a"),
    )

    assert first[1:3] == second[1:3]
    # Database-local event IDs differ, but the semantic ordering remains source/time stable.
    assert len(first[3]) == len(second[3]) == 3


def test_projection_pointer_cas_conflict_rolls_back_snapshot(tmp_path: Path) -> None:
    with _database(tmp_path, "cas.db") as connection:
        _insert_persona(connection, "persona-1")
        _insert_source(
            connection,
            memory_id="memory-a",
            version_id="version-a",
            subject_code="shared_experience",
            content="一起赏雪",
            created_at=_BASE_TIME,
        )
        connection.commit()
        _append_apply(
            connection,
            memory_id="memory-a",
            event_type=RelationshipEventType.SHARED_EXPERIENCE,
        )
        projector = RelationshipProjector(connection)
        with projector.write_transaction():
            first = projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=2),
            )
        connection.execute(
            "DROP TRIGGER trg_relationship_projection_pointer_cas_update"
        )
        connection.execute(
            "UPDATE relationship_projection_active_state SET generation = generation + 1"
        )
        connection.commit()

        _insert_persona(connection, "persona-2", 2)
        try:
            with projector.write_transaction():
                projector.project(
                    persona_artifact_id="persona-2",
                    computed_at=_BASE_TIME + timedelta(days=3),
                    expected_pointer_generation=0,
                )
        except ValueError:
            pass
        else:
            raise AssertionError("stale projection CAS must fail")

        rows = connection.execute(
            "SELECT projection_id FROM relationship_projections ORDER BY version"
        ).fetchall()
        assert [row["projection_id"] for row in rows] == [first.projection_id]
