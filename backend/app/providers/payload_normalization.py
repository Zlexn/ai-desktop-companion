from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ContextBudgetInvariantError
from app.domain.models import ChatRole
from app.providers.base import LLMMessage, LLMOptions


@dataclass(frozen=True)
class AnthropicPayloadView:
    system: str
    conversation: tuple[dict[str, str], ...]
    character_count: int


@dataclass(frozen=True)
class RoleMessagePayloadView:
    messages: tuple[dict[str, str], ...]
    character_count: int


def normalize_provider_payload(
    provider_name: str,
    messages: list[LLMMessage] | tuple[LLMMessage, ...],
) -> AnthropicPayloadView | RoleMessagePayloadView:
    allowed = {ChatRole.SYSTEM, ChatRole.USER, ChatRole.ASSISTANT}
    if provider_name == "anthropic":
        system = "\n\n".join(
            message.content for message in messages if message.role is ChatRole.SYSTEM
        )
        conversation = tuple(
            {"role": message.role.value, "content": message.content}
            for message in messages
            if message.role in {ChatRole.USER, ChatRole.ASSISTANT}
        )
        return AnthropicPayloadView(
            system=system,
            conversation=conversation,
            character_count=len(system)
            + sum(len(message["content"]) for message in conversation),
        )

    forwarded = tuple(
        {"role": message.role.value, "content": message.content}
        for message in messages
        if message.role in allowed
    )
    character_count = sum(len(message["content"]) for message in forwarded)
    if provider_name not in {"deepseek", "fake"}:
        system_count = sum(
            1 for message in messages if message.role is ChatRole.SYSTEM
        )
        character_count += max(0, system_count - 1) * len("\n\n")
    return RoleMessagePayloadView(
        messages=forwarded,
        character_count=character_count,
    )


def validate_chat_dispatch_budget(
    character_count: int,
    options: LLMOptions,
) -> None:
    budget = options.chat_dispatch_budget
    if budget is None:
        return
    if (
        character_count != budget.expected_normalized_characters
        or character_count > budget.max_normalized_characters
    ):
        raise ContextBudgetInvariantError()


def provider_character_count(
    provider_name: str,
    messages: list[LLMMessage] | tuple[LLMMessage, ...],
) -> int:
    return normalize_provider_payload(provider_name, messages).character_count
