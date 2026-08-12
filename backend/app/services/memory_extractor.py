from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
import time
from typing import Protocol

from app.core.config import Settings
from app.domain.models import ChatRole, MemoryGovernorProposal, MemoryType, Message
from app.providers.base import LLMMessage, LLMOptions, LLMProvider, LLMResponse
from app.services.memory_extraction_contract import (
    MEMORY_EXTRACTION_DISCLOSURE_VERSION,
)


MEMORY_EXTRACTION_SCHEMA_VERSION = "memory-shadow-schema-v1"
MEMORY_LOCAL_RULES_VERSION = "memory-local-rules-v1"

_TOP_LEVEL_KEYS = {"schema_version", "proposals"}
_PROPOSAL_KEYS = {
    "memory_type",
    "subject",
    "content",
    "canonical_key_hint",
    "confidence",
    "source_message_ids",
}
_DISCLOSURE_KEYS = {
    "disclosure_version",
    "schema_version",
    "user_message",
    "assistant_message",
}
_DISCLOSED_MESSAGE_KEYS = {"id", "content"}

_SYSTEM_INSTRUCTION = """You extract untrusted suggestions for durable user memory.
Use only the disclosed current-turn user_message and assistant_message fields. Do not
infer from prior history, hidden context, or hidden reasoning. The user message must be
the source of every proposal; assistant text can only support it. Return strict JSON
only, with exactly schema_version and proposals. Each proposal must have exactly
memory_type, subject, content, canonical_key_hint, confidence, and source_message_ids.
Do not include markdown, commentary, or hidden reasoning. Suggestions are untrusted
and will be checked by a local Governor."""

_LOCAL_PATTERNS: tuple[
    tuple[re.Pattern[str], MemoryType, str, str, float], ...
] = (
    (
        re.compile(r"^我叫\s*(?P<value>[^。！？!?；;\n]+?)\s*[。！？!?]?$"),
        MemoryType.USER_FACT,
        "姓名",
        "用户叫{value}",
        0.95,
    ),
    (
        re.compile(r"^我喜欢\s*(?P<value>[^。！？!?；;\n]+?)\s*[。！？!?]?$"),
        MemoryType.PREFERENCE,
        "偏好",
        "用户喜欢{value}",
        0.90,
    ),
    (
        re.compile(r"^我不喜欢\s*(?P<value>[^。！？!?；;\n]+?)\s*[。！？!?]?$"),
        MemoryType.PREFERENCE,
        "不喜欢的事物",
        "用户不喜欢{value}",
        0.90,
    ),
    (
        re.compile(r"^我的目标是\s*(?P<value>[^。！？!?；;\n]+?)\s*[。！？!?]?$"),
        MemoryType.LONG_TERM_GOAL,
        "长期目标",
        "用户的目标是{value}",
        0.90,
    ),
    (
        re.compile(r"^我计划\s*(?P<value>[^。！？!?；;\n]+?)\s*[。！？!?]?$"),
        MemoryType.LONG_TERM_GOAL,
        "计划",
        "用户计划{value}",
        0.85,
    ),
)


class MemoryExtractionInvalidOutputError(ValueError):
    pass


@dataclass(frozen=True)
class MemoryExtractionResult:
    proposals: list[MemoryGovernorProposal]
    provider: str
    model: str
    elapsed_ms: int


class MemoryExtractor(Protocol):
    async def extract(
        self,
        *,
        user_message: Message,
        assistant_message: Message,
    ) -> MemoryExtractionResult: ...


