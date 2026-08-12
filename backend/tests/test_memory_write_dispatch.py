import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.domain.models import (
    MemoryExtractionConsent,
    MemoryExtractionConsentStatus,
    MemoryExtractorRoute,
    MemoryType,
    MemoryWriteActivityOutcome,
    MemoryWriteConsentStatus,
)
from app.repositories.memory_automation import MemoryAutomationRepository
from app.repositories.sqlite import managed_connection
from app.services.memory_extraction_contract import (
    MEMORY_EXTRACTION_DISCLOSED_FIELDS,
    MEMORY_EXTRACTION_DISCLOSURE_VERSION,
    MEMORY_EXTRACTION_PURPOSE,
)
from app.services.memory_extraction_dispatch import MemoryExtractionDispatchFence
from app.services.memory_gate_b_contract import (
    MEMORY_ALLOWED_AUTO_TYPES,
    MEMORY_ALLOWED_AUTO_TYPES_VERSION,
    MEMORY_WRITE_POLICY_VERSION,
    MEMORY_WRITE_PURPOSE,
    MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
)
from app.services.memory_write_dispatch import (
    MemoryWriteDispatchFence,
    MemoryWriteDispatcher,
    exact_write_authority_outcome,
)
from app.services.versioned_memory_commit import WriteAuthoritySnapshot


_NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _grant(repository: MemoryAutomationRepository):
    return repository.set_write_consent(
        status=MemoryWriteConsentStatus.GRANTED,
        purpose=MEMORY_WRITE_PURPOSE,
        policy_version=MEMORY_WRITE_POLICY_VERSION,
        allowed_memory_types_version=MEMORY_ALLOWED_AUTO_TYPES_VERSION,
        allowed_memory_types=MEMORY_ALLOWED_AUTO_TYPES,
        retention_disclosure_version=MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
    )


