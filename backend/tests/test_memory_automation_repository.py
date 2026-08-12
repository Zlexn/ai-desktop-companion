import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.domain.models import (
    MemoryAutomationMode,
    MemoryAutoActiveJobSnapshot,
    MemoryExtractionConsentStatus,
    MemoryExtractorRoute,
    MemoryJobAuditOutcome,
    MemoryJobStatus,
)
from app.repositories.memory_automation import (
    DEFAULT_MEMORY_EXTRACTION_SCOPE_ID,
    MemoryAutomationRepository,
)
from app.repositories.personas import PersonaRepository
from app.repositories.sqlite import managed_connection
from app.services.persona_compiler import PersonaCompiler
from app.services.persona_service import PersonaService
from app.services.prompt_renderer import default_prompt_renderer


_SCHEMA_VERSION = "memory-shadow-schema-v1"
_GOVERNOR_VERSION = "memory-governor-rules-v1"


def _seed_turn(database_url: str, *, suffix: str = "1") -> dict[str, str]:
    ids = {
        "session_id": f"session-{suffix}",
        "user_message_id": f"user-{suffix}",
        "assistant_message_id": f"assistant-{suffix}",
    }
    with managed_connection(database_url) as connection:
        connection.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (ids["session_id"], "test", "2026-07-16T00:00:00+00:00", "2026-07-16T00:00:00+00:00"),
        )
        connection.executemany(
            """
            INSERT INTO messages (id, session_id, role, content, metadata_json, created_at)
            VALUES (?, ?, ?, ?, '{}', ?)
            """,
            (
                (
                    ids["user_message_id"],
                    ids["session_id"],
                    "user",
                    "transient user fixture",
                    "2026-07-16T00:00:01+00:00",
                ),
                (
                    ids["assistant_message_id"],
                    ids["session_id"],
                    "assistant",
                    "transient assistant fixture",
                    "2026-07-16T00:00:02+00:00",
                ),
            ),
        )
        connection.commit()
    return ids


def _reserve(
    database_url: str,
    ids: dict[str, str],
    *,
    schema_version: str = _SCHEMA_VERSION,
) -> tuple[Any, bool]:
    with managed_connection(database_url) as connection:
        return MemoryAutomationRepository(connection).reserve_job(
            turn_id=ids["assistant_message_id"],
            schema_version=schema_version,
            session_id=ids["session_id"],
            user_message_id=ids["user_message_id"],
            assistant_message_id=ids["assistant_message_id"],
            mode=MemoryAutomationMode.SHADOW_AUTO,
            extractor_route=MemoryExtractorRoute.LOCAL,
            governor_version=_GOVERNOR_VERSION,
        )


def _complete_success(repository: MemoryAutomationRepository, job_id: str):
    return repository.complete_job_with_audit(
        job_id,
        status=MemoryJobStatus.SUCCEEDED,
        outcome=MemoryJobAuditOutcome.SHADOW_RECORDED,
        decision_counts={"reject": 1, "create": 2},
        reason_counts={"eligible_shadow_create": 2, "invalid_source": 1},
        proposal_count=3,
        accepted_count=2,
        rejected_count=1,
        redaction_count=0,
        provider="local",
        model="memory-local-rules-v1",
        elapsed_ms=4,
        consent_generation=None,
    )


def test_consent_defaults_unknown_and_mutations_increment_generation(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'consent.db'}"

    with managed_connection(database_url) as connection:
        initial = MemoryAutomationRepository(connection).get_consent()

    assert initial.scope_id == DEFAULT_MEMORY_EXTRACTION_SCOPE_ID
    assert initial.generation == 0
    assert initial.status is MemoryExtractionConsentStatus.UNKNOWN
    assert initial.purpose is None
    assert initial.provider is None
    assert initial.disclosure_version is None
    assert initial.disclosed_fields == ()
    assert initial.created_at == initial.updated_at

    with managed_connection(database_url) as connection:
        granted = MemoryAutomationRepository(connection).set_consent(
            status=MemoryExtractionConsentStatus.GRANTED,
            purpose="extract durable memory proposals from the current completed turn",
            provider="anthropic",
            disclosure_version="memory-extraction-disclosure-v1",
            disclosed_fields=("user_message", "assistant_message"),
        )
    with managed_connection(database_url) as connection:
        declined = MemoryAutomationRepository(connection).set_consent(
            status=MemoryExtractionConsentStatus.DECLINED,
            purpose=granted.purpose or "",
            provider="anthropic",
            disclosure_version="memory-extraction-disclosure-v1",
            disclosed_fields=("user_message", "assistant_message"),
        )
    with managed_connection(database_url) as connection:
        revoked = MemoryAutomationRepository(connection).set_consent(
            status=MemoryExtractionConsentStatus.REVOKED,
            purpose=granted.purpose or "",
            provider="anthropic",
            disclosure_version="memory-extraction-disclosure-v1",
            disclosed_fields=("user_message", "assistant_message"),
        )

    assert granted.generation == 1
    assert declined.generation == 2
    assert revoked.generation == 3
    assert revoked.status is MemoryExtractionConsentStatus.REVOKED
    assert revoked.created_at == initial.created_at
    assert revoked.updated_at >= granted.updated_at


