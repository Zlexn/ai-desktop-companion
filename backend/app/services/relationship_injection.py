from __future__ import annotations

from datetime import datetime

from app.repositories.sqlite import managed_connection
from app.services.relationship_dispatch import RelationshipDisclosureFence
from app.services.relationship_projector import RelationshipProjector


def _view_to_relationship(view) -> dict[str, object] | None:
    if view is None:
        return None
    return {
        "authority": "derived_relationship_projection_not_fact",
        "projection_id": view.projection_id,
        "projection_version": view.projection_version,
        "familiarity_bucket": view.familiarity_bucket.value
        if hasattr(view.familiarity_bucket, "value")
        else str(view.familiarity_bucket),
        "preferred_address": view.preferred_address,
        "relationship_summary_code": view.relationship_summary_code.value
        if hasattr(view.relationship_summary_code, "value")
        else str(view.relationship_summary_code),
        "persona_artifact_id": view.persona_artifact_id,
        "projection_rule_version": view.projection_rule_version,
    }


class RelationshipInjectionService:
    """Pre-dispatch revalidation of the relationship context through the
    relationship disclosure fence.

    Between context composition and Provider I/O, a suppress/redaction/forget
    may have landed. This service re-reads the verified current projection under
    the relationship fence and returns either the current verified view or a
    neutral one, so chat never leaks a forgotten sentinel or stale address.
    """

    def __init__(
        self,
        *,
        database_url: str,
        fence: RelationshipDisclosureFence,
    ) -> None:
        self._database_url = database_url
        self._fence = fence

    async def current_relationship(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, object] | None:
        """Composition-time snapshot of the current verified projection.

        The read itself is not fence-guarded: the authoritative, fence-guarded
        check happens at pre-dispatch revalidation. Returns None when no
        verified projection exists (no relationship context at all).
        """
        del now
        with managed_connection(self._database_url) as connection:
            view = RelationshipProjector(connection).current_view()
        return _view_to_relationship(view)

    async def revalidate_or_neutral(
        self,
        *,
        relationship: dict[str, object] | None,
        now: datetime | None = None,
    ) -> dict[str, object] | None:
        if relationship is None:
            return None
        async with self._fence.hold_dispatch():
            with managed_connection(self._database_url) as connection:
                view = RelationshipProjector(connection).current_view()
        if view is None:
            # Projection vanished (suppressed/redacted/corrupt): return neutral.
            return {
                "authority": "derived_relationship_projection_not_fact",
                "projection_id": "neutral",
                "projection_version": 0,
                "familiarity_bucket": "steady",
                "preferred_address": None,
                "relationship_summary_code": "steady",
                "persona_artifact_id": (
                    str(relationship.get("persona_artifact_id") or "")
                ),
                "projection_rule_version": str(
                    relationship.get("projection_rule_version") or ""
                ),
            }
        current = _view_to_relationship(view)
        # Preserve the composed persona provenance even when the current view
        # references a newer persona artifact (neutral is still persona-aware).
        return current