def _remote_consent(generation: int = 1) -> MemoryExtractionConsent:
    return MemoryExtractionConsent(
        scope_id="default",
        status=MemoryExtractionConsentStatus.GRANTED,
        purpose=MEMORY_EXTRACTION_PURPOSE,
        provider="anthropic",
        disclosure_version=MEMORY_EXTRACTION_DISCLOSURE_VERSION,
        disclosed_fields=MEMORY_EXTRACTION_DISCLOSED_FIELDS,
        generation=generation,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_real_remote_commit_rechecks_remote_authority_in_transaction(
    tmp_path: Path,
) -> None:
    from app.domain.models import (
        MemoryEvidenceExtractorKind,
        MemoryGovernorProposal,
    )
    from app.repositories.versioned_memories import (
        DeletionGenerationSnapshot,
        VersionedMemoryRepository,
    )
    from app.services.memory_commit_policy import MemoryCommitPolicy
    from app.services.memory_extraction_contract import (
        memory_remote_authority_fingerprint,
    )
    from app.services.memory_governor import MemoryGovernor
    from app.services.memory_source_reference import MemorySourceReferenceService
    from app.services.versioned_memory_commit import (
        VersionedMemoryCommitRequest,
        VersionedMemoryCommitService,
        WriteAuthoritySnapshot,
    )

    with managed_connection(f"sqlite:///{tmp_path / 'remote-commit.db'}") as connection:
        consent = _grant(MemoryAutomationRepository(connection))
        connection.execute(
            """
            INSERT INTO memory_extraction_consents (
                scope_id, status, purpose, provider, disclosure_version,
                disclosed_fields_json, generation, created_at, updated_at
            ) VALUES ('default', 'granted', ?, 'anthropic', ?, ?, 2, ?, ?)
            """,
            (
                MEMORY_EXTRACTION_PURPOSE,
                MEMORY_EXTRACTION_DISCLOSURE_VERSION,
                '["user_message","assistant_message"]',
                _NOW.isoformat(),
                _NOW.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES ('s', 'x', ?, ?)",
            (_NOW.isoformat(), _NOW.isoformat()),
        )
        connection.executemany(
            """
            INSERT INTO messages (id, session_id, role, content, metadata_json, created_at)
            VALUES (?, 's', ?, ?, '{}', ?)
            """,
            (
                ("u", "user", "我喜欢红茶。", _NOW.isoformat()),
                ("a", "assistant", "好的。", _NOW.isoformat()),
            ),
        )
        connection.execute(
            """
            INSERT INTO memory_jobs (
                id, turn_id, schema_version, session_id, user_message_id,
                assistant_message_id, mode, extractor_route, status,
                attempt_count, governor_version, consent_generation, created_at
            ) VALUES ('j', 'a', 'memory-shadow-schema-v1', 's', 'u', 'a',
                      'shadow_auto', 'remote', 'pending', 0,
                      'memory-governor-rules-v1', NULL, ?)
            """,
            (_NOW.isoformat(),),
        )
        connection.commit()
        proposal = MemoryGovernorProposal(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户喜欢红茶",
            canonical_key_hint=None,
            confidence=0.9,
            source_message_ids=("u",),
        )
        governor_result = MemoryGovernor(
            max_proposals=3,
            max_proposal_characters=200,
            max_total_characters=600,
        ).evaluate(
            proposal=proposal,
            user_text="我喜欢红茶。",
            user_message_id="u",
            assistant_message_id="a",
        )
        stale_fingerprint = memory_remote_authority_fingerprint(
            generation=1,
            purpose=MEMORY_EXTRACTION_PURPOSE,
            provider="anthropic",
            disclosure_version=MEMORY_EXTRACTION_DISCLOSURE_VERSION,
            disclosed_fields=MEMORY_EXTRACTION_DISCLOSED_FIELDS,
        )
        request = VersionedMemoryCommitRequest(
            job_id="j",
            turn_id="a",
            proposal_index=0,
            proposal=proposal,
            governor_result=governor_result,
            session_id="s",
            user_message_id="u",
            user_text="我喜欢红茶。",
            extractor_kind=MemoryEvidenceExtractorKind.REMOTE,
            provider_identifier="anthropic",
            model_identifier="test-model",
            authority=WriteAuthoritySnapshot(
                write_consent_generation=consent.generation,
                remote_consent_generation=1,
                remote_authority_fingerprint=stale_fingerprint,
                turn_completed_at=consent.granted_at,
            ),
            deletion_snapshot=DeletionGenerationSnapshot(
                global_generation=0,
                session_generation=0,
                type_generations={memory_type: 0 for memory_type in MEMORY_ALLOWED_AUTO_TYPES},
            ),
        )

        result = VersionedMemoryCommitService(
            connection,
            versioned=VersionedMemoryRepository(connection),
            policy=MemoryCommitPolicy(),
            source_references=MemorySourceReferenceService(b"r" * 32),
        ).commit_one(request)

        assert result.outcome is MemoryWriteActivityOutcome.SKIPPED_CONSENT_CHANGED
        assert connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_versions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0] == 0


def test_commit_transaction_rejects_turn_completed_before_grant(tmp_path: Path) -> None:
    from app.domain.models import MemoryEvidenceExtractorKind, MemoryGovernorProposal
    from app.repositories.versioned_memories import DeletionGenerationSnapshot, VersionedMemoryRepository
    from app.services.memory_commit_policy import MemoryCommitPolicy
    from app.services.memory_governor import MemoryGovernor
    from app.services.memory_source_reference import MemorySourceReferenceService
    from app.services.versioned_memory_commit import (
        VersionedMemoryCommitRequest,
        VersionedMemoryCommitService,
        WriteAuthoritySnapshot,
    )

    with managed_connection(f"sqlite:///{tmp_path / 'commit-timing.db'}") as connection:
        repository = MemoryAutomationRepository(connection)
        consent = _grant(repository)
        connection.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES ('s', 'x', ?, ?)",
            (_NOW.isoformat(), _NOW.isoformat()),
        )
        connection.executemany(
            """
            INSERT INTO messages (id, session_id, role, content, metadata_json, created_at)
            VALUES (?, 's', ?, ?, '{}', ?)
            """,
            (
                ("u", "user", "我喜欢红茶。", _NOW.isoformat()),
                ("a", "assistant", "好的。", _NOW.isoformat()),
            ),
        )
        connection.execute(
            """
            INSERT INTO memory_jobs (
                id, turn_id, schema_version, session_id, user_message_id,
                assistant_message_id, mode, extractor_route, status,
                attempt_count, governor_version, consent_generation, created_at
            ) VALUES ('j', 'a', 'memory-shadow-schema-v1', 's', 'u', 'a',
                      'shadow_auto', 'local', 'pending', 0,
                      'memory-governor-rules-v1', NULL, ?)
            """,
            (_NOW.isoformat(),),
        )
        connection.commit()
        proposal = MemoryGovernorProposal(
            memory_type=MemoryType.PREFERENCE,
            subject="饮品偏好",
            content="用户喜欢红茶",
            canonical_key_hint=None,
            confidence=0.9,
            source_message_ids=("u",),
        )
        governor_result = MemoryGovernor(
            max_proposals=3,
            max_proposal_characters=200,
            max_total_characters=600,
        ).evaluate(
            proposal=proposal,
            user_text="我喜欢红茶。",
            user_message_id="u",
            assistant_message_id="a",
        )
        request = VersionedMemoryCommitRequest(
            job_id="j",
            turn_id="a",
            proposal_index=0,
            proposal=proposal,
            governor_result=governor_result,
            session_id="s",
            user_message_id="u",
            user_text="我喜欢红茶。",
            extractor_kind=MemoryEvidenceExtractorKind.LOCAL,
            provider_identifier=None,
            model_identifier="local",
            authority=WriteAuthoritySnapshot(
                write_consent_generation=consent.generation,
                remote_consent_generation=None,
                remote_authority_fingerprint=None,
                turn_completed_at=consent.granted_at - timedelta(seconds=1),
            ),
            deletion_snapshot=DeletionGenerationSnapshot(
                global_generation=0,
                session_generation=0,
                type_generations={memory_type: 0 for memory_type in MEMORY_ALLOWED_AUTO_TYPES},
            ),
        )

        result = VersionedMemoryCommitService(
            connection,
            versioned=VersionedMemoryRepository(connection),
            policy=MemoryCommitPolicy(),
            source_references=MemorySourceReferenceService(b"r" * 32),
        ).commit_one(request)

        assert result.outcome is MemoryWriteActivityOutcome.SKIPPED_TURN_BEFORE_WRITE_GRANT
        assert connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0


