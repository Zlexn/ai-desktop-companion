from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class RelationshipChangeNotifier(Protocol):
    """Non-privacy notification boundary for Gate C3 reconciliation scheduling.

    Implementations receive affected memory IDs after their Gate B mutation
    transaction commits. This is an internal best-effort notification only:
    eventual convergence is guaranteed by startup recovery, never by this
    callback. Implementations must not open long-lived closures over large
    application objects.
    """

    def schedule(self, memory_ids: tuple[str, ...]) -> None: ...


class NoOpRelationshipChangeNotifier:
    """Default notifier that keeps existing unit constructors compatible."""

    def schedule(self, memory_ids: tuple[str, ...]) -> None:
        del memory_ids


class RelationshipChangeNotifierImpl:
    """Scheduler-backed notifier that reserves reconcile jobs in a short-lived
    connection per call, so no long-lived database handle is captured."""

    def __init__(self, database_url: str, persona_artifact_id: str) -> None:
        self._database_url = database_url
        self._persona_artifact_id = persona_artifact_id

    def schedule(self, memory_ids: tuple[str, ...]) -> None:
        from app.repositories.sqlite import managed_connection
        from app.services.relationship_reconciler import RelationshipReconciler
        from app.services.relationship_scheduler import RelationshipScheduler

        with managed_connection(self._database_url) as connection:
            scheduler = RelationshipScheduler(
                RelationshipReconciler(connection),
                persona_artifact_id=self._persona_artifact_id,
            )
            scheduler.schedule(memory_ids, created_at=datetime.now(UTC))
            # Run the reserved jobs now so relationship state converges
            # within this session instead of only at the next restart.
            # run_pending is idempotent (terminal jobs return unchanged).
            scheduler.run_pending(now=datetime.now(UTC))