def test_concurrent_first_consent_reads_create_one_unknown_row(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'consent-race.db'}"
    with managed_connection(database_url):
        pass
    barrier = threading.Barrier(2)
    results: list[Any] = []
    errors: list[BaseException] = []

    def read() -> None:
        try:
            with managed_connection(database_url) as connection:
                barrier.wait()
                results.append(MemoryAutomationRepository(connection).get_consent())
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=read) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == 2
    assert {item.generation for item in results} == {0}
    with managed_connection(database_url) as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_extraction_consents").fetchone()[0] == 1


def _seed_persona(database_url: str) -> str:
    renderer = default_prompt_renderer()
    with managed_connection(database_url) as connection:
        service = PersonaService(
            PersonaRepository(connection),
            compiler=PersonaCompiler(
                template_text=renderer.load_template_text(),
                persona_max_characters=8_000,
            ),
            bootstrap_config=renderer.load_persona_v1_config(),
        )
        return service.bootstrap().artifact.id


def test_new_job_persists_and_freezes_exact_persona_provenance(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'persona-provenance.db'}"
    ids = _seed_turn(database_url)
    persona_id = _seed_persona(database_url)

    with managed_connection(database_url) as connection:
        repository = MemoryAutomationRepository(connection)
        job, created = repository.reserve_job(
            turn_id=ids["assistant_message_id"],
            schema_version=_SCHEMA_VERSION,
            session_id=ids["session_id"],
            user_message_id=ids["user_message_id"],
            assistant_message_id=ids["assistant_message_id"],
            mode=MemoryAutomationMode.SHADOW_AUTO,
            extractor_route=MemoryExtractorRoute.LOCAL,
            governor_version=_GOVERNOR_VERSION,
            persona_artifact_id=persona_id,
        )
        assert created
        assert job.persona_artifact_id == persona_id
        with pytest.raises(
            sqlite3.IntegrityError,
            match="memory job reservation snapshot is immutable",
        ):
            connection.execute(
                "UPDATE memory_jobs SET persona_artifact_id = NULL WHERE id = ?",
                (job.id,),
            )


