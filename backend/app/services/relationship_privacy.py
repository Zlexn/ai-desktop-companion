from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import sqlite3

from app.domain.relationship import (
    RelationshipAuthorityActionKind,
    RelationshipEventType,
)
from app.repositories.relationship_ledger import (
    CorruptRelationshipEventError,
    RelationshipLedgerRepository,
)
from app.services.relationship_authority import RelationshipAuthorityService
from app.services.relationship_contract import (
    RELATIONSHIP_RULE_VERSION,
    RELATIONSHIP_SCOPE_ID,
)


class RelationshipPrivacyPrimitive:
    """In-transaction privacy primitive for relationship true forget.

    Runs inside the existing Gate B write transaction (caller-owned); never
    opens a nested independent connection. For a forgotten source memory with a
    preferred-address relationship it atomically:

    - revokes the eligible apply;
    - appends suppression authority (prevents revival);
    - clears the apply payload physically to NULL;
    - activates a projection with no address.

    All writes share the caller's transaction; any fault rolls back everything.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._connection = connection
        self._fault_injector = fault_injector
        self._ledger = RelationshipLedgerRepository(connection)
        self._authority = RelationshipAuthorityService(connection, ledger=self._ledger)

    def purge_preferred_address(
        self,
        *,
        source_memory_id: str,
        now: datetime,
    ) -> None:
        """Purge a forgotten source's preferred-address relationship state."""
        if not self._connection.in_transaction:
            raise RuntimeError(
                "relationship privacy requires a caller-owned write transaction"
            )
        self._checkpoint("begin")
        applies = self._eligible_preferred_address_applies(source_memory_id)
        for event in applies:
            self._ledger.redact_preferred_address(
                apply_event_id=event.id,
                created_at=now,
            )
            self._checkpoint("redacted_apply")
        self._append_suppression(source_memory_id, now=now)
        self._checkpoint("after_suppress")
        # Activate a no-address projection (recompute after revoke+suppress).
        from app.services.relationship_projector import RelationshipProjector

        RelationshipProjector(self._connection).project(
            persona_artifact_id=self._active_persona_id(),
            computed_at=now,
        )
        self._checkpoint("projection")

    def _eligible_preferred_address_applies(self, source_memory_id: str):
        rows = self._connection.execute(
            """
            SELECT * FROM relationship_events
            WHERE event_kind='apply' AND event_type='preferred_address'
              AND source_memory_id=?
              AND payload_state='active'
            ORDER BY observed_at, id
            """,
            (source_memory_id,),
        ).fetchall()
        return [self._ledger.event(str(row["id"])) for row in rows]

    def _append_suppression(self, source_memory_id: str, *, now: datetime) -> None:
        current = self._authority.effective(
            source_memory_id=source_memory_id,
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
            subject_code="preferred_address",
        )
        if current.suppressed:
            return
        self._authority.suppress(
            source_memory_id=source_memory_id,
            event_type=RelationshipEventType.PREFERRED_ADDRESS,
            subject_code="preferred_address",
            action_kind=RelationshipAuthorityActionKind.PRIVACY_REDACT,
            reason_code="privacy_redact",
            expected_decision_id=current.decision_id,
            expected_decision_generation=current.generation,
            expected_authority_epoch=current.authority_epoch,
        )

    def _active_persona_id(self) -> str:
        row = self._connection.execute(
            "SELECT id FROM persona_artifacts WHERE payload_state='active' "
            "ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("relationship privacy requires an active Persona")
        return str(row["id"])

    def _checkpoint(self, name: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(name)


def relationship_privacy_now() -> datetime:
    return datetime.now(UTC)
