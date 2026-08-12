from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Callable
from uuid import uuid4

from app.core.config import Settings
from app.domain.session_summary import (
    SummaryJob,
    SummaryJobKind,
    SummaryJobStatus,
    SummarySnapshotMessage,
    SummarySnapshotTurn,
    SummarySourceSnapshot,
    SummarySuppression,
    SummarySuppressionState,
)
from app.domain.models import ChatRole
from app.repositories.sqlite import managed_connection
from app.repositories.summary_automation import (
    SummaryAutomationRepository,
    authorize_suppression_transition,
    clear_suppression_transition_guard,
)
from app.services.session_summary_contract import (
    SUMMARY_SCHEMA_VERSION,
    canonical_summary_source_set_hash,
)
from app.services.session_summary_service import (
    build_summary_processing_policy,
    summary_provider_policy_for_settings,
)
from app.services.summary_invalidation import SummaryInvalidationService


class SummaryRebuildService:
    def __init__(
        self,
        database_url: str,
        *,
        settings: Settings,
        session_deletion_generation: Callable[[str], int] | None = None,
    ) -> None:
        self._database_url = database_url
        self._settings = settings
        self._session_deletion_generation = session_deletion_generation or (
            lambda _session_id: 0
        )

    def authorize(
        self,
        *,
        summary_id: str,
        expected_suppression_generation: int,
    ) -> SummarySuppression:
        with managed_connection(self._database_url) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                summary = SummaryInvalidationService._require_exact_summary(
                    connection,
                    summary_id,
                )
                if summary.payload_state != "redacted":
                    raise ValueError("redacted exact summary is required")
                row = connection.execute(
                    "SELECT * FROM summary_source_suppressions "
                    "WHERE session_id=? AND source_set_hash=?",
                    (summary.session_id, summary.source_set_hash),
                ).fetchone()
                if row is None or str(row["state"]) != "suppressed":
                    raise ValueError("summary source set is not suppressed")
                if int(row["generation"]) != expected_suppression_generation:
                    raise ValueError("suppression generation conflict")
                permit_id = str(uuid4())
                generation = expected_suppression_generation + 1
                now = datetime.now(UTC).isoformat()
                authorize_suppression_transition(
                    connection,
                    session_id=summary.session_id,
                    source_set_hash=summary.source_set_hash,
                    expected_generation=expected_suppression_generation,
                    target_generation=generation,
                    target_state="rebuild_authorized",
                )
                cursor = connection.execute(
                    """
                    UPDATE summary_source_suppressions
                    SET generation=?, state='rebuild_authorized',
                        rebuild_permit_id=?, bound_job_id=NULL,
                        authorized_summary_id=?,
                        reason_code='explicit_rebuild_authorized', updated_at=?
                    WHERE session_id=? AND source_set_hash=? AND generation=?
                      AND state='suppressed'
                    """,
                    (
                        generation,
                        permit_id,
                        summary.id,
                        now,
                        summary.session_id,
                        summary.source_set_hash,
                        expected_suppression_generation,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("suppression changed during authorization")
                clear_suppression_transition_guard(
                    connection,
                    session_id=summary.session_id,
                    source_set_hash=summary.source_set_hash,
                )
                SummaryInvalidationService._audit(
                    connection,
                    session_id=summary.session_id,
                    generation=generation,
                    state="rebuild_authorized",
                    reason_code="explicit_rebuild_authorized",
                    created_at=now,
                )
                updated = self._permit_row(connection, permit_id)
                connection.commit()
                return SummaryInvalidationService._from_row(updated)
            except BaseException:
                connection.rollback()
                raise

    def reserve(self, permit_id: str) -> tuple[SummaryJob, bool]:
        with managed_connection(self._database_url) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                suppression = self._permit_row(connection, permit_id)
                if str(suppression["state"]) == "rebuild_in_progress":
                    bound_id = suppression["bound_job_id"]
                    if bound_id is None:
                        raise ValueError("rebuild permit binding is corrupt")
                    job = SummaryAutomationRepository(connection).require_job(
                        str(bound_id)
                    )
                    connection.commit()
                    return job, False
                if str(suppression["state"]) != "rebuild_authorized":
                    raise ValueError("rebuild permit is not authorized")
                authorized_summary_id = suppression["authorized_summary_id"]
                if authorized_summary_id is None:
                    raise ValueError("rebuild permit source summary is unavailable")
                summary = connection.execute(
                    """
                    SELECT * FROM session_summaries
                    WHERE id=? AND session_id=? AND source_set_hash=?
                      AND payload_state='redacted' AND provenance_state='exact'
                    """,
                    (
                        str(authorized_summary_id),
                        str(suppression["session_id"]),
                        str(suppression["source_set_hash"]),
                    ),
                ).fetchone()
                if summary is None:
                    raise ValueError("rebuild permit source summary is unavailable")
                snapshot = self._safe_snapshot(
                    connection,
                    summary_id=str(summary["id"]),
                    session_id=str(summary["session_id"]),
                )
                if snapshot.source_turn_count < self._settings.summary_rebuild_min_safe_turns:
                    raise ValueError("safe complete turns are below the rebuild minimum")
                policy = build_summary_processing_policy(self._settings)
                authority = SummaryAutomationRepository(
                    connection
                ).valid_processing_snapshot(policy)
                if authority is None:
                    raise ValueError("processing authority is required for rebuild")
                route = (
                    "fake"
                    if self._settings.session_summary_provider == "fake"
                    else "remote"
                )
                repository = SummaryAutomationRepository(
                    connection,
                    adopt_transaction=True,
                )
                job, created = repository.reserve_job(
                    snapshot=snapshot,
                    job_kind=SummaryJobKind.REBUILD,
                    route=route,
                    provider=(
                        self._settings.session_summary_llm_provider
                        if route == "remote"
                        else None
                    ),
                    model=(
                        self._settings.session_summary_llm_model
                        if route == "remote"
                        else None
                    ),
                    summarizer_schema_version=SUMMARY_SCHEMA_VERSION,
                    processing_consent_generation=authority.generation,
                    processing_policy_fingerprint=authority.policy_fingerprint,
                    provider_policy_fingerprint=summary_provider_policy_for_settings(
                        self._settings
                    ),
                    session_deletion_generation=self._session_deletion_generation(
                        str(suppression["session_id"])
                    ),
                    suppression_generation=int(suppression["generation"]) + 1,
                    rebuild_authorization_generation=int(suppression["generation"]),
                    rebuild_permit_id=permit_id,
                    source_summary_id=str(summary["id"]),
                )
                generation = int(suppression["generation"]) + 1
                now = datetime.now(UTC).isoformat()
                authorize_suppression_transition(
                    connection,
                    session_id=str(suppression["session_id"]),
                    source_set_hash=str(suppression["source_set_hash"]),
                    expected_generation=int(suppression["generation"]),
                    target_generation=generation,
                    target_state="rebuild_in_progress",
                )
                cursor = connection.execute(
                    """
                    UPDATE summary_source_suppressions
                    SET generation=?, state='rebuild_in_progress', bound_job_id=?,
                        reason_code='rebuild_job_bound', updated_at=?
                    WHERE rebuild_permit_id=? AND generation=?
                      AND state='rebuild_authorized' AND bound_job_id IS NULL
                    """,
                    (
                        generation,
                        job.id,
                        now,
                        permit_id,
                        int(suppression["generation"]),
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("rebuild permit changed during binding")
                clear_suppression_transition_guard(
                    connection,
                    session_id=str(suppression["session_id"]),
                    source_set_hash=str(suppression["source_set_hash"]),
                )
                SummaryInvalidationService._audit(
                    connection,
                    session_id=str(suppression["session_id"]),
                    generation=generation,
                    state="rebuild_in_progress",
                    reason_code="rebuild_job_bound",
                    created_at=now,
                )
                connection.commit()
                return job, created
            except BaseException:
                connection.rollback()
                raise

    def retry(
        self,
        *,
        job_id: str,
        expected_job_status: SummaryJobStatus,
        expected_suppression_generation: int,
        expected_suppression_state: SummarySuppressionState,
    ) -> tuple[SummaryJob, SummarySuppression]:
        if expected_job_status not in {
            SummaryJobStatus.FAILED,
            SummaryJobStatus.CANCELLED,
            SummaryJobStatus.SKIPPED,
        }:
            raise ValueError("rebuild job is not retryable")
        if expected_suppression_state not in {
            SummarySuppressionState.SUPPRESSED,
            SummarySuppressionState.REBUILD_IN_PROGRESS,
        }:
            raise ValueError("rebuild suppression state is not retryable")

        with managed_connection(self._database_url) as connection:
            repository = SummaryAutomationRepository(connection)
            job = repository.require_job(job_id)
            if (
                job.job_kind is not SummaryJobKind.REBUILD
                or job.status is not expected_job_status
                or job.source_summary_id is None
            ):
                raise ValueError("rebuild job snapshot changed")
            if repository.valid_processing_snapshot(
                build_summary_processing_policy(self._settings)
            ) is None:
                raise ValueError("processing authority is required for rebuild")
            summary = SummaryInvalidationService._require_exact_summary(
                connection,
                job.source_summary_id,
            )
            row = connection.execute(
                "SELECT * FROM summary_source_suppressions "
                "WHERE session_id=? AND source_set_hash=?",
                (summary.session_id, summary.source_set_hash),
            ).fetchone()
            if (
                row is None
                or int(row["generation"]) != expected_suppression_generation
                or str(row["state"]) != expected_suppression_state.value
            ):
                raise ValueError("rebuild suppression snapshot changed")
            if expected_suppression_state is SummarySuppressionState.REBUILD_IN_PROGRESS:
                if (
                    row["rebuild_permit_id"] != job.rebuild_permit_id
                    or row["bound_job_id"] != job.id
                ):
                    raise ValueError("rebuild permit binding changed")
                permit_id = str(row["rebuild_permit_id"])
            else:
                if expected_job_status is not SummaryJobStatus.CANCELLED:
                    raise ValueError("only a cancelled rebuild may retry from suppressed")
                permit_id = None

        if permit_id is not None:
            suppressed = self.cancel(
                permit_id,
                expected_suppression_generation=expected_suppression_generation,
            )
        else:
            suppressed = SummaryInvalidationService._from_row(row)

        authorized = self.authorize(
            summary_id=job.source_summary_id,
            expected_suppression_generation=suppressed.generation,
        )
        try:
            retried, created = self.reserve(authorized.permit_id)
        except BaseException:
            self.cancel(
                authorized.permit_id,
                expected_suppression_generation=authorized.generation,
            )
            raise
        if not created or retried.id == job.id:
            raise RuntimeError("fresh rebuild permit did not create a new job")
        with managed_connection(self._database_url) as connection:
            current = self._permit_row(connection, authorized.permit_id)
            return retried, SummaryInvalidationService._from_row(current)

    def cancel(
        self,
        permit_id: str,
        *,
        expected_suppression_generation: int,
    ) -> SummarySuppression:
        with managed_connection(self._database_url) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._permit_row(connection, permit_id)
                if int(row["generation"]) != expected_suppression_generation:
                    raise ValueError("suppression generation conflict")
                job_id = row["bound_job_id"]
                if job_id is not None:
                    SummaryAutomationRepository(
                        connection,
                        adopt_transaction=True,
                    ).cancel_job(str(job_id))
                generation = expected_suppression_generation + 1
                now = datetime.now(UTC).isoformat()
                authorize_suppression_transition(
                    connection,
                    session_id=str(row["session_id"]),
                    source_set_hash=str(row["source_set_hash"]),
                    expected_generation=expected_suppression_generation,
                    target_generation=generation,
                    target_state="suppressed",
                )
                cursor = connection.execute(
                    """
                    UPDATE summary_source_suppressions
                    SET generation=?, state='suppressed', rebuild_permit_id=NULL,
                        bound_job_id=NULL, authorized_summary_id=NULL,
                        reason_code='rebuild_cancelled', updated_at=?
                    WHERE rebuild_permit_id=? AND generation=?
                    """,
                    (generation, now, permit_id, expected_suppression_generation),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("rebuild permit changed during cancellation")
                clear_suppression_transition_guard(
                    connection,
                    session_id=str(row["session_id"]),
                    source_set_hash=str(row["source_set_hash"]),
                )
                SummaryInvalidationService._audit(
                    connection,
                    session_id=str(row["session_id"]),
                    generation=generation,
                    state="suppressed",
                    reason_code="rebuild_cancelled",
                    created_at=now,
                )
                updated = connection.execute(
                    "SELECT * FROM summary_source_suppressions WHERE session_id=? "
                    "AND source_set_hash=?",
                    (str(row["session_id"]), str(row["source_set_hash"])),
                ).fetchone()
                assert updated is not None
                connection.commit()
                return SummaryInvalidationService._from_row(updated)
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _permit_row(connection, permit_id: str):
        row = connection.execute(
            "SELECT * FROM summary_source_suppressions WHERE rebuild_permit_id=?",
            (permit_id,),
        ).fetchone()
        if row is None:
            raise ValueError("rebuild permit does not match a source set")
        return row

    @staticmethod
    def _safe_snapshot(
        connection,
        *,
        summary_id: str,
        session_id: str,
    ) -> SummarySourceSnapshot:
        rows = connection.execute(
            """
            SELECT source.chat_turn_id, source.turn_order,
                   user_message.id AS user_id, user_message.content AS user_content,
                   assistant_message.id AS assistant_id,
                   assistant_message.content AS assistant_content
            FROM session_summary_sources AS source
            JOIN chat_turns AS turn ON turn.id=source.chat_turn_id
            JOIN messages AS user_message ON user_message.id=turn.user_message_id
            JOIN messages AS assistant_message
              ON assistant_message.id=turn.assistant_message_id
            WHERE source.summary_id=? AND source.message_order_in_turn=0
              AND turn.session_id=?
              AND NOT EXISTS (
                  SELECT 1 FROM memory_summary_source_exclusions AS excluded
                  WHERE excluded.source_message_id IN (
                      turn.user_message_id, turn.assistant_message_id
                  )
              )
            ORDER BY source.turn_order, source.chat_turn_id
            """,
            (summary_id, session_id),
        ).fetchall()
        turns = tuple(
            SummarySnapshotTurn(
                id=str(row["chat_turn_id"]),
                turn_order=int(row["turn_order"]),
                messages=(
                    SummarySnapshotMessage(
                        id=str(row["user_id"]),
                        role=ChatRole.USER,
                        content=str(row["user_content"]),
                        message_order_in_turn=0,
                    ),
                    SummarySnapshotMessage(
                        id=str(row["assistant_id"]),
                        role=ChatRole.ASSISTANT,
                        content=str(row["assistant_content"]),
                        message_order_in_turn=1,
                    ),
                ),
            )
            for row in rows
        )
        barrier = connection.execute(
            "SELECT generation FROM memory_summary_barrier WHERE singleton_id=1"
        ).fetchone()
        assert barrier is not None
        source_hash = (
            canonical_summary_source_set_hash(
                session_id=session_id,
                turns=tuple(
                    {
                        "turn_id": turn.id,
                        "turn_order": turn.turn_order,
                        "messages": tuple(
                            {
                                "message_id": message.id,
                                "message_order_in_turn": (
                                    message.message_order_in_turn
                                ),
                            }
                            for message in turn.messages
                        ),
                    }
                    for turn in turns
                ),
            )
            if turns
            else None
        )
        return SummarySourceSnapshot(
            session_id=session_id,
            barrier_generation=int(barrier["generation"]),
            candidate_turn_count=len(turns),
            source_character_count=sum(
                len(message.content)
                for turn in turns
                for message in turn.messages
            ),
            turns=turns,
            source_set_hash=source_hash,
        )
