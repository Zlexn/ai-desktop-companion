from collections import Counter
from dataclasses import dataclass
import logging

from app.core.config import Settings
from app.core.errors import ProviderInvalidResponseError, ValidationAppError
from app.domain.models import ChatRole
from app.providers.base import (
    ChatDispatchBudget,
    LLMOptions,
    LLMProvider,
    LLMResponse,
)
from app.repositories.chat_turns import ChatTurnRepository
from app.repositories.context_sources import ContextSourceRepository
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.services.context_composer import (
    ContextComposer,
    ContextCompositionRequest,
    ContextCompositionResult,
)
from app.services.emotion_analysis_scheduler import EmotionAnalysisScheduler
from app.services.emotion_context import EmotionContextFormatter, EmotionSnapshotReader
from app.services.emotion_service import CompletedTurnEmotionUpdater
from app.services.expression_plan_service import ExpressionPlanService
from app.services.memory_candidate_service import MemoryCandidateService
from app.services.memory_job_scheduler import MemoryJobScheduler
from app.services.persona_contract import CONTEXT_MANIFEST_VERSION
from app.services.persona_service import PersonaService
from app.services.session_summary_scheduler import SessionSummaryScheduler
from app.services.summary_dispatch import SummaryDisclosureFence
from app.services.summary_injection import SummaryInjectionService


logger = logging.getLogger(__name__)

_PROVIDER_METADATA_KEYS = {
    "finish_reason",
    "completion_id",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
}


@dataclass(frozen=True)
class ChatReply:
    reply: str
    provider: str
    model: str
    assistant_message_id: str


def build_context_manifest(
    composition: ContextCompositionResult,
) -> dict[str, object]:
    trim_reason_counts = Counter(
        decision.reason_code for decision in composition.trim_decisions
    )
    return {
        "schema_version": CONTEXT_MANIFEST_VERSION,
        "persona_artifact_id": composition.persona_artifact_id,
        "composer_version": composition.composer_version,
        "encoder_version": composition.encoder_version,
        "selected_recent_message_ids": list(
            composition.selected_recent_message_ids
        ),
        "selected_memory_version_ids": list(
            composition.selected_memory_version_ids
        ),
        "source_emotion_version": composition.source_emotion_version,
        "relationship_projection_id": composition.relationship_projection_id,
        "relationship_projection_version": (
            composition.relationship_projection_version
        ),
        "selected_summary_ids": list(composition.selected_summary_ids),
        "selected_counts": {
            "recent_messages": len(composition.selected_recent_message_ids),
            "memory_versions": len(composition.selected_memory_version_ids),
            "summaries": len(composition.selected_summary_ids),
        },
        "trim_reason_counts": dict(sorted(trim_reason_counts.items())),
        "provider_character_count": composition.provider_character_count,
        "max_characters": composition.max_characters,
    }


