from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterator, Literal
from uuid import uuid4

from app.core.errors import (
    SummaryAuthorityStateError,
    SummaryAuthorityVersionConflictError,
)
from app.domain.session_summary import (
    SummaryAuthorityStatus,
    SummaryInjectionAuthoritySnapshot,
    SummaryJob,
    SummaryJobKind,
    SummaryJobStatus,
    SummarySourceSnapshot,
)
from app.services.session_summary_contract import (
    SUMMARY_AUDIT_SCHEMA_VERSION,
    SUMMARY_INJECTION_SCHEMA_VERSION,
    SUMMARY_JOB_SCHEMA_VERSION,
    canonical_summary_source_set_hash,
    summary_attempt_epoch,
    summary_injection_policy_fingerprint,
    summary_logical_source_identity,
    summary_processing_policy_fingerprint,
)


DEFAULT_SUMMARY_PROCESSING_SCOPE_ID = "default"
DEFAULT_SUMMARY_INJECTION_SCOPE_ID = "default"
SummaryAuthorityAction = Literal[
    "grant",
    "decline",
    "revoke",
    "enable_local",
    "disable_local",
]
SummaryRoute = Literal["local", "remote"]


def _now() -> datetime:
    return datetime.now(UTC)


def _fields_json(fields: tuple[str, ...]) -> str:
    return json.dumps(list(fields), ensure_ascii=False, separators=(",", ":"))


def _parse_fields(raw: object) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return ()
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        return ()
    return tuple(parsed)


def _parse_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _parse_positive_int(value: object) -> int | None:
    parsed = _parse_nonnegative_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def _parse_status(value: object) -> SummaryAuthorityStatus | None:
    try:
        return SummaryAuthorityStatus(str(value))
    except ValueError:
        return None


