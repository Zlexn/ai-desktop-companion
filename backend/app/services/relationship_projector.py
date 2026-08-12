from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Iterator

from app.domain.relationship import (
    RelationshipEvent,
    RelationshipEventKind,
    RelationshipEventType,
    RelationshipPayloadState,
    RelationshipProjectionSnapshot,
    RelationshipProjectionView,
    RelationshipSummaryCode,
)
from app.repositories.relationship_ledger import (
    CorruptRelationshipEventError,
    RelationshipLedgerRepository,
)
from app.repositories.relationship_projections import (
    CorruptRelationshipProjectionError,
    RelationshipProjectionRepository,
)
from app.repositories.relationship_sources import RelationshipSourceRepository
from app.services.relationship_authority import RelationshipAuthorityService
from app.services.relationship_contract import (
    FAMILIARITY_BASELINE,
    FAMILIARITY_MAX,
    FAMILIARITY_MIN,
    FAMILIARITY_PER_EVENT_CAP,
    FAMILIARITY_PER_SOURCE_LIFETIME_CAP,
    RELATIONSHIP_EVENT_SCHEMA_VERSION,
    RELATIONSHIP_PROJECTION_RULE_VERSION,
    RELATIONSHIP_RULE_VERSION,
    RELATIONSHIP_SCOPE_ID,
    familiarity_bucket,
    relationship_private_fingerprint,
)
from app.services.relationship_rules import RelationshipRuleSet


