from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.domain.relationship import RelationshipEventType
from app.repositories.relationship_ledger import RelationshipLedgerRepository
from app.services.relationship_projector import RelationshipProjector

from test_relationship_projector import (
    _BASE_TIME,
    _database,
    _seed_complete_set,
)


def test_verified_view_resolves_only_exact_current_address(tmp_path: Path) -> None:
    with _database(tmp_path, "view.db") as connection:
        events = _seed_complete_set(connection)
        projector = RelationshipProjector(connection)
        with projector.write_transaction():
            snapshot = projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=2),
            )

        view = projector.current_view()
        assert view is not None
        assert view.projection_id == snapshot.projection_id
        assert view.preferred_address == "小雪"
        assert view.contributing_event_count == 3
        raw = connection.execute(
            "SELECT preferred_address_event_id, source_relationship_event_ids_json "
            "FROM relationship_projections WHERE projection_id = ?",
            (snapshot.projection_id,),
        ).fetchone()
        assert raw["preferred_address_event_id"] == events["address"].id
        assert "小雪" not in raw["source_relationship_event_ids_json"]


def test_view_hides_address_after_revoke_without_rewriting_projection(tmp_path: Path) -> None:
    with _database(tmp_path, "view-revoke.db") as connection:
        events = _seed_complete_set(connection)
        projector = RelationshipProjector(connection)
        with projector.write_transaction():
            snapshot = projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=2),
            )
        ledger = RelationshipLedgerRepository(connection)
        with ledger.write_transaction():
            ledger.append_revoke(
                apply_event_id=events["address"].id,
                created_at=_BASE_TIME + timedelta(days=3),
            )

        view = projector.current_view()
        assert view is not None
        assert view.projection_id == snapshot.projection_id
        assert view.preferred_address is None


def test_view_hides_address_after_source_becomes_stale(tmp_path: Path) -> None:
    with _database(tmp_path, "view-stale.db") as connection:
        _seed_complete_set(connection)
        projector = RelationshipProjector(connection)
        with projector.write_transaction():
            projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=2),
            )
        connection.execute(
            "UPDATE memory_record_states SET state = 'archived', record_generation = 1 "
            "WHERE memory_id = 'memory-address'"
        )
        connection.commit()

        assert projector.current_view() is None
        view = projector.current_view_or_neutral(persona_artifact_id="persona-1")
        assert view.projection_id == "neutral"
        assert view.preferred_address is None


def test_persona_switch_before_recompute_returns_requested_neutral_view(
    tmp_path: Path,
) -> None:
    with _database(tmp_path, "view-persona-switch.db") as connection:
        _seed_complete_set(connection)
        projector = RelationshipProjector(connection)
        with projector.write_transaction():
            projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=2),
            )

        view = projector.current_view_or_neutral(persona_artifact_id="persona-2")
        assert view.projection_id == "neutral"
        assert view.persona_artifact_id == "persona-2"
        assert view.preferred_address is None
        assert view.contributing_event_count == 0


def test_projection_integrity_mismatch_returns_neutral_view(tmp_path: Path) -> None:
    with _database(tmp_path, "view-corrupt.db") as connection:
        _seed_complete_set(connection)
        projector = RelationshipProjector(connection)
        with projector.write_transaction():
            snapshot = projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=2),
            )
        connection.execute("DROP TRIGGER trg_relationship_projections_immutable_update")
        connection.execute(
            "UPDATE relationship_projections SET integrity_fingerprint = ? "
            "WHERE projection_id = ?",
            ("e" * 64, snapshot.projection_id),
        )
        connection.commit()

        assert projector.current_view() is None
        neutral = projector.current_view_or_neutral(persona_artifact_id="persona-1")
        assert neutral.projection_id == "neutral"
        assert neutral.preferred_address is None
        assert neutral.familiarity_bucket == "steady"
        assert neutral.contributing_event_count == 0


def test_redacted_address_is_never_resolved(tmp_path: Path) -> None:
    with _database(tmp_path, "view-redacted.db") as connection:
        events = _seed_complete_set(connection)
        projector = RelationshipProjector(connection)
        with projector.write_transaction():
            projector.project(
                persona_artifact_id="persona-1",
                computed_at=_BASE_TIME + timedelta(days=2),
            )
        ledger = RelationshipLedgerRepository(connection)
        with ledger.write_transaction():
            redacted, _ = ledger.redact_preferred_address(
                apply_event_id=events["address"].id,
                created_at=_BASE_TIME + timedelta(days=3),
            )
        assert redacted.payload_state.value == "redacted"
        assert redacted.event_type is RelationshipEventType.PREFERRED_ADDRESS

        view = projector.current_view()
        assert view is not None
        assert view.preferred_address is None