def test_legacy_null_persona_provenance_remains_compatible(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy-persona-provenance.db'}"
    ids = _seed_turn(database_url)

    job, created = _reserve(database_url, ids)

    assert created
    assert job.persona_artifact_id is None


def test_reserve_job_is_idempotent_sequentially_and_schema_versioned(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'reserve.db'}"
    ids = _seed_turn(database_url)

    reservations = [_reserve(database_url, ids) for _ in range(20)]
    version_two = _reserve(database_url, ids, schema_version="memory-shadow-schema-v2")

    assert len({job.id for job, _ in reservations}) == 1
    assert sum(created for _, created in reservations) == 1
    assert version_two[1] is True
    assert version_two[0].id != reservations[0][0].id


def test_reserve_job_is_idempotent_with_concurrent_own_connections(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'reserve-race.db'}"
    ids = _seed_turn(database_url)
    barrier = threading.Barrier(2)
    results: list[tuple[Any, bool]] = []
    errors: list[BaseException] = []

    def reserve() -> None:
        try:
            with managed_connection(database_url) as connection:
                repository = MemoryAutomationRepository(connection)
                barrier.wait()
                results.append(
                    repository.reserve_job(
                        turn_id=ids["assistant_message_id"],
                        schema_version=_SCHEMA_VERSION,
                        session_id=ids["session_id"],
                        user_message_id=ids["user_message_id"],
                        assistant_message_id=ids["assistant_message_id"],
                        mode=MemoryAutomationMode.SHADOW_AUTO,
                        extractor_route=MemoryExtractorRoute.LOCAL,
                        governor_version=_GOVERNOR_VERSION,
                    )
                )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=reserve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == 2
    assert len({job.id for job, _ in results}) == 1
    assert sum(created for _, created in results) == 1


def test_reserve_auto_active_persists_complete_frozen_snapshot(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'active-snapshot.db'}"
    ids = _seed_turn(database_url)
    completed_at = datetime(2026, 7, 16, 0, 0, 2, tzinfo=UTC)
    snapshot = MemoryAutoActiveJobSnapshot(
        reserved_mode=MemoryAutomationMode.AUTO_ACTIVE,
        workflow_version="memory-auto-active-schema-v1",
        extractor_route=MemoryExtractorRoute.LOCAL,
        governor_version=_GOVERNOR_VERSION,
        commit_policy_version="memory-commit-policy-v1",
        canonicalization_version="memory-canonicalization-v1",
        allowed_memory_types_version="memory-auto-write-types-v1",
        write_consent_generation=3,
        remote_consent_generation=None,
        remote_authority_fingerprint=None,
        global_deletion_generation=1,
        session_deletion_generation=2,
        type_deletion_generations={"preference": 4, "other": 5},
        source_session_reference_hash="session-hash",
        source_user_message_reference_hash="user-hash",
        source_assistant_message_reference_hash="assistant-hash",
        turn_completed_at=completed_at,
    )
    with managed_connection(database_url) as connection:
        repository = MemoryAutomationRepository(connection)
        job, created = repository.reserve_job(
            turn_id=ids["assistant_message_id"],
            schema_version="memory-auto-active-schema-v1",
            session_id=ids["session_id"],
            user_message_id=ids["user_message_id"],
            assistant_message_id=ids["assistant_message_id"],
            mode=MemoryAutomationMode.AUTO_ACTIVE,
            extractor_route=MemoryExtractorRoute.LOCAL,
            governor_version=_GOVERNOR_VERSION,
            auto_active_snapshot=snapshot,
            source_session_reference_hash=snapshot.source_session_reference_hash,
            source_user_message_reference_hash=(
                snapshot.source_user_message_reference_hash
            ),
            source_assistant_message_reference_hash=(
                snapshot.source_assistant_message_reference_hash
            ),
        )

    assert created
    assert job.auto_active_snapshot == snapshot


def test_reserve_auto_active_requires_complete_snapshot_before_sql(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'mode.db'}"
    ids = _seed_turn(database_url)

    with managed_connection(database_url) as connection:
        repository = MemoryAutomationRepository(connection)
        with pytest.raises(ValueError, match="complete frozen snapshot"):
            repository.reserve_job(
                turn_id=ids["assistant_message_id"],
                schema_version=_SCHEMA_VERSION,
                session_id=ids["session_id"],
                user_message_id=ids["user_message_id"],
                assistant_message_id=ids["assistant_message_id"],
                mode=MemoryAutomationMode.AUTO_ACTIVE,
                extractor_route=MemoryExtractorRoute.NONE,
                governor_version=_GOVERNOR_VERSION,
            )
        assert connection.execute("SELECT COUNT(*) FROM memory_jobs").fetchone()[0] == 0


def test_job_state_transitions_attempts_timestamps_and_terminal_immutability(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'states.db'}"
    ids = _seed_turn(database_url)
    job, _ = _reserve(database_url, ids)

    with managed_connection(database_url) as connection:
        repository = MemoryAutomationRepository(connection)
        running = repository.update_job_status(
            job.id,
            status=MemoryJobStatus.RUNNING,
            consent_generation=7,
        )
        assert running.attempt_count == 1
        assert running.started_at is not None
        assert running.finished_at is None
        assert running.consent_generation == 7

        with pytest.raises(ValueError, match="pending to running"):
            repository.update_job_status(job.id, status=MemoryJobStatus.PENDING)

        completed, _ = _complete_success(repository, job.id)
        assert completed.status is MemoryJobStatus.SUCCEEDED
        assert completed.finished_at is not None
        assert completed.started_at == running.started_at
        assert completed.consent_generation == 7

        with pytest.raises(ValueError, match="pending to running"):
            repository.update_job_status(job.id, status=MemoryJobStatus.FAILED)


def test_update_job_status_only_permits_pending_to_running(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'running-only.db'}"
    ids = _seed_turn(database_url)
    job, _ = _reserve(database_url, ids)

    invalid_calls = (
        {"status": MemoryJobStatus.PENDING},
        {"status": MemoryJobStatus.SUCCEEDED},
        {"status": MemoryJobStatus.FAILED},
        {"status": MemoryJobStatus.CANCELLED},
        {
            "status": MemoryJobStatus.RUNNING,
            "outcome": MemoryJobAuditOutcome.SHADOW_RECORDED,
        },
        {"status": MemoryJobStatus.RUNNING, "error_category": "provider_error"},
    )
    with managed_connection(database_url) as connection:
        repository = MemoryAutomationRepository(connection)
        for arguments in invalid_calls:
            with pytest.raises(ValueError, match="pending to running"):
                repository.update_job_status(job.id, **arguments)  # type: ignore[arg-type]
            assert repository.require_job(job.id).status is MemoryJobStatus.PENDING
            assert repository.list_audits(limit=20) == []

        running = repository.update_job_status(
            job.id,
            status=MemoryJobStatus.RUNNING,
            consent_generation=4,
        )
        assert running.status is MemoryJobStatus.RUNNING
        assert running.attempt_count == 1
        assert running.started_at is not None
        assert running.consent_generation == 4

        with pytest.raises(ValueError, match="pending to running"):
            repository.update_job_status(job.id, status=MemoryJobStatus.RUNNING)


def test_complete_job_requires_compatible_status_outcome_and_error_category(tmp_path: Path) -> None:
    cases = (
        (MemoryJobStatus.SUCCEEDED, MemoryJobAuditOutcome.FAILED, None),
        (
            MemoryJobStatus.SUCCEEDED,
            MemoryJobAuditOutcome.SHADOW_RECORDED,
            "provider_error",
        ),
        (MemoryJobStatus.FAILED, MemoryJobAuditOutcome.SHADOW_RECORDED, "provider_error"),
        (MemoryJobStatus.FAILED, MemoryJobAuditOutcome.PROVIDER_ERROR, None),
        (MemoryJobStatus.CANCELLED, MemoryJobAuditOutcome.FAILED, "interrupted"),
        (MemoryJobStatus.CANCELLED, MemoryJobAuditOutcome.CANCELLED, None),
    )
    for index, (status, outcome, error_category) in enumerate(cases):
        database_url = f"sqlite:///{tmp_path / f'compatibility-{index}.db'}"
        ids = _seed_turn(database_url, suffix=str(index))
        job, _ = _reserve(database_url, ids)
        with managed_connection(database_url) as connection:
            repository = MemoryAutomationRepository(connection)
            with pytest.raises(ValueError, match="status, outcome, and error_category"):
                repository.complete_job_with_audit(
                    job.id,
                    status=status,
                    outcome=outcome,
                    decision_counts={},
                    reason_counts={},
                    proposal_count=0,
                    accepted_count=0,
                    rejected_count=0,
                    redaction_count=0,
                    provider=None,
                    model=None,
                    elapsed_ms=None,
                    consent_generation=None,
                    error_category=error_category,
                )
            assert repository.require_job(job.id).status is MemoryJobStatus.PENDING
            assert repository.list_audits(limit=20) == []


def test_complete_job_with_audit_serializes_sorted_metadata_only_maps(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'complete.db'}"
    ids = _seed_turn(database_url)
    job, _ = _reserve(database_url, ids)

    with managed_connection(database_url) as connection:
        repository = MemoryAutomationRepository(connection)
        completed, audit = _complete_success(repository, job.id)
        raw = connection.execute(
            "SELECT decision_counts_json, reason_counts_json, "
            "outcome_counts_json FROM memory_job_audits WHERE job_id = ?",
            (job.id,),
        ).fetchone()

    assert completed.status is MemoryJobStatus.SUCCEEDED
    assert audit.job_id == job.id
    assert audit.decision_counts == {"create": 2, "reject": 1}
    assert audit.reason_counts == {"eligible_shadow_create": 2, "invalid_source": 1}
    assert raw["decision_counts_json"] == '{"create": 2, "reject": 1}'
    assert raw["reason_counts_json"] == '{"eligible_shadow_create": 2, "invalid_source": 1}'
    assert raw["outcome_counts_json"] == "{}"


def test_concurrent_terminal_completion_converges_on_one_audit(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'complete-race.db'}"
    ids = _seed_turn(database_url)
    job, _ = _reserve(database_url, ids)
    barrier = threading.Barrier(2)
    results: list[tuple[Any, Any]] = []
    errors: list[BaseException] = []

    def complete() -> None:
        try:
            with managed_connection(database_url) as connection:
                repository = MemoryAutomationRepository(connection)
                barrier.wait()
                results.append(_complete_success(repository, job.id))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=complete) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == 2
    assert {result_job.id for result_job, _ in results} == {job.id}
    assert len({audit.id for _, audit in results}) == 1
    with managed_connection(database_url) as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_job_audits").fetchone()[0] == 1
        assert connection.execute("SELECT status FROM memory_jobs WHERE id = ?", (job.id,)).fetchone()[0] == "succeeded"


