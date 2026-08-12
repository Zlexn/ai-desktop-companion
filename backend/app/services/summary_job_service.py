from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from app.core.config import Settings
from app.domain.models import ChatRole, Message
from app.domain.session_summary import SummaryJob, SummaryJobStatus
from app.repositories.sqlite import managed_connection
from app.repositories.summary_automation import SummaryAutomationRepository
from app.services.credential_sanitizer import sanitize_credentials
from app.services.session_summary_contract import (
    SUMMARY_JOB_SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
    summary_attempt_epoch,
)
from app.services.session_summary_provider import (
    FakeSessionSummaryProvider,
    SessionSummaryOptions,
    SessionSummaryProvider,
    close_session_summary_provider,
)
from app.services.session_summary_service import (
    build_summary_processing_policy,
    summary_provider_policy_for_settings,
)
from app.services.summary_dispatch import SummaryProcessingFence


_TERMINAL_STATUSES = {
    SummaryJobStatus.SUCCEEDED,
    SummaryJobStatus.FAILED,
    SummaryJobStatus.CANCELLED,
    SummaryJobStatus.SKIPPED,
}


@dataclass(frozen=True)
class _PreparedJob:
    job: SummaryJob
    messages: tuple[Message, ...]


class _SummaryJobDeleted(Exception):
    pass


