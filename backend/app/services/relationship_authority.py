from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.relationship import (
    RelationshipAuthorityAction,
    RelationshipAuthorityActionKind,
    RelationshipAuthoritySnapshot,
    RelationshipEventType,
    RelationshipSubjectCode,
)
from app.repositories.relationship_ledger import (
    CorruptRelationshipAuthorityError,
    CorruptRelationshipLineageError,
    RelationshipAuthorityDecisionRecord,
    RelationshipLedgerRepository,
)
from app.services.relationship_contract import (
    RELATIONSHIP_SCOPE_ID,
    relationship_private_fingerprint,
)


class StaleRelationshipAuthorityError(RuntimeError):
    pass


@dataclass(frozen=True)
class _EvaluatedAuthority:
    snapshot: RelationshipAuthoritySnapshot
    own_decision: RelationshipAuthorityDecisionRecord | None


class RelationshipAuthorityService:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        ledger: RelationshipLedgerRepository,
    ) -> None:
        self._connection = connection
        self._ledger = ledger

    def effective(
        self,
        *,
        source_memory_id: str,
        event_type: RelationshipEventType,
        subject_code: RelationshipSubjectCode,
    ) -> RelationshipAuthoritySnapshot:
        self._validate_key(source_memory_id, event_type, subject_code)
        try:
            return self._evaluate(
                source_memory_id=source_memory_id,
                event_type=event_type,
                subject_code=subject_code,
            ).snapshot
        except (CorruptRelationshipAuthorityError, CorruptRelationshipLineageError):
            return self._corrupt_snapshot(
                source_memory_id=source_memory_id,
                event_type=event_type,
                subject_code=subject_code,
            )

    def suppress(
        self,
        *,
        source_memory_id: str,
        event_type: RelationshipEventType,
        subject_code: RelationshipSubjectCode,
        action_kind: RelationshipAuthorityActionKind,
        reason_code: str,
        expected_decision_id: str | None,
        expected_decision_generation: int,
        expected_authority_epoch: int,
    ) -> RelationshipAuthoritySnapshot:
        if action_kind is RelationshipAuthorityActionKind.USER_REENABLE:
            raise ValueError("suppress cannot use user_reenable action kind")
        return self._append(
            source_memory_id=source_memory_id,
            event_type=event_type,
            subject_code=subject_code,
            action=RelationshipAuthorityAction.SUPPRESS,
            action_kind=action_kind,
            reason_code=reason_code,
            expected_decision_id=expected_decision_id,
            expected_decision_generation=expected_decision_generation,
            expected_authority_epoch=expected_authority_epoch,
            expected_inherited_authority_fingerprint=None,
        )

    def reenable(
        self,
        *,
        source_memory_id: str,
        event_type: RelationshipEventType,
        subject_code: RelationshipSubjectCode,
        reason_code: str,
        expected_decision_id: str | None,
        expected_decision_generation: int,
        expected_authority_epoch: int,
        expected_inherited_authority_fingerprint: str | None = None,
    ) -> RelationshipAuthoritySnapshot:
        return self._append(
            source_memory_id=source_memory_id,
            event_type=event_type,
            subject_code=subject_code,
            action=RelationshipAuthorityAction.REENABLE,
            action_kind=RelationshipAuthorityActionKind.USER_REENABLE,
            reason_code=reason_code,
            expected_decision_id=expected_decision_id,
            expected_decision_generation=expected_decision_generation,
            expected_authority_epoch=expected_authority_epoch,
            expected_inherited_authority_fingerprint=(
                expected_inherited_authority_fingerprint
            ),
        )

    def _append(
        self,
        *,
        source_memory_id: str,
        event_type: RelationshipEventType,
        subject_code: RelationshipSubjectCode,
        action: RelationshipAuthorityAction,
        action_kind: RelationshipAuthorityActionKind,
        reason_code: str,
        expected_decision_id: str | None,
        expected_decision_generation: int,
        expected_authority_epoch: int,
        expected_inherited_authority_fingerprint: str | None,
    ) -> RelationshipAuthoritySnapshot:
        self._validate_key(source_memory_id, event_type, subject_code)
        if (
            not isinstance(reason_code, str)
            or not reason_code
            or len(reason_code) > 64
            or any(
                not (character.islower() or character.isdigit() or character == "_")
                for character in reason_code
            )
        ):
            raise ValueError("relationship authority reason code is invalid")
        if (
            type(expected_decision_generation) is not int
            or expected_decision_generation < 0
            or type(expected_authority_epoch) is not int
            or expected_authority_epoch < 0
        ):
            raise ValueError("relationship authority expectations are invalid")
        with self._ledger.write_transaction():
            try:
                evaluated = self._evaluate(
                    source_memory_id=source_memory_id,
                    event_type=event_type,
                    subject_code=subject_code,
                )
            except (CorruptRelationshipAuthorityError, CorruptRelationshipLineageError) as exc:
                raise StaleRelationshipAuthorityError(
                    "relationship authority state is corrupt"
                ) from exc
            current = evaluated.snapshot
            if (
                current.decision_id != expected_decision_id
                or current.generation != expected_decision_generation
                or current.authority_epoch != expected_authority_epoch
                or (
                    expected_inherited_authority_fingerprint is not None
                    and current.inherited_authority_fingerprint
                    != expected_inherited_authority_fingerprint
                )
            ):
                raise StaleRelationshipAuthorityError(
                    "relationship authority expectation is stale"
                )
            decision_id = self._ledger.append_decision(
                source_memory_id=source_memory_id,
                event_type=event_type,
                subject_code=subject_code,
                action=action,
                action_kind=action_kind,
                reason_code=reason_code,
                predecessor_decision_id=current.decision_id,
                generation=current.generation + 1,
                inherited_authority_fingerprint=(
                    current.inherited_authority_fingerprint
                    if action is RelationshipAuthorityAction.REENABLE
                    else None
                ),
                created_at=datetime.now(UTC),
            )
            post = self._evaluate(
                source_memory_id=source_memory_id,
                event_type=event_type,
                subject_code=subject_code,
            ).snapshot
            if post.decision_id != decision_id:
                raise RuntimeError("relationship authority append was not effective")
            return post

    def _evaluate(
        self,
        *,
        source_memory_id: str,
        event_type: RelationshipEventType,
        subject_code: RelationshipSubjectCode,
    ) -> _EvaluatedAuthority:
        graph = self._ledger.lineage_graph(source_memory_id)
        closure = self._ledger.lineage_closure(source_memory_id)
        identities = (source_memory_id, *closure)
        decisions: dict[str, RelationshipAuthorityDecisionRecord | None] = {}
        for memory_id in identities:
            rows = self._ledger.decisions_for_key(
                source_memory_id=memory_id,
                event_type=event_type,
                subject_code=subject_code,
            )
            decisions[memory_id] = rows[-1] if rows else None

        inherited_document = {
            "scope_id": RELATIONSHIP_SCOPE_ID,
            "source_memory_id": source_memory_id,
            "event_type": event_type.value,
            "subject_code": subject_code,
            "lineage_edges": [list(edge) for edge in graph.edges],
            "contributors": [
                {
                    "source_memory_id": memory_id,
                    "decision_id": decisions[memory_id].id
                    if decisions[memory_id]
                    else None,
                    "generation": decisions[memory_id].generation
                    if decisions[memory_id]
                    else 0,
                    "action": decisions[memory_id].action.value
                    if decisions[memory_id]
                    else None,
                }
                for memory_id in closure
            ],
        }
        fingerprint = relationship_private_fingerprint(inherited_document)
        own = decisions[source_memory_id]
        inherited_suppressed = any(
            decisions[memory_id] is not None
            and decisions[memory_id].action is RelationshipAuthorityAction.SUPPRESS
            for memory_id in closure
        )
        if own is not None and own.action is RelationshipAuthorityAction.SUPPRESS:
            suppressed = True
        elif (
            own is not None
            and own.action is RelationshipAuthorityAction.REENABLE
            and own.inherited_authority_fingerprint == fingerprint
        ):
            suppressed = False
        elif inherited_suppressed:
            suppressed = True
        else:
            suppressed = False
        epoch = self._ledger.authority_epoch()
        return _EvaluatedAuthority(
            snapshot=RelationshipAuthoritySnapshot(
                scope_id=RELATIONSHIP_SCOPE_ID,
                source_memory_id=source_memory_id,
                event_type=event_type,
                subject_code=subject_code,
                decision_id=own.id if own else None,
                generation=own.generation if own else 0,
                action=own.action if own else None,
                authority_epoch=epoch,
                inherited_authority_fingerprint=fingerprint,
                suppressed=suppressed,
            ),
            own_decision=own,
        )

    def _corrupt_snapshot(
        self,
        *,
        source_memory_id: str,
        event_type: RelationshipEventType,
        subject_code: RelationshipSubjectCode,
    ) -> RelationshipAuthoritySnapshot:
        try:
            epoch = self._ledger.authority_epoch()
        except CorruptRelationshipAuthorityError:
            epoch = 0
        fingerprint = relationship_private_fingerprint(
            {
                "scope_id": RELATIONSHIP_SCOPE_ID,
                "source_memory_id": source_memory_id,
                "event_type": event_type.value,
                "subject_code": subject_code,
                "state": "corrupt_fail_closed",
            }
        )
        return RelationshipAuthoritySnapshot(
            scope_id=RELATIONSHIP_SCOPE_ID,
            source_memory_id=source_memory_id,
            event_type=event_type,
            subject_code=subject_code,
            decision_id=None,
            generation=0,
            action=None,
            authority_epoch=epoch,
            inherited_authority_fingerprint=fingerprint,
            suppressed=True,
        )

    @staticmethod
    def _validate_key(
        source_memory_id: str,
        event_type: RelationshipEventType,
        subject_code: RelationshipSubjectCode,
    ) -> None:
        if (
            not isinstance(source_memory_id, str)
            or not source_memory_id
            or type(event_type) is not RelationshipEventType
            or event_type.value != subject_code
        ):
            raise ValueError("relationship authority semantic key is invalid")