def test_cancel_is_idempotent_and_creates_one_terminal_audit(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'cancel.db'}"
    ids = _seed_turn(database_url)
    job, _ = _reserve(database_url, ids)

    with managed_connection(database_url) as connection:
        repository = MemoryAutomationRepository(connection)
        first = repository.cancel_job(job.id)
        second = repository.cancel_job(job.id)
        audit = repository.list_audits(limit=20)

    assert first == second
    assert first.status is MemoryJobStatus.CANCELLED
    assert first.outcome is MemoryJobAuditOutcome.CANCELLED
    assert first.error_category == "interrupted"
    assert len(audit) == 1
    assert audit[0].proposal_count == 0


def test_recovery_resets_running_and_returns_all_pending_ids_deterministically(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'recovery.db'}"
    ids_one = _seed_turn(database_url, suffix="1")
    ids_two = _seed_turn(database_url, suffix="2")
    ids_three = _seed_turn(database_url, suffix="3")
    pending, _ = _reserve(database_url, ids_one)
    running_one, _ = _reserve(database_url, ids_two)
    running_two, _ = _reserve(database_url, ids_three)

    with managed_connection(database_url) as connection:
        repository = MemoryAutomationRepository(connection)
        before_one = repository.update_job_status(running_one.id, status=MemoryJobStatus.RUNNING)
        before_two = repository.update_job_status(running_two.id, status=MemoryJobStatus.RUNNING)
        recovered_ids = repository.recover_incomplete_jobs()
        recovered_jobs = [repository.require_job(job_id) for job_id in recovered_ids]

    assert recovered_ids == [job.id for job in sorted((pending, running_one, running_two), key=lambda value: (value.created_at, value.id))]
    assert all(job.status is MemoryJobStatus.PENDING for job in recovered_jobs)
    attempts = {job.id: job.attempt_count for job in recovered_jobs}
    assert attempts[running_one.id] == before_one.attempt_count == 1
    assert attempts[running_two.id] == before_two.attempt_count == 1
    assert attempts[pending.id] == 0