class RelationshipProjector:
    """Deterministically folds verified local relationship events."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._ledger = RelationshipLedgerRepository(connection)
        self._projections = RelationshipProjectionRepository(connection)
        self._sources = RelationshipSourceRepository(connection)
        self._authority = RelationshipAuthorityService(
            connection,
            ledger=self._ledger,
        )

    @contextmanager
    def write_transaction(self) -> Iterator[None]:
        with self._projections.write_transaction():
            yield

    def project(
        self,
        *,
        persona_artifact_id: str,
        computed_at: datetime,
        expected_pointer_generation: int | None = None,
    ) -> RelationshipProjectionSnapshot:
        if not self._connection.in_transaction:
            raise RuntimeError("relationship projection requires a write transaction")
        persona_id = self._validated_persona(persona_artifact_id)
        computed_at = _utc_datetime(computed_at)
        effective = self._effective_applies()
        familiarity, address_id, summary, event_ids = self._fold(effective)
        current = self._projections.current()
        semantics = {
            "scope_id": RELATIONSHIP_SCOPE_ID,
            "persona_artifact_id": persona_id,
            "projection_rule_version": RELATIONSHIP_PROJECTION_RULE_VERSION,
            "familiarity": familiarity,
            "preferred_address_event_id": address_id,
            "relationship_summary_code": summary.value,
            "source_relationship_event_ids": list(event_ids),
            "source_emotion_snapshot_id": None,
        }
        if current is not None:
            candidate = replace(
                current,
                persona_artifact_id=persona_id,
                familiarity=familiarity,
                preferred_address_event_id=address_id,
                relationship_summary_code=summary,
                source_relationship_event_ids=event_ids,
            )
            if self._projections.same_semantics(current, candidate):
                return current
        actual_generation = self._projections.pointer_generation()
        if expected_pointer_generation is None:
            expected_pointer_generation = actual_generation
        elif expected_pointer_generation != actual_generation:
            raise ValueError("relationship projection pointer expectation is stale")
        version = self._next_version()
        projection_id = "projection-" + relationship_private_fingerprint(
            {
                "semantics": semantics,
                "version": version,
                "predecessor_projection_id": (
                    current.projection_id if current is not None else None
                ),
            }
        )[:32]
        unsigned = RelationshipProjectionSnapshot(
            projection_id=projection_id,
            version=version,
            scope_id=RELATIONSHIP_SCOPE_ID,
            persona_artifact_id=persona_id,
            projection_rule_version=RELATIONSHIP_PROJECTION_RULE_VERSION,
            familiarity=familiarity,
            preferred_address_event_id=address_id,
            relationship_summary_code=summary,
            source_relationship_event_ids=event_ids,
            source_emotion_snapshot_id=None,
            computed_at=computed_at,
            integrity_fingerprint="0" * 64,
        )
        snapshot = replace(
            unsigned,
            integrity_fingerprint=self._projections.fingerprint(unsigned),
        )
        return self._projections.append_and_activate(
            snapshot=snapshot,
            expected_pointer_generation=actual_generation,
        )

    def current_view(self) -> RelationshipProjectionView | None:
        try:
            snapshot = self._projections.current()
            if snapshot is None or not self._persona_available(
                snapshot.persona_artifact_id
            ):
                return None
            events = {event.id: event for event in self._ledger.events()}
            revoked = {
                event.revokes_event_id
                for event in events.values()
                if event.event_kind is RelationshipEventKind.REVOKE
            }
            if any(
                event_id not in events
                or events[event_id].event_kind is not RelationshipEventKind.APPLY
                for event_id in snapshot.source_relationship_event_ids
            ):
                return None
            expected_events = self._effective_applies()
            expected_familiarity, expected_address_id, expected_summary, expected_ids = (
                self._fold(expected_events)
            )
            if (
                snapshot.familiarity != expected_familiarity
                or snapshot.relationship_summary_code is not expected_summary
                or tuple(
                    event_id
                    for event_id in expected_ids
                    if event_id not in revoked
                )
                != tuple(
                    event_id
                    for event_id in snapshot.source_relationship_event_ids
                    if event_id not in revoked
                )
            ):
                return None
            address = self._resolve_address(snapshot, events)
            if (
                snapshot.preferred_address_event_id is not None
                and snapshot.preferred_address_event_id not in revoked
                and snapshot.preferred_address_event_id != expected_address_id
            ):
                address = None
            return RelationshipProjectionView(
                projection_id=snapshot.projection_id,
                projection_version=snapshot.version,
                familiarity_bucket=familiarity_bucket(snapshot.familiarity),
                preferred_address=address,
                relationship_summary_code=snapshot.relationship_summary_code,
                persona_artifact_id=snapshot.persona_artifact_id,
                projection_rule_version=snapshot.projection_rule_version,
                contributing_event_count=len(snapshot.source_relationship_event_ids),
            )
        except (
            CorruptRelationshipEventError,
            CorruptRelationshipProjectionError,
            sqlite3.DatabaseError,
            TypeError,
            ValueError,
        ):
            return None

    def current_view_or_neutral(
        self,
        *,
        persona_artifact_id: str,
    ) -> RelationshipProjectionView:
        view = self.current_view()
        if view is None or view.persona_artifact_id != persona_artifact_id:
            return self._neutral_view(persona_artifact_id)
        return view

    def project_view_or_neutral(
        self,
        *,
        persona_artifact_id: str,
        computed_at: datetime,
    ) -> RelationshipProjectionView:
        try:
            self.project(
                persona_artifact_id=persona_artifact_id,
                computed_at=computed_at,
            )
            return self.current_view_or_neutral(
                persona_artifact_id=persona_artifact_id
            )
        except (
            CorruptRelationshipEventError,
            CorruptRelationshipProjectionError,
            sqlite3.DatabaseError,
            TypeError,
            ValueError,
        ):
            return self._neutral_view(persona_artifact_id)

    def _effective_applies(self) -> tuple[RelationshipEvent, ...]:
        events = self._ledger.events()
        by_id = {event.id: event for event in events}
        revoked: set[str] = set()
        for event in events:
            if event.event_kind is not RelationshipEventKind.REVOKE:
                continue
            target = by_id.get(event.revokes_event_id or "")
            if target is None or not _revoke_matches_target(event, target):
                raise CorruptRelationshipEventError(
                    "relationship revoke target semantics are invalid"
                )
            revoked.add(target.id)
        effective: list[RelationshipEvent] = []
        for event in events:
            if (
                event.event_kind is not RelationshipEventKind.APPLY
                or event.id in revoked
                or event.payload_state is not RelationshipPayloadState.ACTIVE
            ):
                continue
            if self._event_is_current_eligible(event):
                effective.append(event)
        return tuple(sorted(effective, key=_event_order_key))

    def _event_is_current_eligible(self, event: RelationshipEvent) -> bool:
        if (
            event.scope_id != RELATIONSHIP_SCOPE_ID
            or event.rule_version != RELATIONSHIP_RULE_VERSION
            or event.event_schema_version != RELATIONSHIP_EVENT_SCHEMA_VERSION
        ):
            return False
        authority = self._authority.effective(
            source_memory_id=event.source_memory_id,
            event_type=event.event_type,
            subject_code=event.subject_code,
        )
        source = self._sources.get_current(
            event.source_memory_id,
            authority=authority,
            relationship_rule_version=event.rule_version,
        )
        if source is None or authority.suppressed:
            return False
        mapping = RelationshipRuleSet().map(
            source,
            persona_artifact_id=event.persona_artifact_id,
        )
        return (
            mapping.eligible
            and mapping.event_type is event.event_type
            and mapping.subject_code == event.subject_code
            and mapping.payload is not None
            and dict(mapping.payload) == event.payload
            and source.source_memory_version_id == event.source_memory_version_id
            and source.version_created_at == event.observed_at
        )

    def _event_remains_effective(
        self,
        event: RelationshipEvent,
        events: dict[str, RelationshipEvent],
    ) -> bool:
        if event.event_kind is not RelationshipEventKind.APPLY:
            return False
        if any(
            candidate.event_kind is RelationshipEventKind.REVOKE
            and candidate.revokes_event_id == event.id
            and _revoke_matches_target(candidate, event)
            for candidate in events.values()
        ):
            return False
        return (
            event.payload_state is RelationshipPayloadState.ACTIVE
            and self._event_is_current_eligible(event)
        )

    def _resolve_address(
        self,
        snapshot: RelationshipProjectionSnapshot,
        events: dict[str, RelationshipEvent],
    ) -> str | None:
        event_id = snapshot.preferred_address_event_id
        if event_id is None or event_id not in snapshot.source_relationship_event_ids:
            return None
        event = events.get(event_id)
        if (
            event is None
            or event.event_type is not RelationshipEventType.PREFERRED_ADDRESS
            or not self._event_remains_effective(event, events)
            or event.payload is None
        ):
            return None
        address = event.payload.get("address")
        return address if isinstance(address, str) else None

    @staticmethod
    def _fold(
        events: tuple[RelationshipEvent, ...],
    ) -> tuple[
        float,
        str | None,
        RelationshipSummaryCode,
        tuple[str, ...],
    ]:
        by_source: dict[str, float] = defaultdict(float)
        addresses: list[RelationshipEvent] = []
        event_ids: list[str] = []
        for event in events:
            event_ids.append(event.id)
            if event.event_type is RelationshipEventType.PREFERRED_ADDRESS:
                addresses.append(event)
                continue
            if event.payload is None:
                continue
            delta = event.payload.get("delta")
            if isinstance(delta, bool) or not isinstance(delta, (int, float)):
                raise CorruptRelationshipEventError(
                    "relationship numeric payload is invalid"
                )
            numeric = max(
                -FAMILIARITY_PER_EVENT_CAP,
                min(FAMILIARITY_PER_EVENT_CAP, float(delta)),
            )
            updated = by_source[event.source_memory_id] + numeric
            by_source[event.source_memory_id] = max(
                -FAMILIARITY_PER_SOURCE_LIFETIME_CAP,
                min(FAMILIARITY_PER_SOURCE_LIFETIME_CAP, updated),
            )
        familiarity = max(
            FAMILIARITY_MIN,
            min(FAMILIARITY_MAX, FAMILIARITY_BASELINE + math.fsum(by_source.values())),
        )
        familiarity = round(familiarity, 12)
        bucket = familiarity_bucket(familiarity)
        address_id = max(addresses, key=_event_order_key).id if addresses else None
        return (
            familiarity,
            address_id,
            RelationshipSummaryCode(bucket),
            tuple(event_ids),
        )

    def _next_version(self) -> int:
        row = self._connection.execute(
            "SELECT MAX(version) AS version FROM relationship_projections"
        ).fetchone()
        value = row["version"] if row is not None else None
        if value is None:
            return 1
        if type(value) is not int or value < 1:
            raise CorruptRelationshipProjectionError(
                "relationship projection version is invalid"
            )
        return value + 1

    def _validated_persona(self, persona_artifact_id: str) -> str:
        if not self._persona_available(persona_artifact_id):
            raise ValueError("relationship projection Persona is unavailable")
        return persona_artifact_id

    def _persona_available(self, persona_artifact_id: object) -> bool:
        if not isinstance(persona_artifact_id, str) or not persona_artifact_id:
            return False
        row = self._connection.execute(
            """
            SELECT payload_state, source_content_json, rendered_system_prompt,
                   content_identity_hash, behavior_fingerprint
            FROM persona_artifacts WHERE id = ?
            """,
            (persona_artifact_id,),
        ).fetchone()
        return (
            row is not None
            and row["payload_state"] == "active"
            and isinstance(row["source_content_json"], str)
            and isinstance(row["rendered_system_prompt"], str)
            and _valid_fingerprint(row["content_identity_hash"])
            and _valid_fingerprint(row["behavior_fingerprint"])
        )

    @staticmethod
    def _neutral_view(persona_artifact_id: str) -> RelationshipProjectionView:
        persona_id = persona_artifact_id if isinstance(persona_artifact_id, str) else ""
        return RelationshipProjectionView(
            projection_id="neutral",
            projection_version=0,
            familiarity_bucket=familiarity_bucket(FAMILIARITY_BASELINE),
            preferred_address=None,
            relationship_summary_code=RelationshipSummaryCode.STEADY,
            persona_artifact_id=persona_id,
            projection_rule_version=RELATIONSHIP_PROJECTION_RULE_VERSION,
            contributing_event_count=0,
        )


def _event_order_key(event: RelationshipEvent) -> tuple[object, ...]:
    return (
        event.observed_at,
        event.source_memory_id,
        event.source_memory_version_id,
        event.event_type.value,
        event.subject_code,
        event.id,
    )


def _revoke_matches_target(
    revoke: RelationshipEvent,
    target: RelationshipEvent,
) -> bool:
    return (
        target.event_kind is RelationshipEventKind.APPLY
        and revoke.event_kind is RelationshipEventKind.REVOKE
        and revoke.scope_id == target.scope_id
        and revoke.event_type is target.event_type
        and revoke.subject_code == target.subject_code
        and revoke.source_memory_id == target.source_memory_id
        and revoke.source_memory_version_id == target.source_memory_version_id
        and revoke.observed_at == target.observed_at
        and revoke.rule_version == target.rule_version
        and revoke.persona_artifact_id == target.persona_artifact_id
        and revoke.revokes_event_id == target.id
    )


def _utc_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("relationship projection timestamp must include timezone")
    return value.astimezone(UTC)


def _valid_fingerprint(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