def authorize_suppression_transition(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    source_set_hash: str,
    expected_generation: int,
    target_generation: int,
    target_state: str,
) -> None:
    connection.execute(
        """
        INSERT INTO summary_suppression_transition_guards (
            session_id, source_set_hash, expected_generation,
            target_generation, target_state
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            session_id,
            source_set_hash,
            expected_generation,
            target_generation,
            target_state,
        ),
    )


def clear_suppression_transition_guard(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    source_set_hash: str,
) -> None:
    connection.execute(
        "DELETE FROM summary_suppression_transition_guards "
        "WHERE session_id=? AND source_set_hash=?",
        (session_id, source_set_hash),
    )


@dataclass(frozen=True)
class SummaryProcessingPolicy:
    route: SummaryRoute
    disclosure_version: str
    purpose: str
    provider: str
    model: str
    endpoint_policy: str
    summarizer_schema_version: str
    disclosed_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_policy_strings(
            self.route,
            self.disclosure_version,
            self.purpose,
            self.provider,
            self.model,
            self.endpoint_policy,
            self.summarizer_schema_version,
        )
        _validate_fields(self.disclosed_fields)

    def fingerprint(self) -> str:
        return summary_processing_policy_fingerprint(
            route=self.route,
            disclosure_version=self.disclosure_version,
            purpose=self.purpose,
            provider=self.provider,
            model=self.model,
            endpoint_policy=self.endpoint_policy,
            summarizer_schema_version=self.summarizer_schema_version,
            disclosed_fields=self.disclosed_fields,
        )


@dataclass(frozen=True)
class SummaryInjectionPolicy:
    route: SummaryRoute
    disclosure_version: str
    purpose: str
    chat_provider: str
    chat_model: str
    endpoint_policy: str
    injection_schema_version: str
    disclosed_fields: tuple[str, ...]
    max_fragment_count: int
    max_fragment_characters: int
    max_total_characters: int

    def __post_init__(self) -> None:
        _validate_policy_strings(
            self.route,
            self.disclosure_version,
            self.purpose,
            self.chat_provider,
            self.chat_model,
            self.endpoint_policy,
            self.injection_schema_version,
        )
        _validate_fields(self.disclosed_fields)
        if self.max_fragment_count <= 0:
            raise ValueError("max_fragment_count must be positive")
        if self.max_fragment_characters <= 0:
            raise ValueError("max_fragment_characters must be positive")
        if self.max_total_characters <= 0:
            raise ValueError("max_total_characters must be positive")
        if self.max_fragment_characters > self.max_total_characters:
            raise ValueError("fragment limit cannot exceed total limit")

    def fingerprint(self) -> str:
        return summary_injection_policy_fingerprint(
            route=self.route,
            disclosure_version=self.disclosure_version,
            purpose=self.purpose,
            chat_provider=self.chat_provider,
            chat_model=self.chat_model,
            endpoint_policy=self.endpoint_policy,
            injection_schema_version=self.injection_schema_version,
            disclosed_fields=self.disclosed_fields,
            max_fragment_count=self.max_fragment_count,
            max_fragment_characters=self.max_fragment_characters,
            max_total_characters=self.max_total_characters,
        )


@dataclass(frozen=True)
class SummaryProcessingAuthority:
    scope_id: str
    status: SummaryAuthorityStatus
    disclosure_version: str | None
    purpose: str | None
    provider: str | None
    disclosed_fields: tuple[str, ...]
    generation: int
    updated_at: datetime


@dataclass(frozen=True)
class SummaryInjectionAuthority:
    scope_id: str
    status: SummaryAuthorityStatus
    disclosure_version: str | None
    disclosed_fields: tuple[str, ...]
    generation: int
    max_fragment_count: int | None
    max_fragment_characters: int | None
    max_total_characters: int | None
    updated_at: datetime


@dataclass(frozen=True)
class SummaryProcessingAuthoritySnapshot:
    generation: int
    policy_fingerprint: str
    disclosure_version: str
    purpose: str
    provider: str
    disclosed_fields: tuple[str, ...]


@dataclass(frozen=True)
class SummaryAuthorityAudit:
    id: str
    authority_kind: Literal["processing", "injection"]
    scope_id: str
    action: SummaryAuthorityAction
    generation: int
    disclosure_version: str | None
    provider: str | None
    created_at: datetime


def _validate_policy_strings(route: str, *values: str) -> None:
    if route not in {"local", "remote"}:
        raise ValueError("summary route must be local or remote")
    if any(not value.strip() for value in values):
        raise ValueError("summary policy values must not be blank")


def _validate_fields(fields: tuple[str, ...]) -> None:
    if not fields or any(not field.strip() for field in fields):
        raise ValueError("summary disclosed fields must not be empty")
    if len(set(fields)) != len(fields):
        raise ValueError("summary disclosed fields must be unique")


def _validate_action(action: str, route: SummaryRoute) -> SummaryAuthorityStatus:
    if route == "remote":
        allowed = {
            "grant": SummaryAuthorityStatus.GRANTED,
            "decline": SummaryAuthorityStatus.DECLINED,
            "revoke": SummaryAuthorityStatus.REVOKED,
        }
    else:
        allowed = {
            "enable_local": SummaryAuthorityStatus.GRANTED,
            "disable_local": SummaryAuthorityStatus.REVOKED,
        }
    try:
        return allowed[action]
    except KeyError as exc:
        raise ValueError("authority action does not match summary route") from exc


class SummaryAutomationRepository:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        adopt_transaction: bool = False,
    ) -> None:
        self._connection = connection
        self._transaction_depth = 1 if adopt_transaction else 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._transaction_depth:
            savepoint = f"summary_automation_sp_{self._transaction_depth}"
            self._transaction_depth += 1
            self._connection.execute(f"SAVEPOINT {savepoint}")
            try:
                yield
            except BaseException:
                self._connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            finally:
                self._transaction_depth -= 1
            return

        if self._connection.in_transaction:
            raise RuntimeError("connection already has an unmanaged transaction")
        self._transaction_depth = 1
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield
        except BaseException:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()
        finally:
            self._transaction_depth = 0

    def get_processing_authority(
        self,
        scope_id: str = DEFAULT_SUMMARY_PROCESSING_SCOPE_ID,
    ) -> SummaryProcessingAuthority:
        with self.transaction():
            row = self._ensure_processing_row(scope_id)
            return self._processing_authority(row)

    def get_injection_authority(
        self,
        scope_id: str = DEFAULT_SUMMARY_INJECTION_SCOPE_ID,
    ) -> SummaryInjectionAuthority:
        with self.transaction():
            row = self._ensure_injection_row(scope_id)
            return self._injection_authority(row)

    def mutate_processing(
        self,
        *,
        action: SummaryAuthorityAction,
        expected_generation: int,
        policy: SummaryProcessingPolicy,
        scope_id: str = DEFAULT_SUMMARY_PROCESSING_SCOPE_ID,
    ) -> SummaryProcessingAuthority:
        status = _validate_action(action, policy.route)
        with self.transaction():
            current = self._ensure_processing_row(scope_id)
            self._require_generation(current, expected_generation)
            generation = expected_generation + 1
            now = _now().isoformat()
            granted = status is SummaryAuthorityStatus.GRANTED
            self._connection.execute(
                """
                UPDATE summary_processing_consents
                SET status=?, disclosure_version=?, purpose=?, provider=?,
                    disclosed_fields_json=?, policy_fingerprint=?, generation=?,
                    updated_at=?
                WHERE scope_id=? AND generation=?
                """,
                (
                    status.value,
                    policy.disclosure_version if granted else None,
                    policy.purpose if granted else None,
                    policy.provider if granted else None,
                    _fields_json(policy.disclosed_fields) if granted else "[]",
                    policy.fingerprint() if granted else None,
                    generation,
                    now,
                    scope_id,
                    expected_generation,
                ),
            )
            self._insert_audit(
                authority_kind="processing",
                scope_id=scope_id,
                action=action,
                generation=generation,
                disclosure_version=policy.disclosure_version if granted else None,
                provider=policy.provider if granted else None,
                created_at=now,
            )
            row = self._processing_row(scope_id)
            assert row is not None
            return self._processing_authority(row)

    def mutate_injection(
        self,
        *,
        action: SummaryAuthorityAction,
        expected_generation: int,
        policy: SummaryInjectionPolicy,
        scope_id: str = DEFAULT_SUMMARY_INJECTION_SCOPE_ID,
    ) -> SummaryInjectionAuthority:
        status = _validate_action(action, policy.route)
        with self.transaction():
            current = self._ensure_injection_row(scope_id)
            self._require_generation(current, expected_generation)
            generation = expected_generation + 1
            now = _now().isoformat()
            granted = status is SummaryAuthorityStatus.GRANTED
            self._connection.execute(
                """
                UPDATE summary_injection_consents
                SET status=?, disclosure_version=?, chat_provider_fingerprint=?,
                    disclosed_fields_json=?, generation=?, max_fragment_count=?,
                    max_fragment_characters=?, max_total_characters=?, updated_at=?
                WHERE scope_id=? AND generation=?
                """,
                (
                    status.value,
                    policy.disclosure_version if granted else None,
                    policy.fingerprint() if granted else None,
                    _fields_json(policy.disclosed_fields) if granted else "[]",
                    generation,
                    policy.max_fragment_count if granted else 1,
                    policy.max_fragment_characters if granted else 1,
                    policy.max_total_characters if granted else 1,
                    now,
                    scope_id,
                    expected_generation,
                ),
            )
            self._insert_audit(
                authority_kind="injection",
                scope_id=scope_id,
                action=action,
                generation=generation,
                disclosure_version=policy.disclosure_version if granted else None,
                provider=policy.chat_provider if granted else None,
                created_at=now,
            )
            row = self._injection_row(scope_id)
            assert row is not None
            return self._injection_authority(row)

    def reserve_job(
        self,
        *,
        snapshot: SummarySourceSnapshot,
        job_kind: SummaryJobKind,
        route: Literal["fake", "remote"],
        provider: str | None,
        model: str | None,
        summarizer_schema_version: str,
        processing_consent_generation: int,
        processing_policy_fingerprint: str | None,
        provider_policy_fingerprint: str,
        session_deletion_generation: int,
        suppression_generation: int,
        rebuild_authorization_generation: int,
        rebuild_permit_id: str | None,
        source_summary_id: str | None = None,
    ) -> tuple[SummaryJob, bool]:
        with self.transaction():
            self._validate_job_reservation(
                snapshot=snapshot,
                job_kind=job_kind,
                route=route,
                provider=provider,
                model=model,
                summarizer_schema_version=summarizer_schema_version,
                processing_consent_generation=processing_consent_generation,
                processing_policy_fingerprint=processing_policy_fingerprint,
                provider_policy_fingerprint=provider_policy_fingerprint,
                session_deletion_generation=session_deletion_generation,
                suppression_generation=suppression_generation,
                rebuild_authorization_generation=rebuild_authorization_generation,
                rebuild_permit_id=rebuild_permit_id,
            )
            assert snapshot.source_set_hash is not None
            if job_kind is SummaryJobKind.INCREMENTAL:
                suppressed = self._connection.execute(
                    "SELECT 1 FROM summary_source_suppressions "
                    "WHERE session_id=? AND source_set_hash=? "
                    "AND state IN ('suppressed', 'rebuild_authorized', 'rebuild_in_progress')",
                    (snapshot.session_id, snapshot.source_set_hash),
                ).fetchone()
                if suppressed is not None:
                    raise ValueError("summary source set is suppressed")
            elif source_summary_id is None:
                raise ValueError("rebuild summary job requires source summary")
            else:
                source_summary = self._connection.execute(
                    "SELECT session_id, payload_state, provenance_state, "
                    "source_set_hash FROM session_summaries WHERE id=?",
                    (source_summary_id,),
                ).fetchone()
                suppression = self._connection.execute(
                    "SELECT generation, state, rebuild_permit_id, "
                    "authorized_summary_id FROM summary_source_suppressions "
                    "WHERE session_id=? AND source_set_hash=("
                    "SELECT source_set_hash FROM session_summaries WHERE id=?)",
                    (snapshot.session_id, source_summary_id),
                ).fetchone()
                if (
                    source_summary is None
                    or str(source_summary["session_id"]) != snapshot.session_id
                    or str(source_summary["payload_state"]) != "redacted"
                    or str(source_summary["provenance_state"]) != "exact"
                    or source_summary["source_set_hash"] is None
                    or suppression is None
                    or int(suppression["generation"]) + 1
                    != suppression_generation
                    or int(suppression["generation"])
                    != rebuild_authorization_generation
                    or str(suppression["state"]) != "rebuild_authorized"
                    or suppression["rebuild_permit_id"] != rebuild_permit_id
                    or suppression["authorized_summary_id"] != source_summary_id
                ):
                    raise ValueError("rebuild authority does not match source summary")
            logical_identity = summary_logical_source_identity(
                session_id=snapshot.session_id,
                job_kind=job_kind.value,
                source_set_hash=snapshot.source_set_hash,
                barrier_generation=snapshot.barrier_generation,
                summarizer_schema_version=summarizer_schema_version,
                route=route,
            )
            attempt_epoch = summary_attempt_epoch(
                logical_source_identity=logical_identity,
                processing_consent_generation=processing_consent_generation,
                processing_policy_fingerprint=processing_policy_fingerprint,
                provider_policy_fingerprint=provider_policy_fingerprint,
                session_deletion_generation=session_deletion_generation,
                suppression_generation=suppression_generation,
                rebuild_authorization_generation=rebuild_authorization_generation,
                rebuild_permit_id=rebuild_permit_id,
            )
            existing = self._connection.execute(
                "SELECT * FROM summary_jobs WHERE logical_source_identity=? "
                "AND attempt_epoch=?",
                (logical_identity, attempt_epoch),
            ).fetchone()
            if existing is not None:
                return self._job_from_row(existing), False

            job_id = str(uuid4())
            created_at = _now().isoformat()
            self._connection.execute(
                """
                INSERT INTO summary_jobs (
                    id, session_id, job_kind, status, logical_source_identity,
                    attempt_epoch, source_set_hash, source_message_count,
                    source_turn_count, captured_barrier_generation,
                    captured_processing_consent_generation,
                    captured_processing_policy_fingerprint,
                    captured_session_deletion_generation,
                    captured_suppression_generation,
                    captured_rebuild_authorization_generation,
                    rebuild_permit_id, source_summary_id, route, provider, model,
                    summarizer_schema_version, job_schema_version,
                    source_manifest_sealed, attempt_count,
                    reason_code, error_category, created_at, started_at, finished_at
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, NULL, ?, NULL, NULL)
                """,
                (
                    job_id,
                    snapshot.session_id,
                    job_kind.value,
                    logical_identity,
                    attempt_epoch,
                    snapshot.source_set_hash,
                    snapshot.source_message_count,
                    snapshot.source_turn_count,
                    snapshot.barrier_generation,
                    processing_consent_generation,
                    processing_policy_fingerprint,
                    session_deletion_generation,
                    suppression_generation,
                    rebuild_authorization_generation,
                    rebuild_permit_id,
                    source_summary_id,
                    route,
                    provider,
                    model,
                    summarizer_schema_version,
                    SUMMARY_JOB_SCHEMA_VERSION,
                    created_at,
                ),
            )
            source_order = 0
            for turn in snapshot.turns:
                for message in turn.messages:
                    self._connection.execute(
                        """
                        INSERT INTO summary_job_sources (
                            job_id, chat_turn_id, message_id, turn_order,
                            message_order_in_turn, source_order
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            job_id,
                            turn.id,
                            message.id,
                            turn.turn_order,
                            message.message_order_in_turn,
                            source_order,
                        ),
                    )
                    source_order += 1
            if source_order != snapshot.source_message_count:
                raise RuntimeError("summary job source manifest is incomplete")
            self._connection.execute(
                "UPDATE summary_jobs SET source_manifest_sealed=1 WHERE id=?",
                (job_id,),
            )
            row = self._connection.execute(
                "SELECT * FROM summary_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            assert row is not None
            return self._job_from_row(row), True

    def list_jobs(self) -> list[SummaryJob]:
        rows = self._connection.execute(
            "SELECT * FROM summary_jobs ORDER BY created_at DESC, id DESC"
        ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def retry_job(
        self,
        job_id: str,
        *,
        processing_policy: SummaryProcessingPolicy,
        provider_policy_fingerprint: str,
        session_deletion_generation: int,
    ) -> tuple[SummaryJob, bool]:
        current = self.require_job(job_id)
        if (
            current.job_kind is not SummaryJobKind.INCREMENTAL
            or current.status
            not in {
                SummaryJobStatus.FAILED,
                SummaryJobStatus.CANCELLED,
                SummaryJobStatus.SKIPPED,
            }
        ):
            raise ValueError("summary job is not retryable")
        authority = self.valid_processing_snapshot(processing_policy)
        if authority is None:
            raise ValueError("current processing authority is required")
        source_rows = self._connection.execute(
            """
            SELECT source.chat_turn_id, source.message_id, source.turn_order,
                   source.message_order_in_turn, message.role, message.content
            FROM summary_job_sources AS source
            JOIN messages AS message ON message.id=source.message_id
            WHERE source.job_id=? ORDER BY source.source_order
            """,
            (job_id,),
        ).fetchall()
        if len(source_rows) != current.source_message_count:
            raise ValueError("summary retry source set is unavailable")
        turns = []
        for index in range(0, len(source_rows), 2):
            user, assistant = source_rows[index : index + 2]
            if (
                str(user["role"]) != "user"
                or str(assistant["role"]) != "assistant"
                or str(user["chat_turn_id"]) != str(assistant["chat_turn_id"])
            ):
                raise ValueError("summary retry source set is invalid")
            from app.domain.session_summary import (
                SummarySnapshotMessage,
                SummarySnapshotTurn,
            )
            from app.domain.models import ChatRole

            turns.append(
                SummarySnapshotTurn(
                    id=str(user["chat_turn_id"]),
                    turn_order=int(user["turn_order"]),
                    messages=(
                        SummarySnapshotMessage(
                            id=str(user["message_id"]),
                            role=ChatRole.USER,
                            content=str(user["content"]),
                            message_order_in_turn=0,
                        ),
                        SummarySnapshotMessage(
                            id=str(assistant["message_id"]),
                            role=ChatRole.ASSISTANT,
                            content=str(assistant["content"]),
                            message_order_in_turn=1,
                        ),
                    ),
                )
            )
        barrier = self._connection.execute(
            "SELECT generation FROM memory_summary_barrier WHERE singleton_id=1"
        ).fetchone()
        if barrier is None:
            raise ValueError("summary retry barrier is unavailable")
        suppression = self._connection.execute(
            "SELECT generation FROM summary_source_suppressions "
            "WHERE session_id=? AND source_set_hash=?",
            (current.session_id, current.source_set_hash),
        ).fetchone()
        suppression_generation = (
            int(suppression["generation"]) if suppression is not None else 0
        )
        snapshot = SummarySourceSnapshot(
            session_id=current.session_id,
            barrier_generation=int(barrier["generation"]),
            candidate_turn_count=len(turns),
            source_character_count=sum(
                len(message.content)
                for turn in turns
                for message in turn.messages
            ),
            turns=tuple(turns),
            source_set_hash=current.source_set_hash,
        )
        route = "fake" if processing_policy.route == "local" else "remote"
        return self.reserve_job(
            snapshot=snapshot,
            job_kind=SummaryJobKind.INCREMENTAL,
            route=route,
            provider=processing_policy.provider if route == "remote" else None,
            model=processing_policy.model if route == "remote" else None,
            summarizer_schema_version=processing_policy.summarizer_schema_version,
            processing_consent_generation=authority.generation,
            processing_policy_fingerprint=authority.policy_fingerprint,
            provider_policy_fingerprint=provider_policy_fingerprint,
            session_deletion_generation=session_deletion_generation,
            suppression_generation=suppression_generation,
            rebuild_authorization_generation=0,
            rebuild_permit_id=None,
        )

    def cancel_api_job(self, job_id: str) -> SummaryJob:
        current = self.require_job(job_id)
        if current.status not in {
            SummaryJobStatus.PENDING,
            SummaryJobStatus.RUNNING,
        }:
            raise ValueError("summary job is not cancellable")
        self._terminalize_job(
            job_id,
            status=SummaryJobStatus.CANCELLED,
            reason_code="user_cancelled",
            error_category=None,
        )
        return self.require_job(job_id)

    def require_job(self, job_id: str) -> SummaryJob:
        row = self._connection.execute(
            "SELECT * FROM summary_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._job_from_row(row)

    def claim_job(
        self,
        job_id: str,
        *,
        max_attempts: int,
        stale_before: datetime | None = None,
        job_schema_version: str = SUMMARY_JOB_SCHEMA_VERSION,
        summarizer_schema_version: str | None = None,
    ) -> SummaryJob | None:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        with self.transaction():
            row = self._connection.execute(
                "SELECT * FROM summary_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            if (
                str(row["job_schema_version"]) != job_schema_version
                or (
                    summarizer_schema_version is not None
                    and str(row["summarizer_schema_version"])
                    != summarizer_schema_version
                )
                or int(row["source_manifest_sealed"]) != 1
                or int(row["attempt_count"]) >= max_attempts
            ):
                return None
            status = str(row["status"])
            stale_running = (
                status == SummaryJobStatus.RUNNING.value
                and stale_before is not None
                and row["started_at"] is not None
                and datetime.fromisoformat(str(row["started_at"])) <= stale_before
            )
            if status != SummaryJobStatus.PENDING.value and not stale_running:
                return None
            now = _now().isoformat()
            cursor = self._connection.execute(
                """
                UPDATE summary_jobs
                SET status='running', attempt_count=attempt_count+1,
                    started_at=?, finished_at=NULL, reason_code=NULL,
                    error_category=NULL
                WHERE id=? AND attempt_count=? AND (
                    status='pending'
                    OR (status='running' AND started_at IS NOT NULL AND started_at<=?)
                )
                """,
                (
                    now,
                    job_id,
                    int(row["attempt_count"]),
                    stale_before.isoformat() if stale_before is not None else "",
                ),
            )
            if cursor.rowcount != 1:
                return None
            claimed = self._connection.execute(
                "SELECT * FROM summary_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            assert claimed is not None
            return self._job_from_row(claimed)

    def prepare_recovery_jobs(
        self,
        *,
        stale_before: datetime,
        job_schema_version: str,
        summarizer_schema_version: str,
        max_attempts: int,
    ) -> tuple[list[SummaryJob], list[str]]:
        with self.transaction():
            recoverable_ids, incompatible = self.classify_recovery_jobs(
                stale_before=stale_before,
                job_schema_version=job_schema_version,
                summarizer_schema_version=summarizer_schema_version,
                max_attempts=max_attempts,
            )
            if recoverable_ids:
                placeholders = ", ".join("?" for _ in recoverable_ids)
                self._connection.execute(
                    f"""
                    UPDATE summary_jobs
                    SET status='pending', started_at=NULL, finished_at=NULL,
                        reason_code=NULL, error_category=NULL
                    WHERE id IN ({placeholders}) AND status='running'
                      AND started_at IS NOT NULL AND started_at<=?
                    """,
                    (*recoverable_ids, stale_before.isoformat()),
                )
            recoverable = [
                self.require_job(job_id) for job_id in recoverable_ids
            ]
            return recoverable, incompatible

    def classify_recovery_jobs(
        self,
        *,
        stale_before: datetime,
        job_schema_version: str,
        summarizer_schema_version: str,
        max_attempts: int,
    ) -> tuple[list[str], list[str]]:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        rows = self._connection.execute(
            """
            SELECT * FROM summary_jobs
            WHERE status='pending'
               OR (status='running' AND started_at IS NOT NULL AND started_at<=?)
            ORDER BY created_at, id
            """,
            (stale_before.isoformat(),),
        ).fetchall()
        recoverable: list[str] = []
        incompatible: list[str] = []
        for row in rows:
            job_id = str(row["id"])
            compatible = (
                str(row["job_schema_version"]) == job_schema_version
                and str(row["summarizer_schema_version"])
                == summarizer_schema_version
                and int(row["attempt_count"]) < max_attempts
                and int(row["source_manifest_sealed"]) == 1
            )
            (recoverable if compatible else incompatible).append(job_id)
        return recoverable, incompatible

    def skip_no_consent_job(self, job_id: str) -> None:
        self._terminalize_job(
            job_id,
            status=SummaryJobStatus.SKIPPED,
            reason_code="skipped_no_consent",
            error_category=None,
        )

    def complete_job(
        self,
        job_id: str,
        *,
        status: SummaryJobStatus,
        reason_code: str,
        error_category: str | None = None,
    ) -> SummaryJob:
        if status not in {
            SummaryJobStatus.FAILED,
            SummaryJobStatus.SKIPPED,
            SummaryJobStatus.CANCELLED,
        }:
            raise ValueError("complete_job requires a non-success terminal status")
        self._terminalize_job(
            job_id,
            status=status,
            reason_code=reason_code,
            error_category=error_category,
        )
        return self.require_job(job_id)

    def commit_summary_job(
        self,
        job_id: str,
        *,
        summary_text: str,
        max_output_characters: int,
        provider_policy_fingerprint: str,
        session_deletion_generation: int | None = None,
    ) -> SummaryJob:
        clean_text = summary_text.strip()
        if not clean_text or len(clean_text) > max_output_characters:
            raise ValueError("summary output violates commit bounds")
        with self.transaction():
            job_row = self._connection.execute(
                "SELECT * FROM summary_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if job_row is None:
                raise KeyError(job_id)
            if str(job_row["status"]) != SummaryJobStatus.RUNNING.value:
                raise ValueError("summary job must be running before commit")
            sources = self._connection.execute(
                "SELECT * FROM summary_job_sources WHERE job_id=? "
                "ORDER BY source_order",
                (job_id,),
            ).fetchall()
            mismatch = self._commit_mismatch_reason(
                job_row,
                sources,
                provider_policy_fingerprint=provider_policy_fingerprint,
                session_deletion_generation=session_deletion_generation,
            )
            if mismatch is not None:
                finished_at = _now().isoformat()
                self._set_terminal_in_transaction(
                    job_id,
                    status=SummaryJobStatus.SKIPPED,
                    reason_code=mismatch,
                    error_category=None,
                )
                self._insert_job_audit(
                    job_row,
                    status=SummaryJobStatus.SKIPPED,
                    reason_code=mismatch,
                    error_category=None,
                    created_at=finished_at,
                )
                return self.require_job(job_id)

            now = _now().isoformat()
            summary_id = str(uuid4())
            self._connection.execute(
                "INSERT INTO summary_commit_guards (job_id, summary_id) VALUES (?, ?)",
                (job_id, summary_id),
            )
            self._connection.execute(
                """
                INSERT INTO session_summaries (
                    id, session_id, summary_text, source,
                    covered_message_start_id, covered_message_end_id,
                    message_count, metadata_json, created_at, updated_at,
                    observed_memory_summary_barrier, payload_state,
                    source_set_hash, summarizer_schema_version,
                    injection_schema_version, replaces_summary_id,
                    provenance_state, redacted_at, redaction_reason_code
                ) VALUES (?, ?, ?, 'generated', ?, ?, ?, '{}', ?, ?, ?,
                          'active', ?, ?, ?, ?, 'exact', NULL, NULL)
                """,
                (
                    summary_id,
                    str(job_row["session_id"]),
                    clean_text,
                    str(sources[0]["message_id"]),
                    str(sources[-1]["message_id"]),
                    int(job_row["source_message_count"]),
                    now,
                    now,
                    int(job_row["captured_barrier_generation"]),
                    str(job_row["source_set_hash"]),
                    str(job_row["summarizer_schema_version"]),
                    SUMMARY_INJECTION_SCHEMA_VERSION,
                    job_row["source_summary_id"],
                ),
            )
            for source in sources:
                self._connection.execute(
                    """
                    INSERT INTO session_summary_sources (
                        summary_id, chat_turn_id, message_id, turn_order,
                        message_order_in_turn, source_order
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        summary_id,
                        str(source["chat_turn_id"]),
                        str(source["message_id"]),
                        int(source["turn_order"]),
                        int(source["message_order_in_turn"]),
                        int(source["source_order"]),
                    ),
                )
            if str(job_row["job_kind"]) == SummaryJobKind.REBUILD.value:
                suppression_identity = self._suppression_identity(job_row)
                authorize_suppression_transition(
                    self._connection,
                    session_id=str(job_row["session_id"]),
                    source_set_hash=suppression_identity,
                    expected_generation=int(
                        job_row["captured_suppression_generation"]
                    ),
                    target_generation=(
                        int(job_row["captured_suppression_generation"]) + 1
                    ),
                    target_state="rebuild_completed",
                )
                suppression_cursor = self._connection.execute(
                    """
                    UPDATE summary_source_suppressions
                    SET generation=generation+1, state='rebuild_completed',
                        rebuild_permit_id=NULL, bound_job_id=NULL,
                        authorized_summary_id=NULL,
                        reason_code='rebuild_completed', updated_at=?
                    WHERE session_id=? AND source_set_hash=?
                      AND generation=? AND state='rebuild_in_progress'
                      AND rebuild_permit_id=? AND bound_job_id=?
                    """,
                    (
                        now,
                        str(job_row["session_id"]),
                        suppression_identity,
                        int(job_row["captured_suppression_generation"]),
                        job_row["rebuild_permit_id"],
                        job_id,
                    ),
                )
                if suppression_cursor.rowcount != 1:
                    raise RuntimeError("rebuild suppression changed before commit")
                clear_suppression_transition_guard(
                    self._connection,
                    session_id=str(job_row["session_id"]),
                    source_set_hash=suppression_identity,
                )
                self._connection.execute(
                    """
                    INSERT INTO summary_suppression_audits (
                        id, session_id, generation, state,
                        reason_code, created_at
                    ) VALUES (?, ?, ?, 'rebuild_completed',
                              'rebuild_completed', ?)
                    """,
                    (
                        str(uuid4()),
                        str(job_row["session_id"]),
                        int(job_row["captured_suppression_generation"]) + 1,
                        now,
                    ),
                )
            self._set_terminal_in_transaction(
                job_id,
                status=SummaryJobStatus.SUCCEEDED,
                reason_code="summary_created",
                error_category=None,
            )
            self._connection.execute(
                "DELETE FROM summary_commit_guards WHERE job_id=?",
                (job_id,),
            )
            self._insert_job_audit(
                job_row,
                status=SummaryJobStatus.SUCCEEDED,
                reason_code="summary_created",
                error_category=None,
                created_at=now,
            )
            return self.require_job(job_id)

    def fail_incompatible_job(self, job_id: str) -> None:
        self._terminalize_job(
            job_id,
            status=SummaryJobStatus.FAILED,
            reason_code="incompatible_recovery",
            error_category="compatibility",
        )

    def cancel_job(self, job_id: str) -> None:
        self._terminalize_job(
            job_id,
            status=SummaryJobStatus.CANCELLED,
            reason_code="scheduler_shutdown",
            error_category=None,
        )

    def fail_job(self, job_id: str) -> None:
        self._terminalize_job(
            job_id,
            status=SummaryJobStatus.FAILED,
            reason_code="worker_error",
            error_category="internal",
        )

    def _commit_mismatch_reason(
        self,
        job_row: sqlite3.Row,
        sources: list[sqlite3.Row],
        *,
        provider_policy_fingerprint: str,
        session_deletion_generation: int | None,
    ) -> str | None:
        if (
            int(job_row["source_manifest_sealed"]) != 1
            or len(sources) != int(job_row["source_message_count"])
            or not sources
        ):
            return "discarded_source_changed"
        session_id = str(job_row["session_id"])
        if self._connection.execute(
            "SELECT 1 FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone() is None:
            return "discarded_session_deleted"
        if (
            session_deletion_generation is not None
            and session_deletion_generation
            != int(job_row["captured_session_deletion_generation"])
        ):
            return "discarded_session_deleted"
        barrier = self._connection.execute(
            "SELECT generation FROM memory_summary_barrier WHERE singleton_id=1"
        ).fetchone()
        if (
            barrier is None
            or int(barrier["generation"])
            != int(job_row["captured_barrier_generation"])
        ):
            return "discarded_barrier_changed"
        source_ids = tuple(str(source["message_id"]) for source in sources)
        placeholders = ", ".join("?" for _ in source_ids)
        if self._connection.execute(
            f"SELECT 1 FROM memory_summary_source_exclusions "
            f"WHERE source_message_id IN ({placeholders}) LIMIT 1",
            source_ids,
        ).fetchone() is not None:
            return "discarded_source_excluded"
        current_sources = self._connection.execute(
            """
            SELECT source.chat_turn_id, source.message_id, source.turn_order,
                   source.message_order_in_turn, source.source_order
            FROM summary_job_sources AS source
            JOIN chat_turns AS turn ON turn.id=source.chat_turn_id
            JOIN messages AS message ON message.id=source.message_id
            WHERE source.job_id=? AND turn.session_id=? AND message.session_id=?
            ORDER BY source.source_order
            """,
            (str(job_row["id"]), session_id, session_id),
        ).fetchall()
        if [tuple(row) for row in current_sources] != [
            (
                str(row["chat_turn_id"]),
                str(row["message_id"]),
                int(row["turn_order"]),
                int(row["message_order_in_turn"]),
                int(row["source_order"]),
            )
            for row in sources
        ]:
            return "discarded_source_changed"
        suppression_identity = self._suppression_identity(job_row)
        suppression = self._connection.execute(
            "SELECT generation, state, rebuild_permit_id, bound_job_id "
            "FROM summary_source_suppressions "
            "WHERE session_id=? AND source_set_hash=?",
            (session_id, suppression_identity),
        ).fetchone()
        current_suppression_generation = (
            int(suppression["generation"]) if suppression is not None else 0
        )
        if str(job_row["job_kind"]) == SummaryJobKind.REBUILD.value:
            if (
                suppression is None
                or str(suppression["state"]) != "rebuild_in_progress"
                or suppression["rebuild_permit_id"] != job_row["rebuild_permit_id"]
                or suppression["bound_job_id"] != job_row["id"]
            ):
                return "discarded_rebuild_authority_changed"
        elif suppression is not None and str(suppression["state"]) in {
            "suppressed",
            "rebuild_authorized",
            "rebuild_in_progress",
        }:
            return "discarded_suppressed"
        if current_suppression_generation != int(
            job_row["captured_suppression_generation"]
        ):
            return "discarded_suppression_changed"
        expected_attempt_epoch = summary_attempt_epoch(
            logical_source_identity=str(job_row["logical_source_identity"]),
            processing_consent_generation=int(
                job_row["captured_processing_consent_generation"]
            ),
            processing_policy_fingerprint=(
                str(job_row["captured_processing_policy_fingerprint"])
                if job_row["captured_processing_policy_fingerprint"] is not None
                else None
            ),
            provider_policy_fingerprint=provider_policy_fingerprint,
            session_deletion_generation=int(
                job_row["captured_session_deletion_generation"]
            ),
            suppression_generation=int(
                job_row["captured_suppression_generation"]
            ),
            rebuild_authorization_generation=int(
                job_row["captured_rebuild_authorization_generation"]
            ),
            rebuild_permit_id=(
                str(job_row["rebuild_permit_id"])
                if job_row["rebuild_permit_id"] is not None
                else None
            ),
        )
        if expected_attempt_epoch != str(job_row["attempt_epoch"]):
            return "discarded_provider_policy_changed"
        authority = self._processing_row(DEFAULT_SUMMARY_PROCESSING_SCOPE_ID)
        if (
            authority is None
            or str(authority["status"]) != SummaryAuthorityStatus.GRANTED.value
            or int(authority["generation"])
            != int(job_row["captured_processing_consent_generation"])
            or authority["policy_fingerprint"]
            != job_row["captured_processing_policy_fingerprint"]
        ):
            return "discarded_processing_authority_changed"
        return None

    def _suppression_identity(self, job_row: sqlite3.Row) -> str:
        if str(job_row["job_kind"]) != SummaryJobKind.REBUILD.value:
            return str(job_row["source_set_hash"])
        source_summary_id = job_row["source_summary_id"]
        if source_summary_id is None:
            return ""
        source_summary = self._connection.execute(
            "SELECT session_id, source_set_hash FROM session_summaries WHERE id=?",
            (str(source_summary_id),),
        ).fetchone()
        if (
            source_summary is None
            or str(source_summary["session_id"]) != str(job_row["session_id"])
            or source_summary["source_set_hash"] is None
        ):
            return ""
        return str(source_summary["source_set_hash"])

    def _set_terminal_in_transaction(
        self,
        job_id: str,
        *,
        status: SummaryJobStatus,
        reason_code: str,
        error_category: str | None,
    ) -> None:
        self._connection.execute(
            """
            UPDATE summary_jobs
            SET status=?, reason_code=?, error_category=?, finished_at=?
            WHERE id=? AND status IN ('pending', 'running')
            """,
            (
                status.value,
                reason_code,
                error_category,
                _now().isoformat(),
                job_id,
            ),
        )

    def _insert_job_audit(
        self,
        job_row: sqlite3.Row,
        *,
        status: SummaryJobStatus,
        reason_code: str,
        error_category: str | None,
        created_at: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO summary_job_audits (
                id, job_id, status, outcome, source_message_count,
                source_turn_count, consent_generation, barrier_generation,
                route, provider, model, elapsed_ms, reason_code,
                error_category, schema_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                str(job_row["id"]),
                status.value,
                reason_code,
                int(job_row["source_message_count"]),
                int(job_row["source_turn_count"]),
                int(job_row["captured_processing_consent_generation"]),
                int(job_row["captured_barrier_generation"]),
                str(job_row["route"]),
                job_row["provider"],
                job_row["model"],
                reason_code,
                error_category,
                SUMMARY_AUDIT_SCHEMA_VERSION,
                created_at,
            ),
        )

    def _terminalize_job(
        self,
        job_id: str,
        *,
        status: SummaryJobStatus,
        reason_code: str,
        error_category: str | None,
    ) -> None:
        with self.transaction():
            row = self._connection.execute(
                "SELECT * FROM summary_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if row is None or str(row["status"]) not in {"pending", "running"}:
                return
            now = _now().isoformat()
            self._set_terminal_in_transaction(
                job_id,
                status=status,
                reason_code=reason_code,
                error_category=error_category,
            )
            self._insert_job_audit(
                row,
                status=status,
                reason_code=reason_code,
                error_category=error_category,
                created_at=now,
            )

    def valid_processing_snapshot(
        self,
        policy: SummaryProcessingPolicy,
        scope_id: str = DEFAULT_SUMMARY_PROCESSING_SCOPE_ID,
    ) -> SummaryProcessingAuthoritySnapshot | None:
        row = self._processing_row(scope_id)
        if row is None:
            return None
        fields = _parse_fields(row["disclosed_fields_json"])
        generation = _parse_nonnegative_int(row["generation"])
        fingerprint = policy.fingerprint()
        if not (
            generation is not None
            and str(row["status"]) == SummaryAuthorityStatus.GRANTED.value
            and row["disclosure_version"] == policy.disclosure_version
            and row["purpose"] == policy.purpose
            and row["provider"] == policy.provider
            and fields == policy.disclosed_fields
            and row["policy_fingerprint"] == fingerprint
        ):
            return None
        return SummaryProcessingAuthoritySnapshot(
            generation=generation,
            policy_fingerprint=fingerprint,
            disclosure_version=policy.disclosure_version,
            purpose=policy.purpose,
            provider=policy.provider,
            disclosed_fields=fields,
        )

    def valid_injection_snapshot(
        self,
        policy: SummaryInjectionPolicy,
        scope_id: str = DEFAULT_SUMMARY_INJECTION_SCOPE_ID,
    ) -> SummaryInjectionAuthoritySnapshot | None:
        row = self._injection_row(scope_id)
        if row is None:
            return None
        fields = _parse_fields(row["disclosed_fields_json"])
        generation = _parse_nonnegative_int(row["generation"])
        fragment_count = _parse_positive_int(row["max_fragment_count"])
        fragment_characters = _parse_positive_int(row["max_fragment_characters"])
        total_characters = _parse_positive_int(row["max_total_characters"])
        fingerprint = policy.fingerprint()
        if not (
            generation is not None
            and fragment_count is not None
            and fragment_characters is not None
            and total_characters is not None
            and fragment_characters <= total_characters
            and str(row["status"]) == SummaryAuthorityStatus.GRANTED.value
            and row["disclosure_version"] == policy.disclosure_version
            and row["chat_provider_fingerprint"] == fingerprint
            and fields == policy.disclosed_fields
            and fragment_count == policy.max_fragment_count
            and fragment_characters == policy.max_fragment_characters
            and total_characters == policy.max_total_characters
        ):
            return None
        return SummaryInjectionAuthoritySnapshot(
            generation=generation,
            policy_fingerprint=fingerprint,
            disclosure_version=policy.disclosure_version,
            disclosed_fields=fields,
            max_fragment_count=policy.max_fragment_count,
            max_fragment_characters=policy.max_fragment_characters,
            max_total_characters=policy.max_total_characters,
        )

    def list_authority_audits(self) -> list[SummaryAuthorityAudit]:
        rows = self._connection.execute(
            "SELECT * FROM summary_authority_audits ORDER BY created_at, id"
        ).fetchall()
        return [
            SummaryAuthorityAudit(
                id=str(row["id"]),
                authority_kind=str(row["authority_kind"]),  # type: ignore[arg-type]
                scope_id=str(row["scope_id"]),
                action=str(row["action"]),  # type: ignore[arg-type]
                generation=int(row["generation"]),
                disclosure_version=(
                    str(row["disclosure_version"])
                    if row["disclosure_version"] is not None
                    else None
                ),
                provider=(
                    str(row["provider"]) if row["provider"] is not None else None
                ),
                created_at=datetime.fromisoformat(str(row["created_at"])),
            )
            for row in rows
        ]

    def _validate_job_reservation(
        self,
        *,
        snapshot: SummarySourceSnapshot,
        job_kind: SummaryJobKind,
        route: str,
        provider: str | None,
        model: str | None,
        summarizer_schema_version: str,
        processing_consent_generation: int,
        processing_policy_fingerprint: str | None,
        provider_policy_fingerprint: str,
        session_deletion_generation: int,
        suppression_generation: int,
        rebuild_authorization_generation: int,
        rebuild_permit_id: str | None,
    ) -> None:
        if not isinstance(job_kind, SummaryJobKind):
            raise ValueError("invalid summary job kind")
        if route not in {"fake", "remote"}:
            raise ValueError("invalid summary job route")
        if not summarizer_schema_version.strip() or not provider_policy_fingerprint.strip():
            raise ValueError("summary job policy identity must not be blank")
        generations = (
            snapshot.barrier_generation,
            processing_consent_generation,
            session_deletion_generation,
            suppression_generation,
            rebuild_authorization_generation,
        )
        if any(value < 0 for value in generations):
            raise ValueError("summary job generations must be non-negative")
        if route == "remote" and (
            provider is None
            or not provider.strip()
            or model is None
            or not model.strip()
        ):
            raise ValueError("remote summary job requires provider identity")
        if route == "fake" and (provider is not None or model is not None):
            raise ValueError("fake summary job cannot claim a remote provider")
        if job_kind is SummaryJobKind.REBUILD and rebuild_permit_id is None:
            raise ValueError("rebuild summary job requires a permit")
        if job_kind is SummaryJobKind.INCREMENTAL and rebuild_permit_id is not None:
            raise ValueError("incremental summary job cannot bind a rebuild permit")
        if not snapshot.turns or snapshot.source_set_hash is None:
            raise ValueError("source snapshot must contain complete turns")
        current_barrier = self._connection.execute(
            "SELECT generation FROM memory_summary_barrier WHERE singleton_id=1"
        ).fetchone()
        if (
            current_barrier is None
            or int(current_barrier["generation"]) != snapshot.barrier_generation
        ):
            raise ValueError("source snapshot barrier is stale")
        session_exists = self._connection.execute(
            "SELECT 1 FROM sessions WHERE id=?",
            (snapshot.session_id,),
        ).fetchone()
        if session_exists is None:
            raise ValueError("source snapshot session does not exist")
        expected_hash = canonical_summary_source_set_hash(
            session_id=snapshot.session_id,
            turns=tuple(
                {
                    "turn_id": turn.id,
                    "turn_order": turn.turn_order,
                    "messages": tuple(
                        {
                            "message_id": message.id,
                            "message_order_in_turn": message.message_order_in_turn,
                        }
                        for message in turn.messages
                    ),
                }
                for turn in snapshot.turns
            ),
        )
        if snapshot.source_set_hash != expected_hash:
            raise ValueError("source snapshot hash is invalid")
        expected_order = 1
        for index, turn in enumerate(snapshot.turns):
            if index and turn.turn_order <= snapshot.turns[index - 1].turn_order:
                raise ValueError("source snapshot turn order is invalid")
            if tuple(message.message_order_in_turn for message in turn.messages) != (0, 1):
                raise ValueError("source snapshot message order is invalid")
            row = self._connection.execute(
                """
                SELECT session_id, user_message_id, assistant_message_id, turn_order
                FROM chat_turns WHERE id=?
                """,
                (turn.id,),
            ).fetchone()
            if (
                row is None
                or str(row["session_id"]) != snapshot.session_id
                or int(row["turn_order"]) != turn.turn_order
                or str(row["user_message_id"]) != turn.messages[0].id
                or str(row["assistant_message_id"]) != turn.messages[1].id
            ):
                raise ValueError("source snapshot does not match durable chat turns")
            excluded = self._connection.execute(
                "SELECT 1 FROM memory_summary_source_exclusions "
                "WHERE source_message_id IN (?, ?) LIMIT 1",
                (turn.messages[0].id, turn.messages[1].id),
            ).fetchone()
            if excluded is not None:
                raise ValueError("source snapshot contains an excluded turn")
            expected_order += 2

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> SummaryJob:
        return SummaryJob(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            job_kind=SummaryJobKind(str(row["job_kind"])),
            status=SummaryJobStatus(str(row["status"])),
            logical_source_identity=str(row["logical_source_identity"]),
            attempt_epoch=str(row["attempt_epoch"]),
            source_set_hash=str(row["source_set_hash"]),
            source_message_count=int(row["source_message_count"]),
            source_turn_count=int(row["source_turn_count"]),
            captured_barrier_generation=int(row["captured_barrier_generation"]),
            captured_processing_consent_generation=int(
                row["captured_processing_consent_generation"]
            ),
            captured_processing_policy_fingerprint=(
                str(row["captured_processing_policy_fingerprint"])
                if row["captured_processing_policy_fingerprint"] is not None
                else None
            ),
            captured_session_deletion_generation=int(
                row["captured_session_deletion_generation"]
            ),
            captured_suppression_generation=int(
                row["captured_suppression_generation"]
            ),
            captured_rebuild_authorization_generation=int(
                row["captured_rebuild_authorization_generation"]
            ),
            rebuild_permit_id=(
                str(row["rebuild_permit_id"])
                if row["rebuild_permit_id"] is not None
                else None
            ),
            source_summary_id=(
                str(row["source_summary_id"])
                if row["source_summary_id"] is not None
                else None
            ),
            route=str(row["route"]),  # type: ignore[arg-type]
            provider=(str(row["provider"]) if row["provider"] is not None else None),
            model=str(row["model"]) if row["model"] is not None else None,
            summarizer_schema_version=str(row["summarizer_schema_version"]),
            job_schema_version=str(row["job_schema_version"]),
            attempt_count=int(row["attempt_count"]),
            reason_code=(
                str(row["reason_code"]) if row["reason_code"] is not None else None
            ),
            error_category=(
                str(row["error_category"])
                if row["error_category"] is not None
                else None
            ),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            started_at=(
                datetime.fromisoformat(str(row["started_at"]))
                if row["started_at"] is not None
                else None
            ),
            finished_at=(
                datetime.fromisoformat(str(row["finished_at"]))
                if row["finished_at"] is not None
                else None
            ),
        )

    def _ensure_processing_row(self, scope_id: str) -> sqlite3.Row:
        row = self._processing_row(scope_id)
        if row is None:
            now = _now().isoformat()
            self._connection.execute(
                """
                INSERT INTO summary_processing_consents (
                    scope_id, status, disclosure_version, purpose, provider,
                    disclosed_fields_json, policy_fingerprint, generation, updated_at
                ) VALUES (?, 'unknown', NULL, NULL, NULL, '[]', NULL, 0, ?)
                ON CONFLICT(scope_id) DO NOTHING
                """,
                (scope_id, now),
            )
            row = self._processing_row(scope_id)
        assert row is not None
        return row

    def _ensure_injection_row(self, scope_id: str) -> sqlite3.Row:
        row = self._injection_row(scope_id)
        if row is None:
            now = _now().isoformat()
            self._connection.execute(
                """
                INSERT INTO summary_injection_consents (
                    scope_id, status, disclosure_version, chat_provider_fingerprint,
                    disclosed_fields_json, generation, max_fragment_count,
                    max_fragment_characters, max_total_characters, updated_at
                ) VALUES (?, 'unknown', NULL, NULL, '[]', 0, 1, 1, 1, ?)
                ON CONFLICT(scope_id) DO NOTHING
                """,
                (scope_id, now),
            )
            row = self._injection_row(scope_id)
        assert row is not None
        return row

    def _processing_row(self, scope_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM summary_processing_consents WHERE scope_id=?",
            (scope_id,),
        ).fetchone()

    def _injection_row(self, scope_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM summary_injection_consents WHERE scope_id=?",
            (scope_id,),
        ).fetchone()

    @staticmethod
    def _require_generation(row: sqlite3.Row, expected_generation: int) -> None:
        actual_generation = _parse_nonnegative_int(row["generation"])
        if actual_generation is None:
            raise SummaryAuthorityStateError()
        if expected_generation < 0 or actual_generation != expected_generation:
            raise SummaryAuthorityVersionConflictError()

    def _insert_audit(
        self,
        *,
        authority_kind: Literal["processing", "injection"],
        scope_id: str,
        action: SummaryAuthorityAction,
        generation: int,
        disclosure_version: str | None,
        provider: str | None,
        created_at: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO summary_authority_audits (
                id, authority_kind, scope_id, action, generation,
                disclosure_version, provider, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                authority_kind,
                scope_id,
                action,
                generation,
                disclosure_version,
                provider,
                created_at,
            ),
        )

    @staticmethod
    def _processing_authority(row: sqlite3.Row) -> SummaryProcessingAuthority:
        status = _parse_status(row["status"])
        generation = _parse_nonnegative_int(row["generation"])
        fields = _parse_fields(row["disclosed_fields_json"])
        try:
            updated_at = datetime.fromisoformat(str(row["updated_at"]))
        except ValueError as exc:
            raise SummaryAuthorityStateError() from exc
        granted = status is SummaryAuthorityStatus.GRANTED
        if (
            status is None
            or generation is None
            or (granted and not fields)
        ):
            raise SummaryAuthorityStateError()
        return SummaryProcessingAuthority(
            scope_id=str(row["scope_id"]),
            status=status,
            disclosure_version=(
                str(row["disclosure_version"])
                if granted and row["disclosure_version"] is not None
                else None
            ),
            purpose=(
                str(row["purpose"])
                if granted and row["purpose"] is not None
                else None
            ),
            provider=(
                str(row["provider"])
                if granted and row["provider"] is not None
                else None
            ),
            disclosed_fields=fields if granted else (),
            generation=generation,
            updated_at=updated_at,
        )

    @staticmethod
    def _injection_authority(row: sqlite3.Row) -> SummaryInjectionAuthority:
        status = _parse_status(row["status"])
        generation = _parse_nonnegative_int(row["generation"])
        fields = _parse_fields(row["disclosed_fields_json"])
        fragment_count = _parse_positive_int(row["max_fragment_count"])
        fragment_characters = _parse_positive_int(row["max_fragment_characters"])
        total_characters = _parse_positive_int(row["max_total_characters"])
        try:
            updated_at = datetime.fromisoformat(str(row["updated_at"]))
        except ValueError as exc:
            raise SummaryAuthorityStateError() from exc
        granted = status is SummaryAuthorityStatus.GRANTED
        if (
            status is None
            or generation is None
            or fragment_count is None
            or fragment_characters is None
            or total_characters is None
            or fragment_characters > total_characters
            or (granted and not fields)
        ):
            raise SummaryAuthorityStateError()
        return SummaryInjectionAuthority(
            scope_id=str(row["scope_id"]),
            status=status,
            disclosure_version=(
                str(row["disclosure_version"])
                if granted and row["disclosure_version"] is not None
                else None
            ),
            disclosed_fields=fields if granted else (),
            generation=generation,
            max_fragment_count=fragment_count if granted else None,
            max_fragment_characters=fragment_characters if granted else None,
            max_total_characters=total_characters if granted else None,
            updated_at=updated_at,
        )