def test_recovery_terminalizes_incompatible_jobs_without_returning_them(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'incompatible-recovery.db'}"
    ids = _seed_turn(database_url)
    job, _ = _reserve(database_url, ids)

    with managed_connection(database_url) as connection:
        repository = MemoryAutomationRepository(connection)
        recovered_ids = repository.recover_incomplete_jobs(
            mode=MemoryAutomationMode.SHADOW_AUTO,
            compatible_job=lambda _job: False,
        )
        terminal = repository.require_job(job.id)
        audits = repository.list_audits(limit=10)

    assert recovered_ids == []
    assert terminal.status is MemoryJobStatus.SUCCEEDED
    assert terminal.outcome is MemoryJobAuditOutcome.SKIPPED_MODE_CHANGED
    assert len(audits) == 1
    assert audits[0].proposal_count == 0


@pytest.mark.parametrize(
    ("override", "message"),
    (
        ({"accepted_count": 2}, r"proposal_count must equal accepted_count \+ rejected_count"),
        ({"decision_counts": {"create": 1}}, "decision counts must equal proposal_count"),
        ({"reason_counts": {"eligible_shadow_create": 1}}, "reason counts must equal proposal_count"),
    ),
)
def test_invalid_audit_counts_roll_back_terminal_update(
    tmp_path: Path,
    override: dict[str, object],
    message: str,
) -> None:
    database_url = f"sqlite:///{tmp_path / ('rollback-' + next(iter(override)) + '.db')}"
    ids = _seed_turn(database_url)
    job, _ = _reserve(database_url, ids)
    arguments: dict[str, object] = {
        "status": MemoryJobStatus.SUCCEEDED,
        "outcome": MemoryJobAuditOutcome.SHADOW_RECORDED,
        "decision_counts": {"create": 1, "reject": 1},
        "reason_counts": {"eligible_shadow_create": 1, "invalid_source": 1},
        "proposal_count": 2,
        "accepted_count": 1,
        "rejected_count": 1,
        "redaction_count": 0,
        "provider": "local",
        "model": "memory-local-rules-v1",
        "elapsed_ms": 1,
        "consent_generation": None,
    }
    arguments.update(override)

    with managed_connection(database_url) as connection:
        repository = MemoryAutomationRepository(connection)
        with pytest.raises(ValueError, match=message):
            repository.complete_job_with_audit(job.id, **arguments)  # type: ignore[arg-type]

    with managed_connection(database_url) as connection:
        row = connection.execute("SELECT status, finished_at FROM memory_jobs WHERE id = ?", (job.id,)).fetchone()
        audit_count = connection.execute("SELECT COUNT(*) FROM memory_job_audits").fetchone()[0]
    assert tuple(row) == ("pending", None)
    assert audit_count == 0


