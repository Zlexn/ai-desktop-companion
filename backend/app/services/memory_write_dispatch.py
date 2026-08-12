from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import AsyncIterator, Generic, TypeVar

from app.domain.models import (
    MemoryExtractionConsent,
    MemoryExtractionConsentStatus,
    MemoryExtractorRoute,
    MemoryWriteActivityOutcome,
    MemoryWriteConsent,
    MemoryWriteConsentStatus,
)
from app.services.memory_extraction_contract import (
    MEMORY_EXTRACTION_DISCLOSED_FIELDS,
    MEMORY_EXTRACTION_DISCLOSURE_VERSION,
    MEMORY_EXTRACTION_PURPOSE,
    memory_remote_authority_fingerprint,
)
from app.services.memory_extraction_dispatch import MemoryExtractionDispatchFence
from app.services.memory_gate_b_contract import (
    MEMORY_ALLOWED_AUTO_TYPES,
    MEMORY_ALLOWED_AUTO_TYPES_VERSION,
    MEMORY_WRITE_POLICY_VERSION,
    MEMORY_WRITE_PURPOSE,
    MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
)
from app.services.versioned_memory_commit import WriteAuthoritySnapshot


TExtraction = TypeVar("TExtraction")
TPrepared = TypeVar("TPrepared")
TCommit = TypeVar("TCommit")


class WriteConsentMutation:
    def __init__(self, fence: MemoryWriteDispatchFence) -> None:
        self._fence = fence
        self._entered = False

    async def __aenter__(self) -> None:
        try:
            await self._fence._lock.acquire()
        except BaseException:
            self._fence._pending_mutations -= 1
            raise
        self._entered = True

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if self._entered:
            self._fence._lock.release()
            self._entered = False
        self._fence._pending_mutations -= 1


class MemoryWriteDispatchFence:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending_mutations = 0

    def begin_write_consent_mutation(self) -> WriteConsentMutation:
        self._pending_mutations += 1
        return WriteConsentMutation(self)

    def has_pending_write_consent_mutation(self) -> bool:
        return self._pending_mutations > 0

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[bool]:
        async with self._lock:
            yield self._pending_mutations == 0


@dataclass(frozen=True)
class RemoteAuthoritySnapshot:
    generation: int
    purpose: str
    provider: str
    disclosure_version: str
    disclosed_fields: tuple[str, ...]


@dataclass(frozen=True)
class MemoryWriteDispatchResult(Generic[TExtraction, TCommit]):
    outcome: MemoryWriteActivityOutcome | None
    extraction: TExtraction | None
    commit_result: TCommit | None
    write_authority: WriteAuthoritySnapshot | None
    remote_authority: RemoteAuthoritySnapshot | None


def exact_write_authority_outcome(
    consent: MemoryWriteConsent,
    *,
    turn_completed_at: datetime,
) -> MemoryWriteActivityOutcome | None:
    exact_identity = (
        consent.status is MemoryWriteConsentStatus.GRANTED
        and consent.purpose == MEMORY_WRITE_PURPOSE
        and consent.policy_version == MEMORY_WRITE_POLICY_VERSION
        and consent.allowed_memory_types_version
        == MEMORY_ALLOWED_AUTO_TYPES_VERSION
        and consent.retention_disclosure_version
        == MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION
        and consent.allowed_memory_types == MEMORY_ALLOWED_AUTO_TYPES
    )
    if not exact_identity:
        return MemoryWriteActivityOutcome.SKIPPED_NO_WRITE_CONSENT
    if consent.granted_at is None or consent.granted_at > turn_completed_at:
        return MemoryWriteActivityOutcome.SKIPPED_TURN_BEFORE_WRITE_GRANT
    return None


def _same_write_authority(
    before: MemoryWriteConsent,
    after: MemoryWriteConsent,
    *,
    turn_completed_at: datetime,
) -> bool:
    return (
        before == after
        and exact_write_authority_outcome(
            after,
            turn_completed_at=turn_completed_at,
        )
        is None
    )