class SummaryJobService:
    def __init__(
        self,
        *,
        database_url: str,
        settings: Settings,
        processing_fence: SummaryProcessingFence,
        fake_provider_factory: Callable[[], SessionSummaryProvider] | None = None,
        remote_provider_factory: Callable[[], SessionSummaryProvider] | None = None,
        session_deletion_generation: Callable[[str], int] | None = None,
    ) -> None:
        self._database_url = database_url
        self._settings = settings
        self._processing_fence = processing_fence
        self._fake_provider_factory = fake_provider_factory or FakeSessionSummaryProvider
        self._remote_provider_factory = remote_provider_factory
        self._session_deletion_generation = session_deletion_generation or (
            lambda _session_id: 0
        )

    async def process(
        self,
        job_id: str,
        *,
        expected_session_id: str | None = None,
    ) -> SummaryJob | None:
        try:
            try:
                prepared = self._claim_and_prepare(
                    job_id,
                    expected_session_id=expected_session_id,
                )
            except KeyError:
                self._missing_job_result(job_id, expected_session_id)
            if isinstance(prepared, SummaryJob):
                return prepared

            async with self._processing_fence.hold_dispatch() as dispatch_allowed:
                if not dispatch_allowed:
                    return self._discard(
                        prepared.job.id,
                        prepared.job.session_id,
                        "discarded_processing_authority_changed",
                    )
                reason = self._preflight_reason(prepared.job)
                if reason is not None:
                    return self._discard(
                        prepared.job.id,
                        prepared.job.session_id,
                        reason,
                    )
                if prepared.job.route == "remote":
                    if self._remote_provider_factory is None:
                        return self._fail(
                            prepared.job.id,
                            prepared.job.session_id,
                            reason_code="provider_unavailable",
                            error_category="configuration",
                        )
                    provider_factory = self._remote_provider_factory
                else:
                    provider_factory = self._fake_provider_factory
                return await self._generate_and_commit(
                    prepared,
                    provider_factory=provider_factory,
                )
        except _SummaryJobDeleted:
            return None

    async def _generate_and_commit(
        self,
        prepared: _PreparedJob,
        *,
        provider_factory: Callable[[], SessionSummaryProvider],
    ) -> SummaryJob:
        provider: SessionSummaryProvider | None = None
        try:
            provider = provider_factory()
            result = await provider.generate(
                list(prepared.messages),
                SessionSummaryOptions(
                    max_tokens=self._settings.session_summary_llm_max_tokens,
                    timeout_seconds=self._settings.session_summary_llm_timeout_seconds,
                    max_retries=self._settings.session_summary_llm_max_retries,
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return self._fail(
                prepared.job.id,
                prepared.job.session_id,
                reason_code="provider_error",
                error_category="provider",
            )
        finally:
            if provider is not None:
                await close_session_summary_provider(provider)

        clean_text, credential_count = sanitize_credentials(result.text)
        if not clean_text:
            return self._fail(
                prepared.job.id,
                prepared.job.session_id,
                reason_code="invalid_output",
                error_category="validation",
            )
        if credential_count:
            return self._fail(
                prepared.job.id,
                prepared.job.session_id,
                reason_code="credential_output",
                error_category="validation",
            )
        if len(clean_text) > self._settings.session_summary_max_output_characters:
            return self._fail(
                prepared.job.id,
                prepared.job.session_id,
                reason_code="oversized_output",
                error_category="validation",
            )

        if prepared.job.route == "remote":
            reason = self._preflight_reason(prepared.job)
            if reason is not None:
                return self._discard(
                    prepared.job.id,
                    prepared.job.session_id,
                    reason,
                )
        with managed_connection(self._database_url) as connection:
            automation = SummaryAutomationRepository(connection)
            try:
                return automation.commit_summary_job(
                    prepared.job.id,
                    summary_text=clean_text,
                    max_output_characters=(
                        self._settings.session_summary_max_output_characters
                    ),
                    provider_policy_fingerprint=summary_provider_policy_for_settings(
                        self._settings
                    ),
                    session_deletion_generation=self._session_deletion_generation(
                        prepared.job.session_id
                    ),
                )
            except KeyError:
                if connection.execute(
                    "SELECT 1 FROM sessions WHERE id=?",
                    (prepared.job.session_id,),
                ).fetchone() is None:
                    raise _SummaryJobDeleted(prepared.job.id)
                raise

    def _claim_and_prepare(
        self,
        job_id: str,
        *,
        expected_session_id: str | None,
    ) -> _PreparedJob | SummaryJob:
        with managed_connection(self._database_url) as connection:
            automation = SummaryAutomationRepository(connection)
            current = automation.require_job(job_id)
            if (
                expected_session_id is not None
                and current.session_id != expected_session_id
            ):
                raise RuntimeError("summary job ownership changed")
            if current.status in _TERMINAL_STATUSES:
                return current
            claimed = automation.claim_job(
                job_id,
                max_attempts=self._settings.summary_job_max_attempts,
                job_schema_version=SUMMARY_JOB_SCHEMA_VERSION,
                summarizer_schema_version=SUMMARY_SCHEMA_VERSION,
            )
            if claimed is None:
                return automation.require_job(job_id)
            messages = self._load_messages(connection, claimed)
            if messages is None:
                return automation.complete_job(
                    job_id,
                    status=SummaryJobStatus.SKIPPED,
                    reason_code="discarded_source_changed",
                )
            if claimed.route == "remote":
                reason = self._preflight_reason_in_connection(
                    connection,
                    claimed,
                )
                if reason is not None:
                    return automation.complete_job(
                        job_id,
                        status=SummaryJobStatus.SKIPPED,
                        reason_code=reason,
                    )
            else:
                reason = self._local_authority_reason(connection, claimed)
                if reason is not None:
                    return automation.complete_job(
                        job_id,
                        status=SummaryJobStatus.SKIPPED,
                        reason_code=reason,
                    )
            return _PreparedJob(job=claimed, messages=messages)

    @staticmethod
    def _load_messages(
        connection: sqlite3.Connection,
        job: SummaryJob,
    ) -> tuple[Message, ...] | None:
        rows = connection.execute(
            """
            SELECT source.message_id, message.session_id, message.role,
                   message.content, message.created_at
            FROM summary_job_sources AS source
            JOIN messages AS message ON message.id=source.message_id
            JOIN chat_turns AS turn ON turn.id=source.chat_turn_id
            WHERE source.job_id=? AND message.session_id=?
              AND turn.session_id=?
            ORDER BY source.source_order
            """,
            (job.id, job.session_id, job.session_id),
        ).fetchall()
        if len(rows) != job.source_message_count:
            return None
        messages = tuple(
            Message(
                id=str(row["message_id"]),
                session_id=str(row["session_id"]),
                role=ChatRole(str(row["role"])),
                content=str(row["content"]),
                metadata={},
                created_at=datetime_from_iso(str(row["created_at"])),
            )
            for row in rows
        )
        if tuple(message.role for message in messages) != tuple(
            ChatRole.USER if index % 2 == 0 else ChatRole.ASSISTANT
            for index in range(len(messages))
        ):
            return None
        return messages

    def _preflight_reason(self, job: SummaryJob) -> str | None:
        with managed_connection(self._database_url) as connection:
            return self._preflight_reason_in_connection(connection, job)

    def _preflight_reason_in_connection(
        self,
        connection: sqlite3.Connection,
        job: SummaryJob,
    ) -> str | None:
        policy = build_summary_processing_policy(self._settings)
        authority = SummaryAutomationRepository(connection).valid_processing_snapshot(
            policy
        )
        if authority is None:
            return "discarded_processing_authority_changed"
        if (
            authority.generation != job.captured_processing_consent_generation
            or authority.policy_fingerprint
            != job.captured_processing_policy_fingerprint
        ):
            return "discarded_processing_authority_changed"
        reason = self._common_epoch_reason(connection, job)
        return reason or self._provider_epoch_reason(job)

    def _local_authority_reason(
        self,
        connection: sqlite3.Connection,
        job: SummaryJob,
    ) -> str | None:
        policy = build_summary_processing_policy(self._settings)
        authority = SummaryAutomationRepository(connection).valid_processing_snapshot(
            policy
        )
        if authority is None:
            return "discarded_processing_authority_changed"
        if (
            authority.generation != job.captured_processing_consent_generation
            or authority.policy_fingerprint
            != job.captured_processing_policy_fingerprint
        ):
            return "discarded_processing_authority_changed"
        reason = self._common_epoch_reason(connection, job)
        return reason or self._provider_epoch_reason(job)

    def _common_epoch_reason(
        self,
        connection: sqlite3.Connection,
        job: SummaryJob,
    ) -> str | None:
        if connection.execute(
            "SELECT 1 FROM sessions WHERE id=?",
            (job.session_id,),
        ).fetchone() is None:
            return "discarded_session_deleted"
        if self._session_deletion_generation(job.session_id) != (
            job.captured_session_deletion_generation
        ):
            return "discarded_session_deleted"
        barrier = connection.execute(
            "SELECT generation FROM memory_summary_barrier WHERE singleton_id=1"
        ).fetchone()
        if barrier is None or int(barrier["generation"]) != job.captured_barrier_generation:
            return "discarded_barrier_changed"
        if connection.execute(
            """
            SELECT 1 FROM summary_job_sources AS source
            JOIN memory_summary_source_exclusions AS excluded
              ON excluded.source_message_id=source.message_id
            WHERE source.job_id=? LIMIT 1
            """,
            (job.id,),
        ).fetchone() is not None:
            return "discarded_source_excluded"
        suppression_reason = self._suppression_epoch_reason(connection, job)
        if suppression_reason is not None:
            return suppression_reason
        return None

    @staticmethod
    def _suppression_epoch_reason(
        connection: sqlite3.Connection,
        job: SummaryJob,
    ) -> str | None:
        suppression_hash = job.source_set_hash
        if job.job_kind.value == "rebuild":
            if job.source_summary_id is None:
                return "discarded_rebuild_authority_changed"
            source_summary = connection.execute(
                "SELECT session_id, source_set_hash, payload_state, provenance_state "
                "FROM session_summaries WHERE id=?",
                (job.source_summary_id,),
            ).fetchone()
            if (
                source_summary is None
                or str(source_summary["session_id"]) != job.session_id
                or source_summary["source_set_hash"] is None
                or str(source_summary["payload_state"]) != "redacted"
                or str(source_summary["provenance_state"]) != "exact"
            ):
                return "discarded_rebuild_authority_changed"
            suppression_hash = str(source_summary["source_set_hash"])
        suppression = connection.execute(
            "SELECT generation, state, rebuild_permit_id, bound_job_id "
            "FROM summary_source_suppressions "
            "WHERE session_id=? AND source_set_hash=?",
            (job.session_id, suppression_hash),
        ).fetchone()
        current_generation = (
            int(suppression["generation"]) if suppression is not None else 0
        )
        if current_generation != job.captured_suppression_generation:
            return "discarded_suppression_changed"
        if job.job_kind.value == "rebuild":
            if (
                suppression is None
                or str(suppression["state"]) != "rebuild_in_progress"
                or suppression["rebuild_permit_id"] != job.rebuild_permit_id
                or suppression["bound_job_id"] != job.id
            ):
                return "discarded_rebuild_authority_changed"
        elif suppression is not None and str(suppression["state"]) in {
            "suppressed",
            "rebuild_authorized",
            "rebuild_in_progress",
        }:
            return "discarded_suppressed"
        return None

    def _provider_epoch_reason(self, job: SummaryJob) -> str | None:
        current_attempt_epoch = summary_attempt_epoch(
            logical_source_identity=job.logical_source_identity,
            processing_consent_generation=job.captured_processing_consent_generation,
            processing_policy_fingerprint=(
                job.captured_processing_policy_fingerprint
            ),
            provider_policy_fingerprint=summary_provider_policy_for_settings(
                self._settings
            ),
            session_deletion_generation=job.captured_session_deletion_generation,
            suppression_generation=job.captured_suppression_generation,
            rebuild_authorization_generation=(
                job.captured_rebuild_authorization_generation
            ),
            rebuild_permit_id=job.rebuild_permit_id,
        )
        if current_attempt_epoch != job.attempt_epoch:
            return "discarded_provider_policy_changed"
        return None

    def _discard(
        self,
        job_id: str,
        expected_session_id: str,
        reason_code: str,
    ) -> SummaryJob:
        with managed_connection(self._database_url) as connection:
            try:
                return SummaryAutomationRepository(connection).complete_job(
                    job_id,
                    status=SummaryJobStatus.SKIPPED,
                    reason_code=reason_code,
                )
            except KeyError:
                return self._deleted_job_result(
                    job_id,
                    expected_session_id,
                    connection,
                )

    def _missing_job_result(
        self,
        job_id: str,
        expected_session_id: str | None,
    ) -> NoReturn:
        with managed_connection(self._database_url) as connection:
            return self._deleted_job_result(
                job_id,
                expected_session_id,
                connection,
            )

    @staticmethod
    def _deleted_job_result(
        job_id: str,
        expected_session_id: str | None,
        connection: sqlite3.Connection,
    ) -> NoReturn:
        job_exists = connection.execute(
            "SELECT 1 FROM summary_jobs WHERE id=?",
            (job_id,),
        ).fetchone() is not None
        session_deleted = (
            expected_session_id is not None
            and connection.execute(
                "SELECT 1 FROM sessions WHERE id=?",
                (expected_session_id,),
            ).fetchone()
            is None
        )
        if job_exists or not session_deleted:
            raise KeyError(job_id)
        raise _SummaryJobDeleted(job_id)

    def _fail(
        self,
        job_id: str,
        expected_session_id: str,
        *,
        reason_code: str,
        error_category: str,
    ) -> SummaryJob:
        with managed_connection(self._database_url) as connection:
            try:
                return SummaryAutomationRepository(connection).complete_job(
                    job_id,
                    status=SummaryJobStatus.FAILED,
                    reason_code=reason_code,
                    error_category=error_category,
                )
            except KeyError:
                return self._deleted_job_result(
                    job_id,
                    expected_session_id,
                    connection,
                )


def datetime_from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)