def test_transaction_rolls_back_job_and_audit_together_on_insert_failure(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'atomic.db'}"
    ids = _seed_turn(database_url)
    job, _ = _reserve(database_url, ids)

    with managed_connection(database_url) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_memory_audit_insert
            BEFORE INSERT ON memory_job_audits
            BEGIN
                SELECT RAISE(ABORT, 'injected audit failure');
            END
            """
        )
        connection.commit()
        repository = MemoryAutomationRepository(connection)
        with pytest.raises(sqlite3.IntegrityError, match="injected audit failure"):
            _complete_success(repository, job.id)

    with managed_connection(database_url) as connection:
        row = connection.execute("SELECT status, outcome, finished_at FROM memory_jobs WHERE id = ?", (job.id,)).fetchone()
        assert tuple(row) == ("pending", None, None)
        assert connection.execute("SELECT COUNT(*) FROM memory_job_audits").fetchone()[0] == 0


def test_nested_completion_failure_rolls_back_to_savepoint_when_outer_catches(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'nested-atomic.db'}"
    ids = _seed_turn(database_url)
    job, _ = _reserve(database_url, ids)

    with managed_connection(database_url) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_nested_memory_audit_insert
            BEFORE INSERT ON memory_job_audits
            BEGIN
                SELECT RAISE(ABORT, 'injected nested audit failure');
            END
            """
        )
        connection.commit()
        repository = MemoryAutomationRepository(connection)
        with repository.transaction():
            try:
                _complete_success(repository, job.id)
            except sqlite3.IntegrityError as exc:
                assert "injected nested audit failure" in str(exc)

    with managed_connection(database_url) as connection:
        row = connection.execute(
            "SELECT status, outcome, finished_at FROM memory_jobs WHERE id = ?",
            (job.id,),
        ).fetchone()
        assert tuple(row) == ("pending", None, None)
        assert connection.execute("SELECT COUNT(*) FROM memory_job_audits").fetchone()[0] == 0


def test_provider_and_model_identifiers_reject_secret_like_or_unbounded_values(tmp_path: Path) -> None:
    identifiers = (
        ("provider", "sk-secret-provider"),
        ("model", "Bearer private-model"),
        ("provider", "-----BEGIN PRIVATE KEY-----"),
        ("model", "line\nbreak"),
        ("provider", "x" * 129),
        ("model", ""),
    )
    for index, (field, invalid_value) in enumerate(identifiers):
        database_url = f"sqlite:///{tmp_path / f'identifier-{index}.db'}"
        ids = _seed_turn(database_url, suffix=str(index))
        job, _ = _reserve(database_url, ids)
        arguments: dict[str, object] = {
            "status": MemoryJobStatus.FAILED,
            "outcome": MemoryJobAuditOutcome.PROVIDER_ERROR,
            "decision_counts": {},
            "reason_counts": {},
            "proposal_count": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "redaction_count": 0,
            "provider": "anthropic",
            "model": "fixture-model",
            "elapsed_ms": 5,
            "consent_generation": 0,
            "error_category": "provider_error",
        }
        arguments[field] = invalid_value
        with managed_connection(database_url) as connection:
            repository = MemoryAutomationRepository(connection)
            with pytest.raises(ValueError, match="provider and model identifiers"):
                repository.complete_job_with_audit(job.id, **arguments)  # type: ignore[arg-type]
            assert repository.require_job(job.id).status is MemoryJobStatus.PENDING
            persisted = "\n".join(
                str(value)
                for row in connection.execute("SELECT * FROM memory_job_audits").fetchall()
                for value in row
            )
        if invalid_value:
            assert invalid_value not in persisted


