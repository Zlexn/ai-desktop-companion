from __future__ import annotations

import sqlite3
from collections.abc import Callable

from app.core.config import Settings
from app.domain.models import SessionSummary
from app.domain.session_summary import SummaryJob, SummaryJobKind
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.messages import MessageRepository
from app.repositories.session_summaries import SessionSummaryRepository
from app.repositories.summary_automation import (
    SummaryAutomationRepository,
    SummaryInjectionPolicy,
    SummaryProcessingPolicy,
)
from app.services.session_summary_contract import (
    SUMMARY_INJECTION_DISCLOSED_FIELDS,
    SUMMARY_INJECTION_DISCLOSURE_VERSION,
    SUMMARY_INJECTION_PURPOSE,
    SUMMARY_INJECTION_SCHEMA_VERSION,
    SUMMARY_PROCESSING_DISCLOSED_FIELDS,
    SUMMARY_PROCESSING_DISCLOSURE_VERSION,
    SUMMARY_PROCESSING_PURPOSE,
    SUMMARY_SCHEMA_VERSION,
    summary_provider_policy_fingerprint,
)
from app.services.session_summary_provider import (
    SessionSummaryOptions,
    SessionSummaryProvider,
)
from app.services.session_summary_sanitizer import sanitize_summary_text


def build_summary_processing_policy(settings: Settings) -> SummaryProcessingPolicy:
    if settings.session_summary_provider == "fake":
        return SummaryProcessingPolicy(
            route="local",
            disclosure_version=SUMMARY_PROCESSING_DISCLOSURE_VERSION,
            purpose=SUMMARY_PROCESSING_PURPOSE,
            provider="fake",
            model="fake-session-summary-v1",
            endpoint_policy="local-process-v1",
            summarizer_schema_version=SUMMARY_SCHEMA_VERSION,
            disclosed_fields=SUMMARY_PROCESSING_DISCLOSED_FIELDS,
        )
    provider = settings.session_summary_llm_provider
    return SummaryProcessingPolicy(
        route="remote",
        disclosure_version=SUMMARY_PROCESSING_DISCLOSURE_VERSION,
        purpose=SUMMARY_PROCESSING_PURPOSE,
        provider=provider,
        model=settings.session_summary_llm_model,
        endpoint_policy=(
            settings.deepseek_base_url.rstrip("/")
            if provider == "deepseek"
            else "anthropic-default"
        ),
        summarizer_schema_version=SUMMARY_SCHEMA_VERSION,
        disclosed_fields=SUMMARY_PROCESSING_DISCLOSED_FIELDS,
    )


def summary_provider_policy_for_settings(settings: Settings) -> str:
    policy = build_summary_processing_policy(settings)
    if settings.session_summary_provider == "fake":
        return summary_provider_policy_fingerprint(
            route="fake",
            provider="fake",
            model="fake-session-summary-v1",
            schema_version=SUMMARY_SCHEMA_VERSION,
            max_output_characters=settings.session_summary_max_output_characters,
        )
    return summary_provider_policy_fingerprint(
        route="remote",
        provider=policy.provider,
        model=policy.model,
        endpoint_policy=policy.endpoint_policy,
        schema_version=SUMMARY_SCHEMA_VERSION,
        max_tokens=settings.session_summary_llm_max_tokens,
        timeout_seconds=settings.session_summary_llm_timeout_seconds,
        max_retries=settings.session_summary_llm_max_retries,
        max_output_characters=settings.session_summary_max_output_characters,
    )


def build_summary_injection_policy(settings: Settings) -> SummaryInjectionPolicy:
    route = "local" if settings.llm_provider == "fake" else "remote"
    endpoint_policy = (
        "local-chat-v1"
        if route == "local"
        else (
            settings.deepseek_base_url.rstrip("/")
            if settings.llm_provider == "deepseek"
            else "anthropic-default"
        )
    )
    return SummaryInjectionPolicy(
        route=route,
        disclosure_version=SUMMARY_INJECTION_DISCLOSURE_VERSION,
        purpose=SUMMARY_INJECTION_PURPOSE,
        chat_provider=settings.llm_provider,
        chat_model=settings.llm_model,
        endpoint_policy=endpoint_policy,
        injection_schema_version=SUMMARY_INJECTION_SCHEMA_VERSION,
        disclosed_fields=SUMMARY_INJECTION_DISCLOSED_FIELDS,
        max_fragment_count=settings.summary_injection_max_fragments,
        max_fragment_characters=(
            settings.summary_injection_max_fragment_characters
        ),
        max_total_characters=settings.summary_injection_max_total_characters,
    )


