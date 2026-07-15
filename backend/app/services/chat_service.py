from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import ProviderInvalidResponseError, ValidationAppError
from app.domain.models import ChatRole
from app.services.emotion_analysis_scheduler import EmotionAnalysisScheduler
from app.services.emotion_context import EmotionSnapshotReader
from app.services.emotion_service import CompletedTurnEmotionUpdater
from app.services.expression_plan_service import ExpressionPlanService
from app.providers.base import LLMMessage, LLMOptions, LLMProvider
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.services.context_builder import ContextBuilder
from app.services.memory_candidate_service import MemoryCandidateService
from app.services.prompt_renderer import PromptRenderer
from app.services.session_summary_scheduler import SessionSummaryScheduler


@dataclass(frozen=True)
class ChatReply:
    reply: str
    provider: str
    model: str
    assistant_message_id: str


class ChatService:
    def __init__(
        self,
        sessions: SessionRepository,
        messages: MessageRepository,
        context_builder: ContextBuilder,
        prompt_renderer: PromptRenderer,
        provider: LLMProvider,
        settings: Settings,
        memory_candidates: MemoryCandidateService | None = None,
        summary_scheduler: SessionSummaryScheduler | None = None,
        emotion_updater: CompletedTurnEmotionUpdater | None = None,
        emotion_analysis_scheduler: EmotionAnalysisScheduler | None = None,
        emotion_snapshot_reader: EmotionSnapshotReader | None = None,
        expression_plans: ExpressionPlanService | None = None,
    ) -> None:
        self._sessions = sessions
        self._messages = messages
        self._context_builder = context_builder
        self._prompt_renderer = prompt_renderer
        self._provider = provider
        self._settings = settings
        self._memory_candidates = memory_candidates
        self._summary_scheduler = summary_scheduler
        self._emotion_updater = emotion_updater
        self._emotion_analysis_scheduler = emotion_analysis_scheduler
        self._emotion_snapshot_reader = emotion_snapshot_reader
        self._expression_plans = expression_plans

    async def send_message(self, session_id: str, user_text: str) -> ChatReply:
        clean_text = user_text.strip()
        if not clean_text:
            raise ValidationAppError("消息内容不能为空。")

        self._sessions.require(session_id)
        user_message = self._messages.add(session_id, ChatRole.USER, clean_text)

        system_prompt = self._prompt_renderer.render()
        snapshot = None
        if self._emotion_snapshot_reader is not None:
            try:
                snapshot = self._emotion_snapshot_reader.get_state(apply_decay=True)
            except Exception:
                pass
        emotion_context = self._context_builder.build_emotion_context(snapshot)
        context = self._context_builder.build_context(
            session_id,
            query=clean_text,
            emotion_context=emotion_context,
        )
        emotion_context_count = len(emotion_context)
        provider_messages = self._fit_provider_messages(
            [LLMMessage(role=ChatRole.SYSTEM, content=system_prompt), *context],
            self._settings.chat_context_max_characters,
            protected_system_messages=emotion_context_count,
        )
        response = await self._provider.generate(
            provider_messages,
            LLMOptions(
                model=self._settings.llm_model,
                timeout_seconds=self._settings.llm_timeout_seconds,
                max_retries=self._settings.llm_max_retries,
            ),
        )
        reply = response.text.strip()
        if not reply:
            raise ProviderInvalidResponseError()

        assistant_metadata = {"provider": response.provider, "model": response.model}
        assistant_metadata.update(response.metadata)
        assistant_message = self._messages.add(
            session_id,
            ChatRole.ASSISTANT,
            reply,
            assistant_metadata,
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
        if self._memory_candidates is not None:
            try:
                await self._memory_candidates.create_candidates_from_user_text(
                    session_id=session_id,
                    user_text=clean_text,
                )
            except Exception:
                # Candidate extraction must never break the chat path.
                pass
        if self._summary_scheduler is not None:
            try:
                self._summary_scheduler.schedule(session_id)
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

    @staticmethod
    def _fit_provider_messages(
        messages: list[LLMMessage],
        max_characters: int,
        *,
        protected_system_messages: int = 0,
    ) -> list[LLMMessage]:
        if len(messages) <= 2:
            return messages

        kept = list(messages)
        protected_indexes = set(range(1, 1 + protected_system_messages))
        while ChatService._provider_character_count(kept) > max_characters and len(kept) > 2:
            removable_index = next(
                (
                    index
                    for index, message in enumerate(kept[1:-1], start=1)
                    if index not in protected_indexes and message.role in {ChatRole.USER, ChatRole.ASSISTANT}
                ),
                None,
            )
            if removable_index is None:
                removable_index = next(
                    (index for index in range(1, len(kept) - 1) if index not in protected_indexes),
                    None,
                )
            if removable_index is None:
                break
            kept.pop(removable_index)
            protected_indexes = {
                index - 1 if index > removable_index else index
                for index in protected_indexes
            }
        return kept

    @staticmethod
    def _provider_character_count(messages: list[LLMMessage]) -> int:
        system_count = sum(message.role is ChatRole.SYSTEM for message in messages)
        system_separators = max(0, system_count - 1) * len("\n\n")
        return sum(len(message.content) for message in messages) + system_separators
