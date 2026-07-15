from pathlib import Path

from app.domain.models import (
    DEFAULT_EMOTION_SCOPE_ID,
    EmotionAnalysisAuditOutcome,
    EmotionAnalysisConsentStatus,
    EmotionAnalysisJobStatus,
)
from app.repositories.emotion_analysis import EmotionAnalysisRepository
from app.repositories.sqlite import managed_connection


_POLICY_FINGERPRINT = "emotion-analysis-policy-v1"


def test_consent_defaults_to_unknown_and_persists_transitions(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'consent.db'}"
    with managed_connection(database_url) as connection:
        repository = EmotionAnalysisRepository(connection)
        initial = repository.get_consent()
        granted = repository.set_consent(
            status=EmotionAnalysisConsentStatus.GRANTED,
            disclosure_version="emotion-analysis-disclosure-v1",
            provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
        )

        assert initial.scope_id == DEFAULT_EMOTION_SCOPE_ID
        assert initial.status is EmotionAnalysisConsentStatus.UNKNOWN
        assert granted.status is EmotionAnalysisConsentStatus.GRANTED
        assert granted.disclosure_version == "emotion-analysis-disclosure-v1"
        assert granted.provider == "deepseek"
        assert granted.updated_at >= initial.updated_at

    with managed_connection(database_url) as connection:
        persisted = EmotionAnalysisRepository(connection).get_consent()
        assert persisted.status is EmotionAnalysisConsentStatus.GRANTED


def test_consent_supports_decline_revoke_and_regrant(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'consent-transitions.db'}"
    with managed_connection(database_url) as connection:
        repository = EmotionAnalysisRepository(connection)
        for status in (
            EmotionAnalysisConsentStatus.DECLINED,
            EmotionAnalysisConsentStatus.GRANTED,
            EmotionAnalysisConsentStatus.REVOKED,
            EmotionAnalysisConsentStatus.GRANTED,
        ):
            consent = repository.set_consent(
                status=status,
                disclosure_version="emotion-analysis-disclosure-v1",
                provider="deepseek",
            policy_fingerprint=_POLICY_FINGERPRINT,
            )
            assert consent.status is status


def test_job_reservation_is_idempotent_per_assistant_and_schema(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    with managed_connection(database_url) as connection:
        repository = EmotionAnalysisRepository(connection)
        first, first_created = repository.reserve_job(
            source_session_id="session-1",
            source_user_message_id="user-1",
            source_assistant_message_id="assistant-1",
            schema_version="emotion_analysis_v1",
            base_emotion_version=0,
            consent_generation=1,
        )
        duplicate, duplicate_created = repository.reserve_job(
            source_session_id="session-1",
            source_user_message_id="user-1",
            source_assistant_message_id="assistant-1",
            schema_version="emotion_analysis_v1",
            base_emotion_version=0,
            consent_generation=1,
        )

        assert first_created is True
        assert duplicate_created is False
        assert duplicate.id == first.id
        assert first.status is EmotionAnalysisJobStatus.QUEUED
        assert connection.execute("SELECT COUNT(*) FROM emotion_analysis_jobs").fetchone()[0] == 1


def test_job_status_updates_without_storing_payload(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'job-status.db'}"
    with managed_connection(database_url) as connection:
        repository = EmotionAnalysisRepository(connection)
        job, _ = repository.reserve_job(
            source_session_id="session-1",
            source_user_message_id="user-1",
            source_assistant_message_id="assistant-1",
            schema_version="emotion_analysis_v1",
            base_emotion_version=0,
            consent_generation=1,
        )
        updated = repository.update_job_status(
            job.id,
            status=EmotionAnalysisJobStatus.SUCCEEDED,
            outcome_reason="applied",
        )

        assert updated.status is EmotionAnalysisJobStatus.SUCCEEDED
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(emotion_analysis_jobs)").fetchall()
        }
        assert columns.isdisjoint({"prompt", "response", "content", "payload"})


def test_recover_stale_jobs_marks_queued_and_running_interrupted(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'recover.db'}"
    with managed_connection(database_url) as connection:
        repository = EmotionAnalysisRepository(connection)
        queued, _ = repository.reserve_job(
            source_session_id="session-1",
            source_user_message_id="user-1",
            source_assistant_message_id="assistant-1",
            schema_version="emotion_analysis_v1",
            base_emotion_version=0,
            consent_generation=1,
        )
        running, _ = repository.reserve_job(
            source_session_id="session-1",
            source_user_message_id="user-2",
            source_assistant_message_id="assistant-2",
            schema_version="emotion_analysis_v1",
            base_emotion_version=0,
            consent_generation=1,
        )
        repository.update_job_status(
            running.id,
            status=EmotionAnalysisJobStatus.RUNNING,
            outcome_reason=None,
        )

        recovered = repository.recover_incomplete_jobs()

        assert recovered == 2
        rows = connection.execute(
            "SELECT status, outcome_reason FROM emotion_analysis_jobs ORDER BY source_assistant_message_id"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("failed", "interrupted"),
            ("failed", "interrupted"),
        ]


    database_url = f"sqlite:///{tmp_path / 'audit.db'}"
    with managed_connection(database_url) as connection:
        repository = EmotionAnalysisRepository(connection)
        audit = repository.append_audit(
            job_id="job-1",
            outcome=EmotionAnalysisAuditOutcome.APPLIED,
            source_session_id="session-1",
            source_user_message_id="user-1",
            source_assistant_message_id="assistant-1",
            schema_version="emotion_analysis_v1",
            provider="deepseek",
            model="deepseek-v4-flash",
            message_count=4,
            memory_count=2,
            input_characters=1234,
            redaction_count=1,
            elapsed_ms=200,
            reason_code="applied",
        )

        assert repository.list_audits(limit=10) == [audit]
        assert audit.outcome is EmotionAnalysisAuditOutcome.APPLIED
        assert audit.message_count == 4
        assert audit.memory_count == 2
        assert audit.redaction_count == 1
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(emotion_analysis_audits)").fetchall()
        }
        assert columns.isdisjoint({"prompt", "response", "content", "payload", "memory_text"})
