from __future__ import annotations

import base64
import json
import sqlite3
from datetime import datetime

from app.domain.session_summary import SummaryJob


class SummaryPublicRepository:
    """Reads bounded summary API projections without exposing private identities."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @staticmethod
    def decode_cursor(
        cursor: str | None,
        *,
        kind: str,
        filter_value: str | None = None,
    ) -> int:
        if cursor is None:
            return 0
        try:
            raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
            payload = json.loads(raw)
            offset = payload["offset"]
            if (
                payload["kind"] != kind
                or payload.get("filter") != filter_value
                or not isinstance(offset, int)
                or offset < 0
            ):
                raise ValueError
            return offset
        except Exception as exc:
            raise ValueError("invalid summary cursor") from exc

    @staticmethod
    def encode_cursor(
        offset: int,
        *,
        kind: str,
        filter_value: str | None = None,
    ) -> str:
        raw = json.dumps(
            {"kind": kind, "filter": filter_value, "offset": offset},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii")

    def status_counts(self) -> tuple[dict[str, int], dict[str, int]]:
        summary_rows = self._connection.execute(
            "SELECT payload_state, COUNT(*) AS count FROM session_summaries "
            "GROUP BY payload_state"
        ).fetchall()
        job_rows = self._connection.execute(
            "SELECT status, COUNT(*) AS count FROM summary_jobs GROUP BY status"
        ).fetchall()
        return (
            {str(row["payload_state"]): int(row["count"]) for row in summary_rows},
            {str(row["status"]): int(row["count"]) for row in job_rows},
        )

    def list_summaries(
        self,
        *,
        session_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], bool]:
        filters = "WHERE summary.session_id=?" if session_id is not None else ""
        parameters: tuple[object, ...] = (session_id,) if session_id is not None else ()
        rows = self._connection.execute(
            f"""
            SELECT summary.id, summary.session_id, summary.summary_text,
                   summary.source, summary.message_count, summary.created_at,
                   summary.updated_at, summary.payload_state,
                   summary.provenance_state, summary.redaction_reason_code,
                   summary.replaces_summary_id,
                   MIN(message.created_at) AS source_started_at,
                   MAX(message.created_at) AS source_ended_at,
                   COUNT(DISTINCT source.chat_turn_id) AS source_turn_count,
                   suppression.generation AS suppression_generation,
                   suppression.state AS suppression_state
            FROM session_summaries AS summary
            LEFT JOIN session_summary_sources AS source
              ON source.summary_id=summary.id
            LEFT JOIN messages AS message ON message.id=source.message_id
            LEFT JOIN summary_source_suppressions AS suppression
              ON suppression.session_id=summary.session_id
             AND suppression.source_set_hash=summary.source_set_hash
            {filters}
            GROUP BY summary.id
            ORDER BY summary.updated_at DESC, summary.id DESC
            LIMIT ? OFFSET ?
            """,
            (*parameters, limit + 1, offset),
        ).fetchall()
        items = [self._summary_item(row) for row in rows[:limit]]
        return items, len(rows) > limit

    def summary_detail(self, summary_id: str) -> dict[str, object]:
        row = self._connection.execute(
            """
            SELECT summary.id, summary.session_id, summary.summary_text,
                   summary.source, summary.message_count, summary.created_at,
                   summary.updated_at, summary.payload_state,
                   summary.provenance_state, summary.redaction_reason_code,
                   summary.replaces_summary_id,
                   MIN(message.created_at) AS source_started_at,
                   MAX(message.created_at) AS source_ended_at,
                   COUNT(DISTINCT source.chat_turn_id) AS source_turn_count,
                   suppression.generation AS suppression_generation,
                   suppression.state AS suppression_state
            FROM session_summaries AS summary
            LEFT JOIN session_summary_sources AS source
              ON source.summary_id=summary.id
            LEFT JOIN messages AS message ON message.id=source.message_id
            LEFT JOIN summary_source_suppressions AS suppression
              ON suppression.session_id=summary.session_id
             AND suppression.source_set_hash=summary.source_set_hash
            WHERE summary.id=?
            GROUP BY summary.id
            """,
            (summary_id,),
        ).fetchone()
        if row is None:
            raise KeyError(summary_id)
        return self._summary_item(row)

    def list_jobs(
        self,
        jobs: list[SummaryJob],
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], bool]:
        selected = jobs[offset : offset + limit + 1]
        items = [
            self._job_item(job, suppression=self._job_suppression(job))
            for job in selected[:limit]
        ]
        return items, len(selected) > limit

    def _job_suppression(self, job: SummaryJob) -> sqlite3.Row | None:
        if job.job_kind.value != "rebuild" or job.source_summary_id is None:
            return None
        return self._connection.execute(
            """
            SELECT suppression.generation, suppression.state
            FROM session_summaries AS summary
            JOIN summary_source_suppressions AS suppression
              ON suppression.session_id=summary.session_id
             AND suppression.source_set_hash=summary.source_set_hash
            WHERE summary.id=?
            """,
            (job.source_summary_id,),
        ).fetchone()

    def list_audits(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], bool]:
        rows = self._connection.execute(
            """
            SELECT * FROM (
                SELECT id, 'authority' AS kind, action AS status,
                       NULL AS outcome, NULL AS session_id, NULL AS job_id,
                       NULL AS summary_id, generation, NULL AS source_message_count,
                       NULL AS source_turn_count, NULL AS route, provider, NULL AS model,
                       NULL AS reason_code, NULL AS error_category, created_at
                FROM summary_authority_audits
                UNION ALL
                SELECT id, 'job', status, outcome, NULL, job_id, NULL,
                       consent_generation, source_message_count, source_turn_count,
                       route, provider, model, reason_code, error_category, created_at
                FROM summary_job_audits
                UNION ALL
                SELECT id, 'payload', payload_state, action, NULL, NULL, summary_id,
                       NULL, NULL, NULL, NULL, NULL, NULL, reason_code, NULL, created_at
                FROM summary_payload_audits
                UNION ALL
                SELECT id, 'suppression', state, NULL, session_id, NULL, NULL,
                       generation, NULL, NULL, NULL, NULL, NULL, reason_code, NULL,
                       created_at
                FROM summary_suppression_audits
            ) ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit + 1, offset),
        ).fetchall()
        return [dict(row) for row in rows[:limit]], len(rows) > limit

    @staticmethod
    def _summary_item(row: sqlite3.Row) -> dict[str, object]:
        active = str(row["payload_state"]) == "active"
        unavailable = None
        if not active:
            reason_code = str(row["redaction_reason_code"] or "")
            if reason_code in {"migration_stale_barrier", "stale_barrier"}:
                unavailable = "状态已过期"
            else:
                unavailable = (
                    "内容已清除"
                    if str(row["payload_state"]) == "redacted"
                    else "内容不可用"
                )
        return {
            "id": str(row["id"]),
            "session_id": str(row["session_id"]),
            "summary_text": str(row["summary_text"]) if active else None,
            "source_kind": str(row["source"]),
            "payload_state": str(row["payload_state"]),
            "provenance_state": str(row["provenance_state"]),
            "source_message_count": int(row["message_count"]),
            "source_turn_count": int(row["source_turn_count"]),
            "source_started_at": (
                datetime.fromisoformat(str(row["source_started_at"]))
                if row["source_started_at"] is not None
                else None
            ),
            "source_ended_at": (
                datetime.fromisoformat(str(row["source_ended_at"]))
                if row["source_ended_at"] is not None
                else None
            ),
            "replaces_summary_id": row["replaces_summary_id"],
            "suppression_generation": int(row["suppression_generation"] or 0),
            "suppression_state": row["suppression_state"],
            "unavailable_label": unavailable,
            "created_at": datetime.fromisoformat(str(row["created_at"])),
            "updated_at": datetime.fromisoformat(str(row["updated_at"])),
        }

    @staticmethod
    def _job_item(
        job: SummaryJob,
        *,
        suppression: sqlite3.Row | None,
    ) -> dict[str, object]:
        return {
            "id": job.id,
            "session_id": job.session_id,
            "job_kind": job.job_kind.value,
            "status": job.status.value,
            "source_message_count": job.source_message_count,
            "source_turn_count": job.source_turn_count,
            "route": job.route,
            "provider": job.provider,
            "model": job.model,
            "summarizer_schema_version": job.summarizer_schema_version,
            "job_schema_version": job.job_schema_version,
            "attempt_count": job.attempt_count,
            "reason_code": job.reason_code,
            "error_category": job.error_category,
            "retryable": job.status.value in {"failed", "cancelled", "skipped"},
            "cancellable": (
                job.status.value in {"pending", "running"}
                or (
                    job.job_kind.value == "rebuild"
                    and job.status.value in {"failed", "skipped"}
                )
            ),
            "suppression_generation": (
                int(suppression["generation"])
                if suppression is not None
                else None
            ),
            "suppression_state": (
                str(suppression["state"])
                if suppression is not None
                else None
            ),
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
        }