def test_write_consent_lazy_default_and_generation_lifecycle(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'consent.db'}") as connection:
        repository = MemoryAutomationRepository(connection)
        initial = repository.get_write_consent()
        granted = _grant(repository)
        declined = repository.set_write_consent(
            status=MemoryWriteConsentStatus.DECLINED,
            purpose=MEMORY_WRITE_PURPOSE,
            policy_version=MEMORY_WRITE_POLICY_VERSION,
            allowed_memory_types_version=MEMORY_ALLOWED_AUTO_TYPES_VERSION,
            allowed_memory_types=MEMORY_ALLOWED_AUTO_TYPES,
            retention_disclosure_version=MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
        )
        revoked = repository.set_write_consent(
            status=MemoryWriteConsentStatus.REVOKED,
            purpose=MEMORY_WRITE_PURPOSE,
            policy_version=MEMORY_WRITE_POLICY_VERSION,
            allowed_memory_types_version=MEMORY_ALLOWED_AUTO_TYPES_VERSION,
            allowed_memory_types=MEMORY_ALLOWED_AUTO_TYPES,
            retention_disclosure_version=MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
        )

        assert initial.status is MemoryWriteConsentStatus.UNKNOWN
        assert initial.allowed_memory_types_version is None
        assert initial.generation == 0 and initial.granted_at is None
        assert granted.allowed_memory_types_version == MEMORY_ALLOWED_AUTO_TYPES_VERSION
        assert granted.generation == 1 and granted.granted_at is not None
        assert declined.generation == 2 and declined.granted_at is None
        assert revoked.generation == 3 and revoked.granted_at is None
        assert initial.created_at == granted.created_at == revoked.created_at
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_write_consents"
        ).fetchone()[0] == 1


def test_invalid_persisted_write_consent_fails_closed(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'invalid.db'}") as connection:
        repository = MemoryAutomationRepository(connection)
        repository.get_write_consent()
        connection.execute(
            "UPDATE memory_write_consents SET allowed_memory_types_json = 'not-json'"
        )
        connection.commit()

        with pytest.raises(ValueError, match="invalid persisted memory write consent"):
            repository.get_write_consent()


