from __future__ import annotations

import base64
import json
import sqlite3
from datetime import UTC, datetime

from app.domain.models import MemoryStatus
from app.domain.relationship import (
    RelationshipAuthorityActionKind,
    RelationshipAuthoritySnapshot,
    RelationshipEvent,
    RelationshipEventKind,
    RelationshipEventType,
    RelationshipPayloadState,
    RelationshipReconcileJob,
)
from app.repositories.memories import MemoryRepository
from app.repositories.relationship_ledger import (
    RelationshipLedgerRepository,
)
from app.repositories.relationship_projections import (
    RelationshipProjectionRepository,
)
from app.services.relationship_authority import (
    RelationshipAuthorityService,
    StaleRelationshipAuthorityError,
)
from app.services.relationship_projector import (
    RelationshipProjectionView,
    RelationshipProjector,
)
from app.services.relationship_reconciler import RelationshipReconciler
from app.services.relationship_scheduler import RelationshipScheduler


def _encode_cursor(offset: int, *, kind: str) -> str:
    raw = json.dumps(
        {"kind": kind, "offset": offset},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str | None, *, kind: str) -> int:
    if cursor is None:
        return 0
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        )
        offset = payload["offset"]
        if payload["kind"] != kind or not isinstance(offset, int) or offset < 0:
            raise ValueError
        return offset
    except Exception as exc:
        raise ValueError("invalid relationship cursor") from exc


