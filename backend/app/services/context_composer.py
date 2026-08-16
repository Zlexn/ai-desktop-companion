from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import ValidationAppError
from app.domain.models import ChatRole, Message, MemoryType
from app.domain.persona import PersonaArtifact, PersonaPayloadState
from app.domain.session_summary import SummarySourceFragment
from app.providers.base import LLMMessage
from app.providers.payload_normalization import provider_character_count
from app.repositories.memories import StructuredMemoryContextSource
from app.services.context_data_encoder import ContextDataEncoder, EmotionExpressionView
from app.services.persona_contract import (
    CONTEXT_COMPOSER_VERSION,
    CONTEXT_DATA_ENCODER_VERSION,
)


class ContextProtectedOverflowError(ValidationAppError):
    code = "protected_context_overflow"
    message = "角色设定与当前消息超过上下文限制。"


@dataclass(frozen=True)
class ContextTrimDecision:
    layer: str
    count: int
    reason_code: str


@dataclass(frozen=True)
class ContextCompositionRequest:
    provider_name: str
    session_id: str
    current_user_message_id: str
    current_user_text: str
    persona: PersonaArtifact
    recent_messages: tuple[Message, ...]
    memories: tuple[StructuredMemoryContextSource, ...]
    emotion: EmotionExpressionView | None
    relationship: dict[str, object] | None = None
    summaries: tuple[SummarySourceFragment, ...] = ()


@dataclass(frozen=True)
class ContextCompositionResult:
    provider_messages: tuple[LLMMessage, ...]
    persona_artifact_id: str
    composer_version: str
    encoder_version: str
    selected_recent_message_ids: tuple[str, ...]
    selected_memory_version_ids: tuple[str, ...]
    source_emotion_version: int | None
    relationship_projection_id: str | None
    relationship_projection_version: int | None
    selected_summary_ids: tuple[str, ...]
    provider_character_count: int
    max_characters: int
    trim_decisions: tuple[ContextTrimDecision, ...]