class SummaryJobReservationService:
    """Build and persist C2 job metadata without constructing a Provider."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        settings: Settings,
        session_deletion_generation: Callable[[str], int] | None = None,
    ) -> None:
        self._connection = connection
        self._settings = settings
        self._session_deletion_generation = session_deletion_generation or (
            lambda _session_id: 0
        )

    def reserve_for_turn(
        self,
        session_id: str,
        chat_turn_id: str,
    ) -> tuple[SummaryJob, bool] | None:
        turns = ChatTurnRepository(self._connection)
        trigger_turn = turns.get(chat_turn_id)
        if (
            trigger_turn is None
            or trigger_turn.session_id != session_id
            or not self._is_latest_turn(trigger_turn.id, session_id)
        ):
            return None
        snapshot = turns.snapshot_generation_sources(
            session_id=session_id,
            after_turn_order=self._latest_completed_turn_order(session_id),
            max_turns=self._settings.session_summary_max_input_turns,
            max_messages=self._settings.session_summary_max_input_messages,
            max_characters=self._settings.session_summary_max_input_characters,
        )
        if (
            snapshot.candidate_turn_count
            < self._settings.session_summary_trigger_turn_count
            or not snapshot.turns
            or snapshot.turns[-1].id != chat_turn_id
        ):
            return None

        automation = SummaryAutomationRepository(self._connection)
        route = "fake" if self._settings.session_summary_provider == "fake" else "remote"
        policy = self._processing_policy()
        authority = automation.valid_processing_snapshot(policy)
        provider = None
        model = None
        policy_fingerprint = None
        processing_generation = automation.get_processing_authority().generation
        if authority is not None:
            policy_fingerprint = authority.policy_fingerprint
            processing_generation = authority.generation
        if route == "remote":
            provider = self._settings.session_summary_llm_provider
            model = self._settings.session_summary_llm_model

        reserved = automation.reserve_job(
            snapshot=snapshot,
            job_kind=SummaryJobKind.INCREMENTAL,
            route=route,
            provider=provider,
            model=model,
            summarizer_schema_version=SUMMARY_SCHEMA_VERSION,
            processing_consent_generation=processing_generation,
            processing_policy_fingerprint=policy_fingerprint,
            provider_policy_fingerprint=summary_provider_policy_for_settings(
                self._settings
            ),
            session_deletion_generation=self._session_deletion_generation(session_id),
            suppression_generation=0,
            rebuild_authorization_generation=0,
            rebuild_permit_id=None,
        )
        if authority is None:
            automation.skip_no_consent_job(reserved[0].id)
            return automation.require_job(reserved[0].id), reserved[1]
        return reserved

    def _is_latest_turn(self, chat_turn_id: str, session_id: str) -> bool:
        row = self._connection.execute(
            """
            SELECT id FROM chat_turns
            WHERE session_id=? ORDER BY turn_order DESC, id DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        return row is not None and str(row["id"]) == chat_turn_id

    def _latest_completed_turn_order(self, session_id: str) -> int:
        row = self._connection.execute(
            """
            SELECT MAX(source.turn_order) AS latest_order
            FROM session_summaries AS summary
            JOIN session_summary_sources AS source ON source.summary_id=summary.id
            WHERE summary.session_id=? AND summary.source='generated'
              AND summary.payload_state='active'
              AND summary.provenance_state='exact'
            """,
            (session_id,),
        ).fetchone()
        if row is None or row["latest_order"] is None:
            return 0
        return int(row["latest_order"])

    def _processing_policy(self) -> SummaryProcessingPolicy:
        return build_summary_processing_policy(self._settings)

    def _provider_policy_fingerprint(self, route: str) -> str:
        del route
        return summary_provider_policy_for_settings(self._settings)


class SessionSummaryService:
    def __init__(
        self,
        messages: MessageRepository,
        summaries: SessionSummaryRepository,
        provider: SessionSummaryProvider,
        settings: Settings,
    ) -> None:
        self._messages = messages
        self._summaries = summaries
        self._provider = provider
        self._settings = settings

    async def maybe_generate_for_session(self, session_id: str) -> SessionSummary | None:
        if not self._settings.session_summary_enabled:
            return None

        latest = self._summaries.latest_covered_for_session(session_id)
        snapshot = self._summaries.snapshot_generation_sources(
            session_id=session_id,
            after_message_id=(
                latest.covered_message_end_id if latest is not None else None
            ),
            limit=self._settings.session_summary_max_input_messages,
        )
        if (
            snapshot.candidate_message_count
            < self._settings.session_summary_trigger_message_count
        ):
            return None
        batch = list(snapshot.messages)
        if not batch:
            return None
        try:
            result = await self._provider.generate(
                batch,
                SessionSummaryOptions(
                    max_tokens=self._settings.session_summary_llm_max_tokens,
                    timeout_seconds=self._settings.session_summary_llm_timeout_seconds,
                    max_retries=self._settings.session_summary_llm_max_retries,
                ),
            )
        except Exception:
            return None

        clean_text = sanitize_summary_text(result.text)
        if not clean_text:
            return None
        metadata = {
            "provider": result.provider,
            "model": result.model,
            "summary_schema": "session_summary_v1",
            "trigger_message_count": self._settings.session_summary_trigger_message_count,
            "max_input_messages": self._settings.session_summary_max_input_messages,
            "candidate_message_count": snapshot.candidate_message_count,
            "input_message_count": len(batch),
        }
        try:
            return self._summaries.commit_generated_if_current(
                session_id=session_id,
                summary_text=clean_text,
                source_message_ids=tuple(message.id for message in batch),
                observed_memory_summary_barrier=snapshot.barrier_generation,
                metadata=metadata,
            )
        except Exception:
            return None