def test_later_grant_cannot_authorize_earlier_turn(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'timing.db'}") as connection:
        consent = _grant(MemoryAutomationRepository(connection))

    assert exact_write_authority_outcome(
        consent,
        turn_completed_at=consent.granted_at - timedelta(seconds=1),
    ) is MemoryWriteActivityOutcome.SKIPPED_TURN_BEFORE_WRITE_GRANT


@pytest.mark.asyncio
async def test_pending_write_mutation_blocks_before_extractor(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'pending.db'}") as connection:
        repository = MemoryAutomationRepository(connection)
        grant = _grant(repository)
        fence = MemoryWriteDispatchFence()
        dispatcher = MemoryWriteDispatcher(
            write_fence=fence,
            read_write_consent=repository.get_write_consent,
        )
        mutation = fence.begin_write_consent_mutation()
        extracted = 0
        committed = 0

        async def extract():
            nonlocal extracted
            extracted += 1
            return "proposal"

        async def prepare(value):
            return value

        async def commit(*_args):
            nonlocal committed
            committed += 1

        result = await dispatcher.dispatch(
            route=MemoryExtractorRoute.LOCAL,
            turn_completed_at=grant.granted_at,
            extract=extract,
            prepare_for_commit=prepare,
            commit=commit,
        )
        await mutation.__aenter__()
        await mutation.__aexit__(None, None, None)

        assert result.outcome is MemoryWriteActivityOutcome.SKIPPED_WRITE_CONSENT_CHANGED
        assert extracted == committed == 0


@pytest.mark.asyncio
async def test_revoke_registered_during_extraction_discards_result(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'revoke.db'}"
    with managed_connection(database_url) as connection:
        grant = _grant(MemoryAutomationRepository(connection))
        fence = MemoryWriteDispatchFence()
        extraction_started = asyncio.Event()
        release_extraction = asyncio.Event()
        commits = 0

        def read_consent():
            with managed_connection(database_url) as current:
                return MemoryAutomationRepository(current).get_write_consent()

        dispatcher = MemoryWriteDispatcher(
            write_fence=fence,
            read_write_consent=read_consent,
        )

        async def extract():
            extraction_started.set()
            await release_extraction.wait()
            return "proposal"

        async def commit(*_args):
            nonlocal commits
            commits += 1

        dispatch_task = asyncio.create_task(
            dispatcher.dispatch(
                route=MemoryExtractorRoute.FAKE,
                turn_completed_at=grant.granted_at,
                extract=extract,
                prepare_for_commit=lambda value: asyncio.sleep(0, result=value),
                commit=commit,
            )
        )
        await extraction_started.wait()
        mutation = fence.begin_write_consent_mutation()
        mutation_task = asyncio.create_task(mutation.__aenter__())
        release_extraction.set()
        result = await dispatch_task
        await mutation_task
        with managed_connection(database_url) as current:
            MemoryAutomationRepository(current).set_write_consent(
                status=MemoryWriteConsentStatus.REVOKED,
                purpose=MEMORY_WRITE_PURPOSE,
                policy_version=MEMORY_WRITE_POLICY_VERSION,
                allowed_memory_types_version=MEMORY_ALLOWED_AUTO_TYPES_VERSION,
                allowed_memory_types=MEMORY_ALLOWED_AUTO_TYPES,
                retention_disclosure_version=MEMORY_WRITE_RETENTION_DISCLOSURE_VERSION,
            )
        await mutation.__aexit__(None, None, None)

        assert result.outcome is MemoryWriteActivityOutcome.SKIPPED_WRITE_CONSENT_CHANGED
        assert commits == 0