def _validate_settings(settings: Settings) -> None:
    if not isinstance(settings.memory_extractor_model, str) or not settings.memory_extractor_model.strip():
        raise ValueError("memory extractor model must be a non-empty string")
    for name, value in (
        ("memory_extractor_max_tokens", settings.memory_extractor_max_tokens),
        ("memory_extractor_max_proposals", settings.memory_extractor_max_proposals),
        (
            "memory_extractor_max_proposal_characters",
            settings.memory_extractor_max_proposal_characters,
        ),
        (
            "memory_extractor_max_total_characters",
            settings.memory_extractor_max_total_characters,
        ),
    ):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if (
        settings.memory_extractor_max_total_characters
        < settings.memory_extractor_max_proposal_characters
    ):
        raise ValueError(
            "memory_extractor_max_total_characters must be at least the per-proposal limit"
        )
    timeout = settings.memory_extractor_timeout_seconds
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(float(timeout))
        or float(timeout) <= 0
    ):
        raise ValueError("memory_extractor_timeout_seconds must be positive and finite")
    if type(settings.memory_extractor_max_retries) is not int or settings.memory_extractor_max_retries < 0:
        raise ValueError("memory_extractor_max_retries must be a non-negative integer")


def _validate_turn(user_message: Message, assistant_message: Message) -> None:
    if not isinstance(user_message, Message) or not isinstance(assistant_message, Message):
        raise TypeError("extractor inputs must be Message values")
    for current in (user_message, assistant_message):
        if not isinstance(current.id, str) or not current.id.strip():
            raise ValueError("message IDs must be non-empty strings")
        if not isinstance(current.session_id, str) or not current.session_id.strip():
            raise ValueError("message session IDs must be non-empty strings")
        if not isinstance(current.content, str):
            raise TypeError("message content must be a string")
    if user_message.role is not ChatRole.USER:
        raise ValueError("user_message must have the user role")
    if assistant_message.role is not ChatRole.ASSISTANT:
        raise ValueError("assistant_message must have the assistant role")
    if user_message.session_id != assistant_message.session_id:
        raise ValueError("current-turn messages must belong to the same session")
    if user_message.id == assistant_message.id:
        raise ValueError("current-turn message IDs must be distinct")


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _extract_local_proposals(
    *,
    user_message_id: str,
    user_text: str,
    max_proposals: int,
    max_proposal_characters: int,
    max_total_characters: int,
) -> list[MemoryGovernorProposal]:
    proposals: list[MemoryGovernorProposal] = []
    total_characters = 0
    clauses = re.split(r"[\r\n]+|(?<=[。！？!?；;])", user_text)
    for raw_clause in clauses:
        clause = raw_clause.strip()
        if not clause:
            continue
        for pattern, memory_type, subject, template, confidence in _LOCAL_PATTERNS:
            match = pattern.fullmatch(clause)
            if match is None:
                continue
            value = match.group("value").strip()
            if not value:
                break
            content = template.format(value=value)
            if len(content) > max_proposal_characters:
                break
            proposal = MemoryGovernorProposal(
                memory_type=memory_type,
                subject=subject,
                content=content,
                canonical_key_hint=None,
                confidence=confidence,
                source_message_ids=(user_message_id,),
            )
            if total_characters + len(content) > max_total_characters:
                break
            proposals.append(proposal)
            total_characters += len(content)
            break
        if len(proposals) >= max_proposals:
            break
    return proposals


