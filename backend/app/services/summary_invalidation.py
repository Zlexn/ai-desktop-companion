from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.session_summary import SummarySuppression, SummarySuppressionState
from app.repositories.summary_automation import (
    authorize_suppression_transition,
    clear_suppression_transition_guard,
)
from app.repositories.sqlite import managed_connection
from app.services.session_summary_contract import canonical_summary_source_set_hash


@dataclass(frozen=True)
class _SummaryIdentity:
    id: str
    session_id: str
    source_set_hash: str
    payload_state: str


class SummaryInvalidationPrimitive:
    def __init__(
        self,
        connection,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._connection = connection
        self._fault_injector = fault_injector

    def invalidate_for_true_forget(
        self,
        message_ids: set[str],
        *,
        now: datetime,
    ) -> int:
        existing_ids = {
            str(row["source_message_id"])
            for row in self._connection.execute(
                "SELECT source_message_id "
                "FROM memory_summary_source_exclusions"
            ).fetchall()
        }
        closed_ids = self._complete_turn_message_ids(message_ids | existing_ids)
        self._insert_exclusions(closed_ids, now=now)
        self._checkpoint("summary_exclusions")
        barrier = self._increment_barrier()
        self._checkpoint("summary_barrier")

        affected = self._affected_summaries(closed_ids)
        affected_ids = {str(row["id"]) for row in affected}
        for row in affected:
            self._redact_summary(row, now=now)
        self._checkpoint("summary_payloads")
        self._suppress_rows(affected, now=now)
        self._suppress_exact_identities_for_messages(closed_ids, now=now)
        self._checkpoint("summary_suppressions")

        safe_exact = self._safe_exact_summaries(
            excluded_summary_ids=affected_ids,
            excluded_message_ids=closed_ids,
        )
        for row in safe_exact:
            self._revalidate_exact(row, barrier=barrier, now=now)
        self._redact_unsafe_remaining(
            excluded_summary_ids=affected_ids,
            safe_summary_ids={str(row["id"]) for row in safe_exact},
            now=now,
        )
        self._checkpoint("summary_revalidation")
        return barrier

    def _complete_turn_message_ids(self, message_ids: set[str]) -> set[str]:
        closed = set(message_ids)
        if not message_ids:
            return closed
        ordered = sorted(message_ids)
        placeholders = ", ".join("?" for _ in ordered)
        rows = self._connection.execute(
            f"""
            SELECT user_message_id, assistant_message_id
            FROM chat_turns
            WHERE user_message_id IN ({placeholders})
               OR assistant_message_id IN ({placeholders})
            """,
            (*ordered, *ordered),
        ).fetchall()
        for row in rows:
            closed.add(str(row["user_message_id"]))
            closed.add(str(row["assistant_message_id"]))
        return closed

    def _insert_exclusions(
        self,
        message_ids: set[str],
        *,
        now: datetime,
    ) -> None:
        self._connection.executemany(
            """
            INSERT INTO memory_summary_source_exclusions (
                source_message_id, reason_code, created_at
            ) VALUES (?, 'memory_true_forget', ?)
            ON CONFLICT(source_message_id) DO NOTHING
            """,
            [
                (message_id, now.isoformat())
                for message_id in sorted(message_ids)
            ],
        )

    def _increment_barrier(self) -> int:
        row = self._connection.execute(
            """
            UPDATE memory_summary_barrier
            SET generation=generation+1
            WHERE singleton_id=1
            RETURNING generation
            """
        ).fetchone()
        if row is None:
            raise RuntimeError("memory summary barrier update failed")
        return int(row["generation"])

    def _affected_summaries(self, message_ids: set[str]):
        if not message_ids:
            return []
        ordered = sorted(message_ids)
        placeholders = ", ".join("?" for _ in ordered)
        return self._connection.execute(
            f"""
            SELECT DISTINCT summary.*
            FROM session_summaries AS summary
            JOIN session_summary_sources AS source
              ON source.summary_id=summary.id
            WHERE source.message_id IN ({placeholders})
              AND summary.payload_state='active'
            ORDER BY summary.id
            """,
            ordered,
        ).fetchall()

    def _redact_summary(self, row, *, now: datetime) -> None:
        summary_id = str(row["id"])
        self._connection.execute(
            "INSERT INTO summary_redaction_guards (summary_id) VALUES (?)",
            (summary_id,),
        )
        cursor = self._connection.execute(
            """
            UPDATE session_summaries
            SET summary_text=NULL, payload_state='redacted',
                redacted_at=?, redaction_reason_code='memory_true_forget',
                updated_at=?
            WHERE id=? AND payload_state='active'
            """,
            (now.isoformat(), now.isoformat(), summary_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("summary payload changed during true forget")
        self._connection.execute(
            "DELETE FROM summary_redaction_guards WHERE summary_id=?",
            (summary_id,),
        )
        self._payload_audit(summary_id, now=now)

    def _suppress_exact_identities_for_messages(
        self,
        message_ids: set[str],
        *,
        now: datetime,
    ) -> None:
        if not message_ids:
            return
        ordered = sorted(message_ids)
        placeholders = ", ".join("?" for _ in ordered)
        rows = self._connection.execute(
            f"""
            SELECT DISTINCT summary.*
            FROM session_summaries AS summary
            JOIN session_summary_sources AS source
              ON source.summary_id=summary.id
            WHERE source.message_id IN ({placeholders})
              AND summary.provenance_state='exact'
              AND summary.source_set_hash IS NOT NULL
            ORDER BY summary.id
            """,
            ordered,
        ).fetchall()
        self._suppress_rows(rows, now=now)

    def _suppress_rows(self, rows, *, now: datetime) -> None:
        seen: set[tuple[str, str]] = set()
        for row in rows:
            if row["source_set_hash"] is None:
                continue
            identity = (str(row["session_id"]), str(row["source_set_hash"]))
            if identity in seen:
                continue
            seen.add(identity)
            existing = self._connection.execute(
                "SELECT state, reason_code FROM summary_source_suppressions "
                "WHERE session_id=? AND source_set_hash=?",
                identity,
            ).fetchone()
            if (
                existing is not None
                and str(existing["state"]) == "suppressed"
                and str(existing["reason_code"]) == "memory_true_forget"
            ):
                continue
            self._suppress_source_set(row, now=now)

    def _suppress_source_set(self, row, *, now: datetime) -> None:
        session_id = str(row["session_id"])
        source_set_hash = str(row["source_set_hash"])
        existing = self._connection.execute(
            "SELECT generation FROM summary_source_suppressions "
            "WHERE session_id=? AND source_set_hash=?",
            (session_id, source_set_hash),
        ).fetchone()
        generation = int(existing["generation"]) if existing is not None else 0
        next_generation = generation + 1
        if existing is None:
            self._connection.execute(
                """
                INSERT INTO summary_source_suppressions (
                    session_id, source_set_hash, generation, state,
                    rebuild_permit_id, bound_job_id, authorized_summary_id,
                    reason_code, created_at, updated_at
                ) VALUES (?, ?, ?, 'suppressed', NULL, NULL, NULL,
                          'memory_true_forget', ?, ?)
                """,
                (
                    session_id,
                    source_set_hash,
                    next_generation,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        else:
            authorize_suppression_transition(
                self._connection,
                session_id=session_id,
                source_set_hash=source_set_hash,
                expected_generation=generation,
                target_generation=next_generation,
                target_state="suppressed",
            )
            cursor = self._connection.execute(
                """
                UPDATE summary_source_suppressions
                SET generation=?, state='suppressed', rebuild_permit_id=NULL,
                    bound_job_id=NULL, authorized_summary_id=NULL,
                    reason_code='memory_true_forget', updated_at=?
                WHERE session_id=? AND source_set_hash=? AND generation=?
                """,
                (
                    next_generation,
                    now.isoformat(),
                    session_id,
                    source_set_hash,
                    generation,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("summary suppression changed during true forget")
            clear_suppression_transition_guard(
                self._connection,
                session_id=session_id,
                source_set_hash=source_set_hash,
            )
        SummaryInvalidationService._audit(
            self._connection,
            session_id=session_id,
            generation=next_generation,
            state="suppressed",
            reason_code="memory_true_forget",
            created_at=now.isoformat(),
        )

    def _safe_exact_summaries(
        self,
        *,
        excluded_summary_ids: set[str],
        excluded_message_ids: set[str],
    ):
        rows = self._connection.execute(
            "SELECT * FROM session_summaries "
            "WHERE payload_state='active' AND provenance_state='exact' "
            "ORDER BY id"
        ).fetchall()
        return [
            row
            for row in rows
            if str(row["id"]) not in excluded_summary_ids
            and self._exact_source_map_is_safe(
                row,
                excluded_message_ids=excluded_message_ids,
            )
        ]

    def _exact_source_map_is_safe(
        self,
        row,
        *,
        excluded_message_ids: set[str],
    ) -> bool:
        sources = self._connection.execute(
            """
            SELECT source.chat_turn_id, source.message_id, source.turn_order,
                   source.message_order_in_turn, source.source_order,
                   turn.user_message_id, turn.assistant_message_id
            FROM session_summary_sources AS source
            JOIN chat_turns AS turn ON turn.id=source.chat_turn_id
            WHERE source.summary_id=? AND turn.session_id=?
            ORDER BY source.source_order
            """,
            (str(row["id"]), str(row["session_id"])),
        ).fetchall()
        if not sources or len(sources) % 2:
            return False
        turns = []
        for index in range(0, len(sources), 2):
            user = sources[index]
            assistant = sources[index + 1]
            if (
                int(user["source_order"]) != index
                or int(assistant["source_order"]) != index + 1
                or str(user["chat_turn_id"]) != str(assistant["chat_turn_id"])
                or int(user["turn_order"]) != int(assistant["turn_order"])
                or int(user["message_order_in_turn"]) != 0
                or int(assistant["message_order_in_turn"]) != 1
                or str(user["message_id"]) != str(user["user_message_id"])
                or str(assistant["message_id"])
                != str(assistant["assistant_message_id"])
                or str(user["message_id"]) in excluded_message_ids
                or str(assistant["message_id"]) in excluded_message_ids
            ):
                return False
            turns.append(
                {
                    "turn_id": str(user["chat_turn_id"]),
                    "turn_order": int(user["turn_order"]),
                    "messages": (
                        {
                            "message_id": str(user["message_id"]),
                            "message_order_in_turn": 0,
                        },
                        {
                            "message_id": str(assistant["message_id"]),
                            "message_order_in_turn": 1,
                        },
                    ),
                }
            )
        return str(row["source_set_hash"]) == canonical_summary_source_set_hash(
            session_id=str(row["session_id"]),
            turns=tuple(turns),
        )

    def _revalidate_exact(self, row, *, barrier: int, now: datetime) -> None:
        cursor = self._connection.execute(
            """
            UPDATE session_summaries
            SET observed_memory_summary_barrier=?, updated_at=?
            WHERE id=? AND payload_state='active' AND provenance_state='exact'
            """,
            (barrier, now.isoformat(), str(row["id"])),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("summary changed during barrier revalidation")
        self._connection.execute(
            """
            INSERT INTO summary_payload_audits (
                id, summary_id, action, payload_state,
                reason_code, created_at
            ) VALUES (lower(hex(randomblob(16))), ?, 'revalidated',
                      'active', 'memory_true_forget_safe_revalidation', ?)
            """,
            (str(row["id"]), now.isoformat()),
        )

    def _redact_unsafe_remaining(
        self,
        *,
        excluded_summary_ids: set[str],
        safe_summary_ids: set[str],
        now: datetime,
    ) -> None:
        rows = self._connection.execute(
            "SELECT * FROM session_summaries WHERE payload_state='active' ORDER BY id"
        ).fetchall()
        unsafe_rows = []
        for row in rows:
            summary_id = str(row["id"])
            if summary_id in excluded_summary_ids or summary_id in safe_summary_ids:
                continue
            self._redact_summary(row, now=now)
            unsafe_rows.append(row)
        self._suppress_rows(unsafe_rows, now=now)

    def _payload_audit(self, summary_id: str, *, now: datetime) -> None:
        self._connection.execute(
            """
            INSERT INTO summary_payload_audits (
                id, summary_id, action, payload_state,
                reason_code, created_at
            ) VALUES (lower(hex(randomblob(16))), ?, 'redacted',
                      'redacted', 'memory_true_forget', ?)
            """,
            (summary_id, now.isoformat()),
        )

    def _checkpoint(self, name: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(name)


class SummaryInvalidationService:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def redact_summary(
        self,
        summary_id: str,
        *,
        expected_suppression_generation: int,
        confirmation: str,
    ) -> SummarySuppression:
        if confirmation != "redact_summary_payload":
            raise ValueError("explicit redaction confirmation is required")
        if expected_suppression_generation < 0:
            raise ValueError("suppression generation must be non-negative")
        with managed_connection(self._database_url) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                summary = self._require_exact_summary(connection, summary_id)
                existing = connection.execute(
                    "SELECT * FROM summary_source_suppressions "
                    "WHERE session_id=? AND source_set_hash=?",
                    (summary.session_id, summary.source_set_hash),
                ).fetchone()
                current_generation = int(existing["generation"]) if existing else 0
                if current_generation != expected_suppression_generation:
                    raise ValueError("suppression generation conflict")
                active_summary_ids = tuple(
                    str(row["id"])
                    for row in connection.execute(
                        "SELECT id FROM session_summaries "
                        "WHERE session_id=? AND source_set_hash=? "
                        "AND provenance_state='exact' AND payload_state='active' "
                        "ORDER BY id",
                        (summary.session_id, summary.source_set_hash),
                    ).fetchall()
                )
                if (
                    existing is not None
                    and str(existing["state"]) == "suppressed"
                    and not active_summary_ids
                ):
                    connection.commit()
                    return self._from_row(existing)

                now = datetime.now(UTC).isoformat()
                generation = current_generation + 1
                for active_summary_id in active_summary_ids:
                    connection.execute(
                        "INSERT INTO summary_redaction_guards (summary_id) VALUES (?)",
                        (active_summary_id,),
                    )
                    cursor = connection.execute(
                        """
                        UPDATE session_summaries
                        SET summary_text=NULL, payload_state='redacted',
                            redacted_at=?, redaction_reason_code=?, updated_at=?
                        WHERE id=? AND payload_state='active'
                          AND provenance_state='exact'
                        """,
                        (
                            now,
                            "user_privacy_redaction",
                            now,
                            active_summary_id,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError("summary payload changed during redaction")
                    connection.execute(
                        "DELETE FROM summary_redaction_guards WHERE summary_id=?",
                        (active_summary_id,),
                    )
                    connection.execute(
                        """
                        INSERT INTO summary_payload_audits (
                            id, summary_id, action, payload_state,
                            reason_code, created_at
                        ) VALUES (lower(hex(randomblob(16))), ?, 'redacted',
                                  'redacted', ?, ?)
                        """,
                        (
                            active_summary_id,
                            "user_privacy_redaction",
                            now,
                        ),
                    )
                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO summary_source_suppressions (
                            session_id, source_set_hash, generation, state,
                            rebuild_permit_id, bound_job_id,
                            authorized_summary_id, reason_code,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, 'suppressed', NULL, NULL, NULL, ?, ?, ?)
                        """,
                        (
                            summary.session_id,
                            summary.source_set_hash,
                            generation,
                            "user_privacy_redaction",
                            now,
                            now,
                        ),
                    )
                else:
                    authorize_suppression_transition(
                        connection,
                        session_id=summary.session_id,
                        source_set_hash=summary.source_set_hash,
                        expected_generation=current_generation,
                        target_generation=generation,
                        target_state="suppressed",
                    )
                    cursor = connection.execute(
                        """
                        UPDATE summary_source_suppressions
                        SET generation=?, state='suppressed', rebuild_permit_id=NULL,
                            bound_job_id=NULL, authorized_summary_id=NULL,
                            reason_code=?, updated_at=?
                        WHERE session_id=? AND source_set_hash=? AND generation=?
                        """,
                        (
                            generation,
                            "user_privacy_redaction",
                            now,
                            summary.session_id,
                            summary.source_set_hash,
                            current_generation,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError("suppression changed during redaction")
                    clear_suppression_transition_guard(
                        connection,
                        session_id=summary.session_id,
                        source_set_hash=summary.source_set_hash,
                    )
                self._audit(
                    connection,
                    session_id=summary.session_id,
                    generation=generation,
                    state="suppressed",
                    reason_code="user_privacy_redaction",
                    created_at=now,
                )
                row = connection.execute(
                    "SELECT * FROM summary_source_suppressions "
                    "WHERE session_id=? AND source_set_hash=?",
                    (summary.session_id, summary.source_set_hash),
                ).fetchone()
                assert row is not None
                connection.commit()
                return self._from_row(row)
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _require_exact_summary(connection, summary_id: str) -> _SummaryIdentity:
        row = connection.execute(
            "SELECT id, session_id, source_set_hash, payload_state, provenance_state "
            "FROM session_summaries WHERE id=?",
            (summary_id,),
        ).fetchone()
        if (
            row is None
            or str(row["provenance_state"]) != "exact"
            or row["source_set_hash"] is None
        ):
            raise ValueError("exact summary is required")
        return _SummaryIdentity(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            source_set_hash=str(row["source_set_hash"]),
            payload_state=str(row["payload_state"]),
        )

    @staticmethod
    def _audit(
        connection,
        *,
        session_id: str,
        generation: int,
        state: str,
        reason_code: str,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO summary_suppression_audits (
                id, session_id, generation, state, reason_code, created_at
            ) VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, ?)
            """,
            (session_id, generation, state, reason_code, created_at),
        )

    @staticmethod
    def _from_row(row) -> SummarySuppression:
        return SummarySuppression(
            session_id=str(row["session_id"]),
            source_set_hash=str(row["source_set_hash"]),
            generation=int(row["generation"]),
            state=SummarySuppressionState(str(row["state"])),
            rebuild_permit_id=(
                str(row["rebuild_permit_id"])
                if row["rebuild_permit_id"] is not None
                else None
            ),
            bound_job_id=(
                str(row["bound_job_id"])
                if row["bound_job_id"] is not None
                else None
            ),
            authorized_summary_id=(
                str(row["authorized_summary_id"])
                if row["authorized_summary_id"] is not None
                else None
            ),
            reason_code=str(row["reason_code"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