@pytest.mark.asyncio
async def test_remote_checks_write_before_send_and_remote_after_response(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'remote.db'}"
    with managed_connection(database_url) as connection:
        repository = MemoryAutomationRepository(connection)
        unknown = repository.get_write_consent()
    sends = 0

    async def extract():
        nonlocal sends
        sends += 1
        return "response"

    async def prepare(value):
        return value

    async def commit(*_args):
        return "committed"

    blocked = MemoryWriteDispatcher(
        write_fence=MemoryWriteDispatchFence(),
        read_write_consent=lambda: unknown,
        remote_fence=MemoryExtractionDispatchFence(),
        read_remote_consent=_remote_consent,
        remote_provider="anthropic",
    )
    blocked_result = await blocked.dispatch(
        route=MemoryExtractorRoute.REMOTE,
        turn_completed_at=_NOW,
        extract=extract,
        prepare_for_commit=prepare,
        commit=commit,
    )
    assert blocked_result.outcome is MemoryWriteActivityOutcome.SKIPPED_NO_WRITE_CONSENT
    assert sends == 0

    with managed_connection(database_url) as connection:
        grant = _grant(MemoryAutomationRepository(connection))
    remote_fence = MemoryExtractionDispatchFence()
    remote_state = [_remote_consent()]
    dispatcher = MemoryWriteDispatcher(
        write_fence=MemoryWriteDispatchFence(),
        read_write_consent=lambda: grant,
        remote_fence=remote_fence,
        read_remote_consent=lambda: remote_state[0],
        remote_provider="anthropic",
    )
    prepare_started = asyncio.Event()
    release_prepare = asyncio.Event()

    async def blocked_prepare(value):
        prepare_started.set()
        await release_prepare.wait()
        return value

    task = asyncio.create_task(
        dispatcher.dispatch(
            route=MemoryExtractorRoute.REMOTE,
            turn_completed_at=grant.granted_at,
            extract=extract,
            prepare_for_commit=blocked_prepare,
            commit=commit,
        )
    )
    await prepare_started.wait()
    mutation = remote_fence.begin_consent_mutation()
    mutation_task = asyncio.create_task(mutation.__aenter__())
    release_prepare.set()
    result = await task
    await mutation_task
    remote_state[0] = _remote_consent(generation=2)
    await mutation.__aexit__(None, None, None)

    assert sends == 1
    assert result.outcome is MemoryWriteActivityOutcome.SKIPPED_CONSENT_CHANGED
    assert result.commit_result is None


@pytest.mark.asyncio
async def test_frozen_write_generation_mismatch_blocks_before_extraction(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'frozen-write.db'}") as connection:
        repository = MemoryAutomationRepository(connection)
        grant = _grant(repository)
        calls = 0
        dispatcher = MemoryWriteDispatcher(
            write_fence=MemoryWriteDispatchFence(),
            read_write_consent=repository.get_write_consent,
        )

        async def extract():
            nonlocal calls
            calls += 1
            return "proposal"

        result = await dispatcher.dispatch(
            route=MemoryExtractorRoute.LOCAL,
            turn_completed_at=grant.granted_at,
            extract=extract,
            prepare_for_commit=lambda value: asyncio.sleep(0, result=value),
            commit=lambda *_args: asyncio.sleep(0, result="commit"),
            expected_authority=WriteAuthoritySnapshot(
                write_consent_generation=grant.generation + 1,
                remote_consent_generation=None,
                remote_authority_fingerprint=None,
                turn_completed_at=grant.granted_at,
            ),
        )

    assert calls == 0
    assert result.outcome is MemoryWriteActivityOutcome.SKIPPED_WRITE_CONSENT_CHANGED


@pytest.mark.asyncio
async def test_happy_local_dispatch_reaches_commit_once(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'happy.db'}") as connection:
        repository = MemoryAutomationRepository(connection)
        grant = _grant(repository)
        commits = []
        dispatcher = MemoryWriteDispatcher(
            write_fence=MemoryWriteDispatchFence(),
            read_write_consent=repository.get_write_consent,
        )

        async def commit(prepared, write_snapshot, remote_snapshot):
            commits.append((prepared, write_snapshot, remote_snapshot))
            return "ok"

        result = await dispatcher.dispatch(
            route=MemoryExtractorRoute.LOCAL,
            turn_completed_at=grant.granted_at,
            extract=lambda: asyncio.sleep(0, result="proposal"),
            prepare_for_commit=lambda value: asyncio.sleep(0, result=value),
            commit=commit,
        )

        assert result.outcome is None
        assert result.commit_result == "ok"
        assert len(commits) == 1
        assert commits[0][2] is None