class RelationshipApiService:
    """Bounded local relationship reads and guarded relationship mutations.

    All reads return metadata-only projections: never raw event payload JSON,
    source version IDs for deleted/redacted sources, lineage closures, private
    fingerprints, hashes/HMAC, summary/emotion data, or Provider output. A
    bounded preferred address is exposed only while the exact apply remains
    readable and eligible. Source-memory links are returned only when the
    existing Memory API would still return that memory as readable/eligible.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._ledger = RelationshipLedgerRepository(connection)
        self._authority = RelationshipAuthorityService(
            connection,
            ledger=self._ledger,
        )
        self._projector = RelationshipProjector(connection)
        self._projections = RelationshipProjectionRepository(connection)
        self._memories = MemoryRepository(connection)

    # ---- reads ---------------------------------------------------------

    def projection(self) -> RelationshipProjectionView | None:
        return self._projector.current_view()

    def _memory_readable(self, memory_id: str) -> bool:
        memory = self._memories.get(memory_id)
        return memory is not None and memory.status is MemoryStatus.ACTIVE

    def _revoked_ids(self) -> set[str | None]:
        return {
            event.revokes_event_id
            for event in self._ledger.events()
            if event.event_kind is RelationshipEventKind.REVOKE
        }

    def _bounded_address(self, event: RelationshipEvent) -> str | None:
        if (
            event.event_kind is not RelationshipEventKind.APPLY
            or event.event_type is not RelationshipEventType.PREFERRED_ADDRESS
            or event.payload_state is not RelationshipPayloadState.ACTIVE
            or event.payload is None
            or not self._memory_readable(event.source_memory_id)
        ):
            return None
        authority = self._authority.effective(
            source_memory_id=event.source_memory_id,
            event_type=event.event_type,
            subject_code=event.subject_code,
        )
        if authority.suppressed:
            return None
        address = event.payload.get("address")
        if not isinstance(address, str) or not address:
            return None
        return address

    def event_items(self) -> list[dict[str, object]]:
        revoked = self._revoked_ids()
        items: list[dict[str, object]] = []
        for event in self._ledger.events():
            authority = self._authority.effective(
                source_memory_id=event.source_memory_id,
                event_type=event.event_type,
                subject_code=event.subject_code,
            )
            items.append(
                {
                    "id": event.id,
                    "event_kind": event.event_kind.value,
                    "event_type": event.event_type.value,
                    "subject_code": event.subject_code,
                    "payload_state": event.payload_state.value,
                    "address": (
                        self._bounded_address(event)
                        if event.id not in revoked
                        else None
                    ),
                    "source_memory_id": (
                        event.source_memory_id
                        if self._memory_readable(event.source_memory_id)
                        else None
                    ),
                    "revokes_event_id": event.revokes_event_id,
                    "rule_version": event.rule_version,
                    "persona_artifact_id": event.persona_artifact_id,
                    "observed_at": event.observed_at,
                    "created_at": event.created_at,
                    "authority": {
                        "decision_id": authority.decision_id,
                        "generation": authority.generation,
                        "authority_epoch": authority.authority_epoch,
                        "suppressed": authority.suppressed,
                    },
                }
            )
        return items

    def page(
        self,
        items: list[dict[str, object]],
        *,
        limit: int,
        cursor: str | None,
        kind: str,
    ) -> tuple[list[dict[str, object]], str | None]:
        offset = _decode_cursor(cursor, kind=kind)
        window = items[offset : offset + limit]
        has_more = offset + limit < len(items)
        next_cursor = (
            _encode_cursor(offset + len(window), kind=kind) if has_more else None
        )
        return window, next_cursor

    def job_items(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for job in self._ledger.jobs():
            items.append(
                {
                    "id": job.id,
                    "status": job.status.value,
                    "outcome": (
                        job.outcome.value if job.outcome is not None else None
                    ),
                    "source_memory_id": (
                        job.source_memory_id
                        if self._memory_readable(job.source_memory_id)
                        else None
                    ),
                    "captured_event_type": job.captured_event_type.value,
                    "captured_subject_code": job.captured_subject_code,
                    "captured_record_head_version": (
                        job.captured_record_head_version
                    ),
                    "captured_record_generation": job.captured_record_generation,
                    "captured_authority_generation": (
                        job.captured_authority_generation
                    ),
                    "captured_authority_epoch": job.captured_authority_epoch,
                    "attempt_count": job.attempt_count,
                    "reason_code": job.reason_code,
                    "error_category": job.error_category,
                    "relationship_rule_version": job.relationship_rule_version,
                    "persona_artifact_id": job.persona_artifact_id,
                    "created_at": job.created_at,
                    "started_at": job.started_at,
                    "finished_at": job.finished_at,
                }
            )
        return items

    def audit_items(self) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT id, job_id, outcome, reason_code, attempt_count, created_at
            FROM relationship_job_audits
            ORDER BY created_at, id
            """
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "job_id": str(row["job_id"]),
                "outcome": str(row["outcome"]),
                "reason_code": str(row["reason_code"]),
                "attempt_count": int(row["attempt_count"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # ---- mutations -----------------------------------------------------

    def _active_persona_id(self) -> str:
        row = self._connection.execute(
            "SELECT id FROM persona_artifacts WHERE payload_state='active' "
            "ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("relationship API requires an active Persona")
        return str(row["id"])

    def _require_apply(self, apply_event_id: str) -> RelationshipEvent:
        event = self._ledger.event(apply_event_id)
        if (
            event is None
            or event.event_kind is not RelationshipEventKind.APPLY
        ):
            raise ValueError("relationship apply event does not exist")
        return event

    def suppress(
        self,
        *,
        apply_event_id: str,
        expected_decision_id: str | None,
        expected_decision_generation: int,
        expected_authority_epoch: int,
        now: datetime,
    ) -> RelationshipAuthoritySnapshot:
        event = self._require_apply(apply_event_id)
        if event.id in self._revoked_ids():
            raise ValueError("relationship apply event is already revoked")
        with self._ledger.write_transaction():
            snapshot = self._authority.suppress(
                source_memory_id=event.source_memory_id,
                event_type=event.event_type,
                subject_code=event.subject_code,
                action_kind=RelationshipAuthorityActionKind.USER_REVOKE,
                reason_code="user_revoked",
                expected_decision_id=expected_decision_id,
                expected_decision_generation=expected_decision_generation,
                expected_authority_epoch=expected_authority_epoch,
            )
            self._ledger.append_revoke(
                apply_event_id=apply_event_id,
                created_at=now,
                scope_id=event.scope_id,
            )
            self._projector.project(
                persona_artifact_id=self._active_persona_id(),
                computed_at=now,
            )
        return snapshot

    def redact(
        self,
        *,
        apply_event_id: str,
        confirm_irreversible: bool,
        expected_decision_id: str | None,
        expected_decision_generation: int,
        expected_authority_epoch: int,
        now: datetime,
    ) -> RelationshipAuthoritySnapshot:
        if confirm_irreversible is not True:
            raise ValueError("irreversible redaction requires explicit confirmation")
        event = self._require_apply(apply_event_id)
        if event.event_type is not RelationshipEventType.PREFERRED_ADDRESS:
            raise ValueError("only preferred-address applies can be redacted")
        with self._ledger.write_transaction():
            snapshot = self._authority.suppress(
                source_memory_id=event.source_memory_id,
                event_type=event.event_type,
                subject_code=event.subject_code,
                action_kind=RelationshipAuthorityActionKind.PRIVACY_REDACT,
                reason_code="privacy_redact",
                expected_decision_id=expected_decision_id,
                expected_decision_generation=expected_decision_generation,
                expected_authority_epoch=expected_authority_epoch,
            )
            self._ledger.redact_preferred_address(
                apply_event_id=apply_event_id,
                created_at=now,
            )
            self._projector.project(
                persona_artifact_id=self._active_persona_id(),
                computed_at=now,
            )
        return snapshot

    def reenable(
        self,
        *,
        source_memory_id: str,
        event_type: RelationshipEventType,
        subject_code: str,
        expected_decision_id: str | None,
        expected_decision_generation: int,
        expected_authority_epoch: int,
        now: datetime,
    ) -> RelationshipAuthoritySnapshot:
        # The server privately captures and rechecks the inherited fingerprint;
        # it is never accepted from the client or exposed in responses.
        current = self._authority.effective(
            source_memory_id=source_memory_id,
            event_type=event_type,
            subject_code=subject_code,
        )
        if (
            current.decision_id != expected_decision_id
            or current.generation != expected_decision_generation
            or current.authority_epoch != expected_authority_epoch
        ):
            raise StaleRelationshipAuthorityError(
                "relationship authority expectation is stale"
            )
        with self._ledger.write_transaction():
            snapshot = self._authority.reenable(
                source_memory_id=source_memory_id,
                event_type=event_type,
                subject_code=subject_code,
                reason_code="user_reenabled",
                expected_decision_id=expected_decision_id,
                expected_decision_generation=expected_decision_generation,
                expected_authority_epoch=expected_authority_epoch,
                expected_inherited_authority_fingerprint=(
                    current.inherited_authority_fingerprint
                ),
            )
            # Reconcile this memory so a new apply may be derived if the current
            # memory version is still independently eligible and unsuppressed.
            self._reconcile_memory(source_memory_id, now=now)
        return snapshot

    def _reconcile_memory(self, memory_id: str, *, now: datetime) -> None:
        try:
            scheduler = RelationshipScheduler(
                RelationshipReconciler(self._connection),
                persona_artifact_id=self._active_persona_id(),
            )
            scheduler.schedule((memory_id,), created_at=now)
            scheduler.run_pending(now=now)
        except (ValueError, RuntimeError):
            # Convergence is best-effort; chat and projection stay safe.
            pass

    def reconcile(
        self,
        *,
        now: datetime,
        expected_projection_version: int | None = None,
    ) -> tuple[RelationshipReconcileJob, ...]:
        if expected_projection_version is not None:
            current = self._projections.current()
            actual = current.version if current is not None else None
            if actual != expected_projection_version:
                raise ValueError("relationship projection version is stale")
        scheduler = RelationshipScheduler(
            RelationshipReconciler(self._connection),
            persona_artifact_id=self._active_persona_id(),
        )
        return scheduler.full_reconcile(now=now)

    def rebuild(
        self,
        *,
        now: datetime,
        expected_projection_version: int | None = None,
    ) -> tuple[RelationshipReconcileJob, ...]:
        # Full rebuild is an idempotent full reconcile: same semantics, no
        # delta multiply, suppressed keys stay suppressed.
        return self.reconcile(
            now=now,
            expected_projection_version=expected_projection_version,
        )


def relationship_api_now() -> datetime:
    return datetime.now(UTC)