class ContextComposer:
    def __init__(self, settings: Settings, encoder: ContextDataEncoder) -> None:
        self._settings = settings
        self._encoder = encoder

    def compose(
        self,
        request: ContextCompositionRequest,
        *,
        max_characters: int | None = None,
    ) -> ContextCompositionResult:
        maximum = max_characters or self._settings.chat_context_max_characters
        self._validate_request(request)
        selected_summaries, initial_summary_drops = self._select_summary_limits(
            request.summaries
        )
        selected_memories, initial_memory_drops = self._select_memory_limits(
            tuple(sorted(request.memories, key=self._memory_sort_key))
        )
        selected_recent = list(
            sorted(
                request.recent_messages,
                key=lambda message: message.created_at,
            )
        )
        selected_emotion = request.emotion
        emotion_neutralized = False
        trims: list[ContextTrimDecision] = [
            *initial_summary_drops,
            *initial_memory_drops,
        ]
        (
            selected_summaries,
            selected_memories,
            selected_emotion,
            dynamic_trims,
        ) = self._fit_dynamic_limits(
            selected_summaries,
            selected_memories,
            selected_emotion,
        )
        trims.extend(dynamic_trims)

        messages = self._build_messages(
            request,
            selected_recent,
            selected_memories,
            selected_emotion,
            selected_summaries,
        )
        while provider_character_count(request.provider_name, messages) > maximum:
            if selected_summaries:
                selected_summaries.pop()
                trims.append(
                    ContextTrimDecision(
                        "summary",
                        1,
                        "summary_global_budget",
                    )
                )
            else:
                automatic_indexes = [
                    index
                    for index, memory in enumerate(selected_memories)
                    if memory.source_kind.value == "automatic"
                ]
                if automatic_indexes:
                    selected_memories.pop(automatic_indexes[-1])
                    trims.append(
                        ContextTrimDecision(
                            "memory",
                            1,
                            "automatic_memory_low_rank",
                        )
                    )
                elif (
                    drop_index := self._user_memory_drop_index(selected_memories)
                ) is not None:
                    selected_memories.pop(drop_index)
                    trims.append(
                        ContextTrimDecision(
                            "memory",
                            1,
                            "user_memory_low_rank",
                        )
                    )
                elif selected_recent:
                    removed = self._drop_oldest_turn(selected_recent)
                    trims.append(
                        ContextTrimDecision("recent", removed, "oldest_history")
                    )
                elif selected_emotion is not None and not emotion_neutralized:
                    selected_emotion = self._neutral_emotion(selected_emotion)
                    emotion_neutralized = True
                    trims.append(
                        ContextTrimDecision("emotion", 1, "neutral_expression")
                    )
                else:
                    break
            messages = self._build_messages(
                request,
                selected_recent,
                selected_memories,
                selected_emotion,
                selected_summaries,
            )

        if provider_character_count(request.provider_name, messages) > maximum:
            trims.append(
                ContextTrimDecision("optional", 1, "residual_optional_overflow")
            )
            selected_summaries = []
            selected_emotion = None
            selected_memories = []
            selected_recent = []
            messages = self._build_messages(request, [], [], None, [])

        count = provider_character_count(request.provider_name, messages)
        if count > maximum:
            protected = (
                LLMMessage(ChatRole.SYSTEM, request.persona.rendered_system_prompt or ""),
                LLMMessage(ChatRole.USER, request.current_user_text),
            )
            if provider_character_count(request.provider_name, protected) > maximum:
                raise ContextProtectedOverflowError()
            raise RuntimeError("optional context remained after residual overflow")

        return ContextCompositionResult(
            provider_messages=tuple(messages),
            persona_artifact_id=request.persona.id,
            composer_version=CONTEXT_COMPOSER_VERSION,
            encoder_version=CONTEXT_DATA_ENCODER_VERSION,
            selected_recent_message_ids=tuple(message.id for message in selected_recent),
            selected_memory_version_ids=tuple(
                memory.current_version_id
                for memory in selected_memories
                if memory.current_version_id is not None
            ),
            source_emotion_version=(
                selected_emotion.version if selected_emotion is not None else None
            ),
            relationship_projection_id=(
                str(request.relationship["projection_id"])
                if request.relationship is not None
                else None
            ),
            relationship_projection_version=(
                int(request.relationship["projection_version"])
                if request.relationship is not None
                else None
            ),
            selected_summary_ids=tuple(
                summary.summary_id for summary in selected_summaries
            ),
            provider_character_count=count,
            max_characters=maximum,
            trim_decisions=tuple(trims),
        )

    def _validate_request(self, request: ContextCompositionRequest) -> None:
        if request.relationship is not None:
            # C3 allows at most one verified relationship projection object.
            if not isinstance(request.relationship, dict):
                raise ValueError("relationship must be a projection object or null")
            for key in (
                "authority",
                "projection_id",
                "projection_version",
                "familiarity_bucket",
                "preferred_address",
                "relationship_summary_code",
                "persona_artifact_id",
                "projection_rule_version",
            ):
                if key not in request.relationship:
                    raise ValueError("relationship projection is missing a field")
        if request.persona.payload_state is PersonaPayloadState.REDACTED:
            raise ValueError("Persona must be usable")
        if not request.persona.rendered_system_prompt:
            raise ValueError("Persona prompt is missing")
        if not request.current_user_text.strip():
            raise ValueError("current user text must not be empty")
        if len(request.current_user_text) > self._settings.chat_current_user_max_characters:
            raise ContextProtectedOverflowError()
        if len(request.persona.rendered_system_prompt) > self._settings.persona_max_characters:
            raise ContextProtectedOverflowError()
        recent_ids = [message.id for message in request.recent_messages]
        if request.current_user_message_id in recent_ids:
            raise ValueError("recent messages contain current user message")
        if len(set(recent_ids)) != len(recent_ids):
            raise ValueError("duplicate recent message id")
        memory_ids = [memory.memory_id for memory in request.memories]
        if len(set(memory_ids)) != len(memory_ids):
            raise ValueError("duplicate memory identity")
        version_ids = [
            memory.current_version_id
            for memory in request.memories
            if memory.current_version_id is not None
        ]
        if len(set(version_ids)) != len(version_ids):
            raise ValueError("duplicate memory version")
        summary_ids = [summary.summary_id for summary in request.summaries]
        if len(set(summary_ids)) != len(summary_ids):
            raise ValueError("duplicate summary id")

    def _select_summary_limits(
        self,
        summaries: tuple[SummarySourceFragment, ...],
    ) -> tuple[list[SummarySourceFragment], list[ContextTrimDecision]]:
        selected = [
            summary
            for summary in summaries
            if len(summary.summary_text)
            <= self._settings.summary_injection_max_fragment_characters
        ]
        if len(selected) > self._settings.summary_injection_max_fragments:
            selected = selected[: self._settings.summary_injection_max_fragments]
        total_characters = sum(len(summary.summary_text) for summary in selected)
        while (
            selected
            and total_characters
            > self._settings.summary_injection_max_total_characters
        ):
            total_characters -= len(selected.pop().summary_text)
        dropped = len(summaries) - len(selected)
        decisions = (
            [ContextTrimDecision("summary", dropped, "summary_limit")]
            if dropped
            else []
        )
        return selected, decisions

    def _select_memory_limits(
        self,
        memories: tuple[StructuredMemoryContextSource, ...],
    ) -> tuple[list[StructuredMemoryContextSource], list[ContextTrimDecision]]:
        budgets = self._settings.context_memory_type_budgets()
        selected: list[StructuredMemoryContextSource] = []
        item_counts: Counter[MemoryType] = Counter()
        character_counts: Counter[MemoryType] = Counter()
        dropped = 0
        for memory in memories:
            budget = budgets[memory.memory_type]
            if len(selected) >= self._settings.memory_context_limit:
                dropped += 1
                continue
            if item_counts[memory.memory_type] >= budget.max_items:
                dropped += 1
                continue
            if (
                character_counts[memory.memory_type] + len(memory.content)
                > budget.max_characters
            ):
                dropped += 1
                continue
            selected.append(memory)
            item_counts[memory.memory_type] += 1
            character_counts[memory.memory_type] += len(memory.content)
        decisions = (
            [ContextTrimDecision("memory", dropped, "memory_type_limit")]
            if dropped
            else []
        )
        return selected, decisions

    def _fit_dynamic_limits(
        self,
        summaries: list[SummarySourceFragment],
        memories: list[StructuredMemoryContextSource],
        emotion: EmotionExpressionView | None,
    ) -> tuple[
        list[SummarySourceFragment],
        list[StructuredMemoryContextSource],
        EmotionExpressionView | None,
        list[ContextTrimDecision],
    ]:
        selected_summaries = list(summaries)
        selected_memories = list(memories)
        selected_emotion = emotion
        decisions: list[ContextTrimDecision] = []
        while selected_summaries or selected_memories or selected_emotion is not None:
            encoded = self._encoder.encode(
                memories=selected_memories,
                emotion=selected_emotion,
                summaries=selected_summaries,
            )
            if len(encoded) <= self._settings.chat_dynamic_context_max_characters:
                break
            if selected_summaries:
                selected_summaries.pop()
                decisions.append(
                    ContextTrimDecision("summary", 1, "summary_dynamic_budget")
                )
            elif (
                automatic_index := self._lowest_automatic_index(selected_memories)
            ) is not None:
                selected_memories.pop(automatic_index)
                decisions.append(
                    ContextTrimDecision("memory", 1, "dynamic_context_limit")
                )
            elif selected_memories:
                selected_memories.pop()
                decisions.append(
                    ContextTrimDecision("memory", 1, "dynamic_context_limit")
                )
            else:
                selected_emotion = None
                decisions.append(
                    ContextTrimDecision("emotion", 1, "dynamic_context_limit")
                )
        return (
            selected_summaries,
            selected_memories,
            selected_emotion,
            decisions,
        )

    @staticmethod
    def _memory_sort_key(item: StructuredMemoryContextSource):
        return (
            -item.relevance_score,
            0
            if item.source_kind.value
            in {"manual", "candidate", "user_edit", "user_revert"}
            else 1,
            -item.importance,
            -item.confidence,
            -item.updated_at.timestamp(),
            item.memory_id,
            item.current_version_id or "",
        )

    @staticmethod
    def _lowest_automatic_index(
        memories: list[StructuredMemoryContextSource],
    ) -> int | None:
        indexes = [
            index
            for index, memory in enumerate(memories)
            if memory.source_kind.value == "automatic"
        ]
        return indexes[-1] if indexes else None

    def _user_memory_drop_index(
        self,
        memories: list[StructuredMemoryContextSource],
    ) -> int | None:
        counts = Counter(memory.memory_type for memory in memories)
        for index in range(len(memories) - 1, -1, -1):
            memory = memories[index]
            if memory.source_kind.value == "automatic":
                continue
            budget = self._settings.context_memory_type_budgets()[memory.memory_type]
            if counts[memory.memory_type] > budget.soft_min_items:
                return index
        return None

    @staticmethod
    def _drop_oldest_turn(messages: list[Message]) -> int:
        if not messages:
            return 0
        removed = 1
        first = messages.pop(0)
        if first.role is ChatRole.USER and messages and messages[0].role is ChatRole.ASSISTANT:
            messages.pop(0)
            removed += 1
        return removed

    @staticmethod
    def _neutral_emotion(emotion: EmotionExpressionView) -> EmotionExpressionView:
        return EmotionExpressionView(
            version=emotion.version,
            mood="steady",
            trust=0.4,
            concern=0.2,
            distance=0.55,
            irritation=0.1,
            formality=0.6,
        )

    def _build_messages(
        self,
        request: ContextCompositionRequest,
        recent: list[Message],
        memories: list[StructuredMemoryContextSource],
        emotion: EmotionExpressionView | None,
        summaries: list[SummarySourceFragment],
    ) -> list[LLMMessage]:
        messages = [
            LLMMessage(ChatRole.SYSTEM, request.persona.rendered_system_prompt or "")
        ]
        if summaries or memories or emotion is not None or request.relationship is not None:
            dynamic = self._encoder.encode(
                memories=memories,
                emotion=emotion,
                summaries=summaries,
                relationships=(
                    [request.relationship] if request.relationship is not None else []
                ),
            )
            if len(dynamic) > self._settings.chat_dynamic_context_max_characters:
                raise RuntimeError("dynamic context was not pre-fitted")
            messages.append(LLMMessage(ChatRole.SYSTEM, dynamic))
        messages.extend(
            LLMMessage(message.role, message.content)
            for message in recent
            if message.role in {ChatRole.USER, ChatRole.ASSISTANT}
        )
        messages.append(LLMMessage(ChatRole.USER, request.current_user_text))
        return messages