def _remote_snapshot(
    consent: MemoryExtractionConsent,
    *,
    provider: str,
) -> RemoteAuthoritySnapshot | None:
    if not (
        consent.status is MemoryExtractionConsentStatus.GRANTED
        and consent.purpose == MEMORY_EXTRACTION_PURPOSE
        and consent.provider == provider
        and consent.disclosure_version == MEMORY_EXTRACTION_DISCLOSURE_VERSION
        and consent.disclosed_fields == MEMORY_EXTRACTION_DISCLOSED_FIELDS
    ):
        return None
    return RemoteAuthoritySnapshot(
        generation=consent.generation,
        purpose=str(consent.purpose),
        provider=provider,
        disclosure_version=str(consent.disclosure_version),
        disclosed_fields=consent.disclosed_fields,
    )


class MemoryWriteDispatcher:
    def __init__(
        self,
        *,
        write_fence: MemoryWriteDispatchFence,
        read_write_consent: Callable[[], MemoryWriteConsent],
        remote_fence: MemoryExtractionDispatchFence | None = None,
        read_remote_consent: Callable[[], MemoryExtractionConsent] | None = None,
        remote_provider: str | None = None,
    ) -> None:
        self._write_fence = write_fence
        self._read_write_consent = read_write_consent
        self._remote_fence = remote_fence
        self._read_remote_consent = read_remote_consent
        self._remote_provider = remote_provider

    async def dispatch(
        self,
        *,
        route: MemoryExtractorRoute,
        turn_completed_at: datetime,
        extract: Callable[[], Awaitable[TExtraction]],
        prepare_for_commit: Callable[[TExtraction], Awaitable[TPrepared]],
        commit: Callable[
            [TPrepared, WriteAuthoritySnapshot, RemoteAuthoritySnapshot | None],
            Awaitable[TCommit],
        ],
        expected_authority: WriteAuthoritySnapshot | None = None,
    ) -> MemoryWriteDispatchResult[TExtraction, TCommit]:
        async with self._write_fence.hold() as write_available:
            if not write_available:
                return self._skipped(
                    MemoryWriteActivityOutcome.SKIPPED_WRITE_CONSENT_CHANGED
                )
            before_write = self._read_write_consent()
            write_outcome = exact_write_authority_outcome(
                before_write,
                turn_completed_at=turn_completed_at,
            )
            if write_outcome is not None:
                return self._skipped(write_outcome)
            if (
                expected_authority is not None
                and before_write.generation
                != expected_authority.write_consent_generation
            ):
                return self._skipped(
                    MemoryWriteActivityOutcome.SKIPPED_WRITE_CONSENT_CHANGED
                )
            write_snapshot = WriteAuthoritySnapshot(
                write_consent_generation=before_write.generation,
                remote_consent_generation=None,
                remote_authority_fingerprint=None,
                turn_completed_at=turn_completed_at,
            )
            if route is MemoryExtractorRoute.REMOTE:
                return await self._dispatch_remote(
                    turn_completed_at=turn_completed_at,
                    before_write=before_write,
                    write_snapshot=write_snapshot,
                    extract=extract,
                    prepare_for_commit=prepare_for_commit,
                    commit=commit,
                    expected_authority=expected_authority,
                )
            extracted = await extract()
            prepared = await prepare_for_commit(extracted)
            if self._write_fence.has_pending_write_consent_mutation():
                return self._skipped(
                    MemoryWriteActivityOutcome.SKIPPED_WRITE_CONSENT_CHANGED,
                    extraction=extracted,
                )
            after_write = self._read_write_consent()
            if not _same_write_authority(
                before_write,
                after_write,
                turn_completed_at=turn_completed_at,
            ):
                return self._skipped(
                    MemoryWriteActivityOutcome.SKIPPED_WRITE_CONSENT_CHANGED,
                    extraction=extracted,
                )
            committed = await commit(prepared, write_snapshot, None)
            return MemoryWriteDispatchResult(
                outcome=None,
                extraction=extracted,
                commit_result=committed,
                write_authority=write_snapshot,
                remote_authority=None,
            )

    async def _dispatch_remote(
        self,
        *,
        turn_completed_at: datetime,
        before_write: MemoryWriteConsent,
        write_snapshot: WriteAuthoritySnapshot,
        extract: Callable[[], Awaitable[TExtraction]],
        prepare_for_commit: Callable[[TExtraction], Awaitable[TPrepared]],
        commit: Callable[
            [TPrepared, WriteAuthoritySnapshot, RemoteAuthoritySnapshot | None],
            Awaitable[TCommit],
        ],
        expected_authority: WriteAuthoritySnapshot | None,
    ) -> MemoryWriteDispatchResult[TExtraction, TCommit]:
        if (
            self._remote_fence is None
            or self._read_remote_consent is None
            or not self._remote_provider
        ):
            return self._skipped(MemoryWriteActivityOutcome.SKIPPED_NO_CONSENT)
        async with self._remote_fence.hold() as remote_available:
            if not remote_available:
                return self._skipped(
                    MemoryWriteActivityOutcome.SKIPPED_CONSENT_CHANGED
                )
            before_remote = self._read_remote_consent()
            remote_snapshot = _remote_snapshot(
                before_remote,
                provider=self._remote_provider,
            )
            if remote_snapshot is None:
                return self._skipped(MemoryWriteActivityOutcome.SKIPPED_NO_CONSENT)
            if expected_authority is not None and (
                remote_snapshot.generation
                != expected_authority.remote_consent_generation
                or memory_remote_authority_fingerprint(
                    generation=remote_snapshot.generation,
                    purpose=remote_snapshot.purpose,
                    provider=remote_snapshot.provider,
                    disclosure_version=remote_snapshot.disclosure_version,
                    disclosed_fields=remote_snapshot.disclosed_fields,
                )
                != expected_authority.remote_authority_fingerprint
            ):
                return self._skipped(
                    MemoryWriteActivityOutcome.SKIPPED_CONSENT_CHANGED
                )
            extracted = await extract()
            prepared = await prepare_for_commit(extracted)
            if self._write_fence.has_pending_write_consent_mutation():
                return self._skipped(
                    MemoryWriteActivityOutcome.SKIPPED_WRITE_CONSENT_CHANGED,
                    extraction=extracted,
                )
            if self._remote_fence.has_pending_consent_mutation():
                return self._skipped(
                    MemoryWriteActivityOutcome.SKIPPED_CONSENT_CHANGED,
                    extraction=extracted,
                )
            after_write = self._read_write_consent()
            after_remote = self._read_remote_consent()
            if not _same_write_authority(
                before_write,
                after_write,
                turn_completed_at=turn_completed_at,
            ):
                return self._skipped(
                    MemoryWriteActivityOutcome.SKIPPED_WRITE_CONSENT_CHANGED,
                    extraction=extracted,
                )
            if _remote_snapshot(
                after_remote,
                provider=self._remote_provider,
            ) != remote_snapshot:
                return self._skipped(
                    MemoryWriteActivityOutcome.SKIPPED_CONSENT_CHANGED,
                    extraction=extracted,
                )
            remote_authority_fingerprint = memory_remote_authority_fingerprint(
                generation=remote_snapshot.generation,
                purpose=remote_snapshot.purpose,
                provider=remote_snapshot.provider,
                disclosure_version=remote_snapshot.disclosure_version,
                disclosed_fields=remote_snapshot.disclosed_fields,
            )
            current_write_snapshot = WriteAuthoritySnapshot(
                write_consent_generation=write_snapshot.write_consent_generation,
                remote_consent_generation=remote_snapshot.generation,
                remote_authority_fingerprint=remote_authority_fingerprint,
                turn_completed_at=turn_completed_at,
            )
            committed = await commit(
                prepared,
                current_write_snapshot,
                remote_snapshot,
            )
            return MemoryWriteDispatchResult(
                outcome=None,
                extraction=extracted,
                commit_result=committed,
                write_authority=current_write_snapshot,
                remote_authority=remote_snapshot,
            )

    @staticmethod
    def _skipped(
        outcome: MemoryWriteActivityOutcome,
        *,
        extraction: TExtraction | None = None,
    ) -> MemoryWriteDispatchResult[TExtraction, TCommit]:
        return MemoryWriteDispatchResult(
            outcome=outcome,
            extraction=extraction,
            commit_result=None,
            write_authority=None,
            remote_authority=None,
        )