class ChatService:
    def __init__(
        self,
        sessions: SessionRepository,
        messages: MessageRepository,
        chat_turns: ChatTurnRepository,
        persona_service: PersonaService,
        context_sources: ContextSourceRepository,
        context_composer: ContextComposer,
        provider: LLMProvider,
        settings: Settings,
        memory_candidates: MemoryCandidateService | None = None,
        memory_job_scheduler: MemoryJobScheduler | None = None,
        summary_scheduler: SessionSummaryScheduler | None = None,
        emotion_updater: CompletedTurnEmotionUpdater | None = None,
        emotion_analysis_scheduler: EmotionAnalysisScheduler | None = None,
        emotion_snapshot_reader: EmotionSnapshotReader | None = None,
        emotion_context_formatter: EmotionContextFormatter | None = None,
        expression_plans: ExpressionPlanService | None = None,
        summary_disclosure_fence: SummaryDisclosureFence | None = None,
    ) -> None:
        self._sessions = sessions
        self._messages = messages
        self._chat_turns = chat_turns
        self._persona_service = persona_service
        self._context_sources = context_sources
        self._context_composer = context_composer
        self._provider = provider
        self._settings = settings
        self._memory_candidates = memory_candidates
        self._memory_job_scheduler = memory_job_scheduler
        self._summary_scheduler = summary_scheduler
        self._emotion_updater = emotion_updater
        self._emotion_analysis_scheduler = emotion_analysis_scheduler
        self._emotion_snapshot_reader = emotion_snapshot_reader
        self._emotion_context_formatter = emotion_context_formatter
        self._expression_plans = expression_plans
        self._summary_injection = (
            SummaryInjectionService(context_sources, summary_disclosure_fence)
            if summary_disclosure_fence is not None
            else None
        )

    async def send_message(self, session_id: str, user_text: str) -> ChatReply:
        clean_text = user_text.strip()
        self._validate_current_user_text(clean_text)

        self._sessions.require(session_id)
        user_message = self._messages.add(session_id, ChatRole.USER, clean_text)
        persona = self._persona_service.current().artifact

        snapshot = None
        emotion_view = None
        if self._emotion_snapshot_reader is not None:
            try:
                snapshot = self._emotion_snapshot_reader.get_state(apply_decay=True)
                if self._emotion_context_formatter is not None:
                    emotion_view = self._emotion_context_formatter.to_expression_view(
                        snapshot
                    )
            except Exception:
                snapshot = None
                emotion_view = None

        sources = self._context_sources.snapshot(
            session_id=session_id,
            current_user_message_id=user_message.id,
            query=clean_text,
            recent_limit=self._settings.recent_context_messages,
            memory_limit=(
                self._settings.memory_context_limit
                if self._settings.memory_context_enabled
                else 0
            ),
            memory_fallback_limit=(
                self._settings.memory_retrieval_fallback_limit
            ),
        )

        if (
            self._provider.provider_name != self._settings.llm_provider
            and sources.summaries
        ):
            sources = type(sources)(
                recent_messages=sources.recent_messages,
                memories=sources.memories,
                summaries=(),
                summary_authority=None,
            )

        composition_request = ContextCompositionRequest(
            provider_name=self._provider.provider_name,
            session_id=session_id,
            current_user_message_id=user_message.id,
            current_user_text=clean_text,
            persona=persona,
            recent_messages=sources.recent_messages,
            memories=sources.memories,
            emotion=emotion_view,
            summaries=sources.summaries,
        )
        composition = self._context_composer.compose(
            composition_request,
            max_characters=self._settings.chat_context_max_characters,
        )
        if self._summary_injection is not None and sources.summaries:
            async with self._summary_injection.revalidate_for_dispatch(
                session_id=session_id,
                current_user_message_id=user_message.id,
                current_user_text=clean_text,
                sources=sources,
            ) as current_sources:
                if current_sources != sources:
                    composition = self._context_composer.compose(
                        ContextCompositionRequest(
                            provider_name=self._provider.provider_name,
                            session_id=session_id,
                            current_user_message_id=user_message.id,
                            current_user_text=clean_text,
                            persona=persona,
                            recent_messages=current_sources.recent_messages,
                            memories=current_sources.memories,
                            emotion=emotion_view,
                            summaries=current_sources.summaries,
                        ),
                        max_characters=self._settings.chat_context_max_characters,
                    )
                response = await self._generate(composition)
        else:
            response = await self._generate(composition)
        reply = response.text.strip()
        if not reply:
            raise ProviderInvalidResponseError()

        if "context_manifest" in response.metadata:
            logger.warning(
                "Provider metadata attempted to use reserved context manifest namespace",
                extra={"error_category": "provider_metadata_reserved_collision"},
            )
        provider_metadata = {
            key: value
            for key, value in response.metadata.items()
            if key in _PROVIDER_METADATA_KEYS
        }
        assistant_metadata = {
            **provider_metadata,
            "provider": response.provider,
            "model": response.model,
            "context_manifest": build_context_manifest(composition),
        }
        assistant_message, _completed_turn = self._chat_turns.append_assistant_turn(
            session_id=session_id,
            user_message_id=user_message.id,
            content=reply,
            metadata=assistant_metadata,
        )
        if snapshot is not None and self._expression_plans is not None:
            try:
                self._expression_plans.create_for_assistant_message(
                    assistant_message.id,
                    snapshot,
                )
            except Exception:
                # Expression planning must never break an already-persisted reply.
                pass
        if self._settings.memory_automation_mode == "candidate_confirmation":
            if self._memory_candidates is not None:
                try:
                    await self._memory_candidates.create_candidates_from_user_text(
                        session_id=session_id,
                        user_text=clean_text,
                    )
                except Exception:
                    # Candidate extraction must never break the chat path.
                    pass
        elif self._settings.memory_automation_mode in {
            "shadow_auto",
            "auto_active",
        }:
            if self._memory_job_scheduler is not None:
                try:
                    self._memory_job_scheduler.schedule(
                        session_id=session_id,
                        user_message_id=user_message.id,
                        assistant_message_id=assistant_message.id,
                        persona_artifact_id=composition.persona_artifact_id,
                        chat_turn_id=_completed_turn.id,
                        turn_completed_at=assistant_message.created_at,
                    )
                except Exception:
                    # Shadow scheduling must never break an already-persisted reply.
                    pass
        if self._summary_scheduler is not None:
            try:
                self._summary_scheduler.schedule(
                    session_id,
                    chat_turn_id=_completed_turn.id,
                )
            except Exception:
                # Summary scheduling must never break the chat path.
                pass
        local_emotion_state = None
        local_emotion_updated = self._emotion_updater is None
        if self._emotion_updater is not None:
            try:
                local_emotion_state = self._emotion_updater.update(
                    session_id,
                    user_message,
                    assistant_message,
                )
                local_emotion_updated = True
            except Exception:
                # Emotion updates must never break an already-persisted reply.
                pass
        if (
            local_emotion_updated
            and local_emotion_state is not None
            and self._emotion_analysis_scheduler is not None
        ):
            try:
                self._emotion_analysis_scheduler.schedule(
                    user_message.id,
                    assistant_message.id,
                    local_emotion_state.version,
                )
            except Exception:
                # Remote analysis scheduling must never break an already-persisted reply.
                pass
        return ChatReply(
            reply=reply,
            provider=response.provider,
            model=response.model,
            assistant_message_id=assistant_message.id,
        )

    async def _generate(
        self,
        composition: ContextCompositionResult,
    ) -> LLMResponse:
        return await self._provider.generate(
            list(composition.provider_messages),
            LLMOptions(
                model=self._settings.llm_model,
                timeout_seconds=self._settings.llm_timeout_seconds,
                max_retries=self._settings.llm_max_retries,
                chat_dispatch_budget=ChatDispatchBudget(
                    expected_normalized_characters=(
                        composition.provider_character_count
                    ),
                    max_normalized_characters=composition.max_characters,
                ),
            ),
        )

    def _validate_current_user_text(self, text: str) -> None:
        if not text:
            raise ValidationAppError("消息内容不能为空。")
        if len(text) > self._settings.chat_current_user_max_characters:
            raise ValidationAppError("消息内容过长。")
