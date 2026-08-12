from dataclasses import dataclass, field
from typing import Protocol

from app.domain.models import ChatRole


@dataclass(frozen=True)
class LLMMessage:
    role: ChatRole
    content: str


@dataclass(frozen=True)
class ChatDispatchBudget:
    expected_normalized_characters: int
    max_normalized_characters: int


@dataclass(frozen=True)
class LLMOptions:
    model: str
    timeout_seconds: float
    max_retries: int
    max_tokens: int = 1024
    chat_dispatch_budget: ChatDispatchBudget | None = None


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    metadata: dict[str, object] = field(default_factory=dict)


class LLMProvider(Protocol):
    provider_name: str

    async def generate(self, messages: list[LLMMessage], options: LLMOptions) -> LLMResponse:
        ...
