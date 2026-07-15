from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from app.domain.models import ChatRole, Memory, MemoryStatus, Message
from app.services.credential_sanitizer import sanitize_credentials


@dataclass(frozen=True)
class AnalysisMessage:
    id: str
    role: str
    content: str


@dataclass(frozen=True)
class AnalysisMemory:
    id: str
    memory_type: str
    content: str


@dataclass(frozen=True)
class AnalysisCurrentTurn:
    user_message_id: str
    user_content: str
    assistant_message_id: str
    assistant_content: str


@dataclass(frozen=True)
class EmotionAnalysisInput:
    current_turn: AnalysisCurrentTurn
    recent_messages: tuple[AnalysisMessage, ...]
    memories: tuple[AnalysisMemory, ...]
    input_characters: int
    redaction_count: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


class EmotionAnalysisInputBuilder:
    def __init__(
        self,
        *,
        recent_message_limit: int,
        memory_limit: int,
        max_item_characters: int,
        max_total_characters: int,
    ) -> None:
        if max_total_characters < 2:
            raise ValueError("max_total_characters must be at least 2")
        self._recent_message_limit = recent_message_limit
        self._memory_limit = memory_limit
        self._max_item_characters = max_item_characters
        self._max_total_characters = max_total_characters

    def build(
        self,
        *,
        current_user_message: Message,
        current_assistant_message: Message,
        recent_messages: list[Message],
        relevant_memories: list[Memory],
    ) -> EmotionAnalysisInput:
        if (
            current_user_message.role is not ChatRole.USER
            or current_assistant_message.role is not ChatRole.ASSISTANT
            or current_user_message.session_id != current_assistant_message.session_id
        ):
            raise ValueError("current turn must contain matching user and assistant messages")

        user_content, user_redactions = self._sanitize(current_user_message.content)
        assistant_content, assistant_redactions = self._sanitize(current_assistant_message.content)
        user_budget = max(1, self._max_total_characters // 2)
        assistant_budget = max(1, self._max_total_characters - user_budget)
        user_content = user_content[: min(self._max_item_characters, user_budget)]
        assistant_content = assistant_content[: min(self._max_item_characters, assistant_budget)]
        required_characters = len(user_content) + len(assistant_content)

        current_turn = AnalysisCurrentTurn(
            user_message_id=current_user_message.id,
            user_content=user_content,
            assistant_message_id=current_assistant_message.id,
            assistant_content=assistant_content,
        )
        optional_messages: list[tuple[AnalysisMessage, int]] = []
        selected_recent = recent_messages[-self._recent_message_limit :]
        current_ids = {current_user_message.id, current_assistant_message.id}
        for message in selected_recent:
            if message.id in current_ids:
                continue
            content, redactions = self._sanitize(message.content)
            optional_messages.append(
                (
                    AnalysisMessage(id=message.id, role=message.role.value, content=content),
                    redactions,
                )
            )

        optional_memories: list[tuple[AnalysisMemory, int]] = []
        for memory in relevant_memories:
            if memory.status is not MemoryStatus.ACTIVE:
                continue
            content, redactions = self._sanitize(memory.content)
            optional_memories.append(
                (
                    AnalysisMemory(
                        id=memory.id,
                        memory_type=memory.memory_type.value,
                        content=content,
                    ),
                    redactions,
                )
            )
            if len(optional_memories) == self._memory_limit:
                break

        remaining = self._max_total_characters - required_characters
        included_messages: list[AnalysisMessage] = []
        included_memories: list[AnalysisMemory] = []
        redaction_count = user_redactions + assistant_redactions

        for message, redactions in reversed(optional_messages):
            if len(message.content) <= remaining:
                included_messages.append(message)
                redaction_count += redactions
                remaining -= len(message.content)
        included_messages.reverse()

        for memory, redactions in optional_memories:
            if len(memory.content) <= remaining:
                included_memories.append(memory)
                redaction_count += redactions
                remaining -= len(memory.content)

        input_characters = required_characters + sum(
            len(item.content) for item in included_messages
        ) + sum(len(item.content) for item in included_memories)
        return EmotionAnalysisInput(
            current_turn=current_turn,
            recent_messages=tuple(included_messages),
            memories=tuple(included_memories),
            input_characters=input_characters,
            redaction_count=redaction_count,
        )

    def _sanitize(self, content: str) -> tuple[str, int]:
        sanitized, redactions = sanitize_credentials(content)
        return sanitized[: self._max_item_characters], redactions
