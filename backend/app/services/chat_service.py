from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import ProviderInvalidResponseError, ValidationAppError
from app.domain.models import ChatRole
from app.providers.base import LLMMessage, LLMOptions, LLMProvider
from app.repositories.messages import MessageRepository
from app.repositories.sessions import SessionRepository
from app.services.context_builder import ContextBuilder
from app.services.memory_candidate_service import MemoryCandidateService
from app.services.prompt_renderer import PromptRenderer


@dataclass(frozen=True)
class ChatReply:
    reply: str
    provider: str
    model: str


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
    ) -> None:
        self._sessions = sessions
        self._messages = messages
        self._context_builder = context_builder
        self._prompt_renderer = prompt_renderer
        self._provider = provider
        self._settings = settings
        self._memory_candidates = memory_candidates

    async def send_message(self, session_id: str, user_text: str) -> ChatReply:
        clean_text = user_text.strip()
        if not clean_text:
            raise ValidationAppError("消息内容不能为空。")

        self._sessions.require(session_id)
        self._messages.add(session_id, ChatRole.USER, clean_text)

        system_prompt = self._prompt_renderer.render()
        context = self._context_builder.build_context(session_id, query=clean_text)
        provider_messages = [LLMMessage(role=ChatRole.SYSTEM, content=system_prompt), *context]
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
        self._messages.add(
            session_id,
            ChatRole.ASSISTANT,
            reply,
            assistant_metadata,
        )
        if self._memory_candidates is not None:
            try:
                await self._memory_candidates.create_candidates_from_user_text(
                    session_id=session_id,
                    user_text=clean_text,
                )
            except Exception:
                # Candidate extraction must never break the chat path.
                pass
        return ChatReply(reply=reply, provider=response.provider, model=response.model)