def _strict_json_loads(text: str) -> object:
    if not isinstance(text, str):
        raise MemoryExtractionInvalidOutputError("invalid memory extraction output")

    def reject_constant(_: str) -> object:
        raise ValueError

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        parsed: dict[str, object] = {}
        for key, value in pairs:
            if key in parsed:
                raise ValueError
            parsed[key] = value
        return parsed

    try:
        parsed = json.loads(
            text,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (TypeError, ValueError, json.JSONDecodeError, RecursionError):
        parsed = None
    if parsed is None:
        raise MemoryExtractionInvalidOutputError("invalid memory extraction output")
    return parsed


def _proposal_document(proposal: MemoryGovernorProposal) -> dict[str, object]:
    return {
        "memory_type": proposal.memory_type.value,
        "subject": proposal.subject,
        "content": proposal.content,
        "canonical_key_hint": proposal.canonical_key_hint,
        "confidence": proposal.confidence,
        "source_message_ids": list(proposal.source_message_ids),
    }


class ProviderMemoryExtractor:
    def __init__(self, provider: LLMProvider, settings: Settings) -> None:
        _validate_settings(settings)
        self._provider = provider
        self._settings = settings
        self._options = LLMOptions(
            model=settings.memory_extractor_model,
            timeout_seconds=float(settings.memory_extractor_timeout_seconds),
            max_retries=settings.memory_extractor_max_retries,
            max_tokens=settings.memory_extractor_max_tokens,
        )

    async def extract(
        self,
        *,
        user_message: Message,
        assistant_message: Message,
    ) -> MemoryExtractionResult:
        _validate_turn(user_message, assistant_message)
        disclosed_payload = {
            "disclosure_version": MEMORY_EXTRACTION_DISCLOSURE_VERSION,
            "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
            "user_message": {
                "id": user_message.id,
                "content": user_message.content,
            },
            "assistant_message": {
                "id": assistant_message.id,
                "content": assistant_message.content,
            },
        }
        messages = [
            LLMMessage(role=ChatRole.SYSTEM, content=_SYSTEM_INSTRUCTION),
            LLMMessage(
                role=ChatRole.USER,
                content=json.dumps(disclosed_payload, ensure_ascii=False),
            ),
        ]
        started_at = time.perf_counter()
        response = await self._provider.generate(messages, self._options)
        elapsed_ms = _elapsed_ms(started_at)
        proposals = self._parse_response(
            response.text,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
        )
        provider = response.provider if isinstance(response.provider, str) else ""
        model = response.model if isinstance(response.model, str) else ""
        return MemoryExtractionResult(
            proposals=proposals,
            provider=provider,
            model=model,
            elapsed_ms=elapsed_ms,
        )

    def _parse_response(
        self,
        text: str,
        *,
        user_message_id: str,
        assistant_message_id: str,
    ) -> list[MemoryGovernorProposal]:
        document = _strict_json_loads(text)
        if type(document) is not dict or set(document) != _TOP_LEVEL_KEYS:
            self._invalid_output()
        if document["schema_version"] != MEMORY_EXTRACTION_SCHEMA_VERSION:
            self._invalid_output()
        raw_proposals = document["proposals"]
        if type(raw_proposals) is not list:
            self._invalid_output()
        if len(raw_proposals) > self._settings.memory_extractor_max_proposals:
            self._invalid_output()

        proposals = [
            self._parse_proposal(
                raw_proposal,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
            )
            for raw_proposal in raw_proposals
        ]
        if (
            sum(len(proposal.content) for proposal in proposals)
            > self._settings.memory_extractor_max_total_characters
        ):
            self._invalid_output()
        return proposals

    def _parse_proposal(
        self,
        raw_proposal: object,
        *,
        user_message_id: str,
        assistant_message_id: str,
    ) -> MemoryGovernorProposal:
        if type(raw_proposal) is not dict or set(raw_proposal) != _PROPOSAL_KEYS:
            self._invalid_output()

        raw_memory_type = raw_proposal["memory_type"]
        if type(raw_memory_type) is not str:
            self._invalid_output()
        try:
            memory_type = MemoryType(raw_memory_type)
        except ValueError:
            self._invalid_output()

        subject = raw_proposal["subject"]
        content = raw_proposal["content"]
        hint = raw_proposal["canonical_key_hint"]
        confidence = raw_proposal["confidence"]
        source_ids = raw_proposal["source_message_ids"]
        if type(subject) is not str or not subject.strip() or len(subject) > 120:
            self._invalid_output()
        if (
            type(content) is not str
            or not content.strip()
            or len(content) > self._settings.memory_extractor_max_proposal_characters
        ):
            self._invalid_output()
        if hint is not None and (type(hint) is not str or len(hint) > 120):
            self._invalid_output()
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            self._invalid_output()
        try:
            parsed_confidence = float(confidence)
        except (OverflowError, ValueError):
            self._invalid_output()
        if not math.isfinite(parsed_confidence) or not 0.0 <= parsed_confidence <= 1.0:
            self._invalid_output()
        if (
            type(source_ids) is not list
            or not source_ids
            or any(type(source_id) is not str for source_id in source_ids)
            or len(set(source_ids)) != len(source_ids)
        ):
            self._invalid_output()
        allowed_source_ids = {user_message_id, assistant_message_id}
        if user_message_id not in source_ids or not set(source_ids) <= allowed_source_ids:
            self._invalid_output()

        return MemoryGovernorProposal(
            memory_type=memory_type,
            subject=subject,
            content=content,
            canonical_key_hint=hint,
            confidence=parsed_confidence,
            source_message_ids=tuple(source_ids),
        )

    @staticmethod
    def _invalid_output() -> None:
        raise MemoryExtractionInvalidOutputError("invalid memory extraction output")


class LocalMemoryExtractor:
    def __init__(self, settings: Settings) -> None:
        _validate_settings(settings)
        self._settings = settings

    async def extract(
        self,
        *,
        user_message: Message,
        assistant_message: Message,
    ) -> MemoryExtractionResult:
        _validate_turn(user_message, assistant_message)
        started_at = time.perf_counter()
        proposals = _extract_local_proposals(
            user_message_id=user_message.id,
            user_text=user_message.content,
            max_proposals=self._settings.memory_extractor_max_proposals,
            max_proposal_characters=self._settings.memory_extractor_max_proposal_characters,
            max_total_characters=self._settings.memory_extractor_max_total_characters,
        )
        return MemoryExtractionResult(
            proposals=proposals,
            provider="local",
            model=MEMORY_LOCAL_RULES_VERSION,
            elapsed_ms=_elapsed_ms(started_at),
        )


class MemoryExtractionFakeProvider:
    def __init__(self, settings: Settings) -> None:
        _validate_settings(settings)
        self._settings = settings

    async def generate(
        self,
        messages: list[LLMMessage],
        options: LLMOptions,
    ) -> LLMResponse:
        proposals: list[MemoryGovernorProposal] = []
        if self._has_exact_message_envelope(messages):
            disclosed = _strict_json_loads(messages[1].content)
            if self._has_exact_disclosure(disclosed):
                user_payload = disclosed["user_message"]
                proposals = _extract_local_proposals(
                    user_message_id=user_payload["id"],
                    user_text=user_payload["content"],
                    max_proposals=self._settings.memory_extractor_max_proposals,
                    max_proposal_characters=self._settings.memory_extractor_max_proposal_characters,
                    max_total_characters=self._settings.memory_extractor_max_total_characters,
                )
        response_document = {
            "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
            "proposals": [_proposal_document(proposal) for proposal in proposals],
        }
        return LLMResponse(
            text=json.dumps(response_document, ensure_ascii=False),
            provider="memory-fake",
            model=options.model,
        )

    @staticmethod
    def _has_exact_message_envelope(messages: object) -> bool:
        return (
            type(messages) is list
            and len(messages) == 2
            and isinstance(messages[0], LLMMessage)
            and isinstance(messages[1], LLMMessage)
            and messages[0].role is ChatRole.SYSTEM
            and messages[1].role is ChatRole.USER
            and isinstance(messages[0].content, str)
            and isinstance(messages[1].content, str)
        )

    @staticmethod
    def _has_exact_disclosure(disclosed: object) -> bool:
        if type(disclosed) is not dict or set(disclosed) != _DISCLOSURE_KEYS:
            return False
        if (
            disclosed["disclosure_version"] != MEMORY_EXTRACTION_DISCLOSURE_VERSION
            or disclosed["schema_version"] != MEMORY_EXTRACTION_SCHEMA_VERSION
        ):
            return False
        for key in ("user_message", "assistant_message"):
            item = disclosed[key]
            if type(item) is not dict or set(item) != _DISCLOSED_MESSAGE_KEYS:
                return False
            if (
                type(item["id"]) is not str
                or not item["id"].strip()
                or type(item["content"]) is not str
            ):
                return False
        return disclosed["user_message"]["id"] != disclosed["assistant_message"]["id"]