def test_persistence_is_metadata_only_even_when_transient_values_contain_secrets(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'privacy.db'}"
    ids = _seed_turn(database_url)
    job, _ = _reserve(database_url, ids)
    transient_proposal = "SECRET_SENTINEL_9f40"
    transient_raw_response = "RAW_RESPONSE_SENTINEL_03c1"
    transient_exception = RuntimeError("provider failed with sk-secret")

    with managed_connection(database_url) as connection:
        repository = MemoryAutomationRepository(connection)
        repository.get_consent()
        repository.complete_job_with_audit(
            job.id,
            status=MemoryJobStatus.FAILED,
            outcome=MemoryJobAuditOutcome.PROVIDER_ERROR,
            decision_counts={},
            reason_counts={},
            proposal_count=0,
            accepted_count=0,
            rejected_count=0,
            redaction_count=0,
            provider="anthropic",
            model="fixture-model",
            elapsed_ms=5,
            consent_generation=0,
            error_category="provider_error",
        )

        persisted = "\n".join(
            str(value)
            for table in (
                "memory_extraction_consents",
                "memory_jobs",
                "memory_job_audits",
            )
            for row in connection.execute(f"SELECT * FROM {table}").fetchall()
            for value in row
        )

    assert transient_proposal not in persisted
    assert transient_raw_response not in persisted
    assert str(transient_exception).split()[-1] not in persisted
    assert "sk-secret" not in persisted


def test_corrupt_persisted_audit_metadata_is_rejected_without_raw_data(tmp_path: Path) -> None:
    corrupt_values = (
        '["not-a-map"]',
        '{malformed',
        '{"create": true}',
        '{"create": "1"}',
        '{"create": -1}',
        '{"bad key": 1}',
        '{"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": 1}',
        '{"create": 2}',
    )
    for index, corrupt_json in enumerate(corrupt_values):
        database_url = f"sqlite:///{tmp_path / f'corrupt-{index}.db'}"
        ids = _seed_turn(database_url, suffix=str(index))
        job, _ = _reserve(database_url, ids)
        with managed_connection(database_url) as connection:
            repository = MemoryAutomationRepository(connection)
            _complete_success(repository, job.id)
            connection.execute(
                "UPDATE memory_job_audits SET decision_counts_json = ? WHERE job_id = ?",
                (corrupt_json, job.id),
            )
            connection.commit()
            with pytest.raises(
                ValueError,
                match="^invalid persisted memory audit metadata$",
            ) as error:
                repository.list_audits(limit=20)
        assert corrupt_json not in str(error.value)


def test_require_and_lists_use_stable_order_and_validate_limits(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'lists.db'}"
    ids_one = _seed_turn(database_url, suffix="1")
    ids_two = _seed_turn(database_url, suffix="2")
    first, _ = _reserve(database_url, ids_one)
    second, _ = _reserve(database_url, ids_two)
    with managed_connection(database_url) as connection:
        repository = MemoryAutomationRepository(connection)
        _complete_success(repository, first.id)
        _complete_success(repository, second.id)
        jobs = repository.list_jobs(limit=20)
        audits = repository.list_audits(limit=20)
        assert repository.require_job(first.id).id == first.id
        with pytest.raises(KeyError):
            repository.require_job("missing")
        with pytest.raises(ValueError, match="limit"):
            repository.list_jobs(limit=0)
        with pytest.raises(ValueError, match="limit"):
            repository.list_audits(limit=101)

    assert [job.id for job in jobs] == [job.id for job in sorted((first, second), key=lambda value: (value.created_at, value.id), reverse=True)]
    assert [audit.job_id for audit in audits] == [
        audit.job_id
        for audit in sorted(audits, key=lambda value: (value.created_at, value.id), reverse=True)
    ]
    assert {audit.job_id for audit in audits} == {first.id, second.id}
    assert json.dumps(audits[0].decision_counts, sort_keys=True) == '{"create": 2, "reject": 1}'
