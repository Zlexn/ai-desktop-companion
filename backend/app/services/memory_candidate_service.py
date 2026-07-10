from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.domain.models import ChatRole, Memory, MemoryType
from app.providers.base import LLMMessage, LLMOptions, LLMProvider
from app.repositories.memories import MemoryRepository


MEMORY_EXTRACTION_SCHEMA = "memory_extraction_schema_v1"
MAX_LLM_CANDIDATE_CONTENT_CHARS = 200


@dataclass(frozen=True)
class MemoryCandidateDraft:
    content: str
    memory_type: MemoryType
    candidate_reason: str
    importance: int = 3
    confidence: float = 0.7
    extraction_provider: str = "heuristic"
    extraction_schema: str | None = None
    source_quote: str | None = None


class MemoryCandidateLLMExtractor:
    def __init__(self, provider: LLMProvider, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings

    async def extract(self, user_text: str) -> list[MemoryCandidateDraft]:
        clean_text = user_text.strip()
        if not clean_text:
            return []
        try:
            response = await self._provider.generate(
                self._build_messages(clean_text),
                LLMOptions(
                    model=self._settings.llm_model,
                    timeout_seconds=self._settings.memory_candidate_llm_timeout_seconds,
                    max_retries=self._settings.llm_max_retries,
                    max_tokens=self._settings.memory_candidate_llm_max_tokens,
                ),
            )
        except Exception:
            return []
        return self._parse_response(response.text, clean_text)

    def _build_messages(self, user_text: str) -> list[LLMMessage]:
        system_prompt = (
            "你是长期记忆候选抽取器。只根据当前用户消息抽取候选，不读取或假设旧聊天历史。"
            "只提取对未来对话稳定有用的用户事实、偏好、长期目标、重要事件或关系事件。"
            "不要提取临时情绪、寒暄、对助手的描述、阶段4情感状态、关系分数、API Key、令牌、密码或任何凭据。"
            "候选只是等待用户确认的建议，不是已经记住的事实。"
            "如果没有明确且耐久的信息，返回 {\"candidates\": []}。"
            "必须返回严格 JSON，不要返回 Markdown。"
            "JSON 结构：{\"candidates\":[{\"content\":\"用户喜欢红茶。\","
            "\"memory_type\":\"preference\",\"confidence\":0.9,\"importance\":3,"
            "\"source_quote\":\"我喜欢红茶\",\"reason\":\"explicit_preference_statement\","
            "\"should_create_candidate\":true}]}。"
            "memory_type 只能是 user_fact, preference, long_term_goal, important_event, relationship_event, other。"
        )
        return [
            LLMMessage(role=ChatRole.SYSTEM, content=system_prompt),
            LLMMessage(role=ChatRole.USER, content=user_text),
        ]

    def _parse_response(self, text: str, user_text: str) -> list[MemoryCandidateDraft]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, dict):
            return []
        raw_candidates = payload.get("candidates")
        if not isinstance(raw_candidates, list):
            return []

        drafts: list[MemoryCandidateDraft] = []
        for raw in raw_candidates:
            if len(drafts) >= self._settings.memory_candidate_llm_max_candidates:
                break
            draft = self._parse_candidate(raw, user_text)
            if draft is not None:
                drafts.append(draft)
        return drafts

    def _parse_candidate(self, raw: object, user_text: str) -> MemoryCandidateDraft | None:
        if not isinstance(raw, dict):
            return None
        if raw.get("should_create_candidate") is not True:
            return None

        content = self._clean_text_field(raw.get("content"))
        if not content or len(content) > MAX_LLM_CANDIDATE_CONTENT_CHARS:
            return None
        if not content.startswith("用户"):
            return None
        if self._looks_like_secret(content):
            return None

        source_quote = self._clean_text_field(raw.get("source_quote"))
        if not source_quote or source_quote not in user_text:
            return None
        if self._looks_like_secret(source_quote):
            return None

        try:
            memory_type = MemoryType(str(raw.get("memory_type")))
        except ValueError:
            return None

        confidence = self._parse_float(raw.get("confidence"))
        if confidence is None or confidence < self._settings.memory_candidate_llm_confidence_threshold:
            return None

        importance = self._parse_int(raw.get("importance"))
        if importance is None or importance < 1 or importance > 5:
            return None

        reason = self._clean_text_field(raw.get("reason")) or "llm_candidate"
        return MemoryCandidateDraft(
            content=content,
            memory_type=memory_type,
            candidate_reason=reason,
            importance=importance,
            confidence=confidence,
            extraction_provider="llm",
            extraction_schema=MEMORY_EXTRACTION_SCHEMA,
            source_quote=source_quote,
        )

    def _clean_text_field(self, value: object) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip()

    def _parse_float(self, value: object) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            return float(value)
        return None

    def _parse_int(self, value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        return None

    def _looks_like_secret(self, text: str) -> bool:
        lowered = text.lower()
        blocked_terms = (
            "api key",
            "apikey",
            "token",
            "password",
            "secret",
            "密钥",
            "令牌",
            "密码",
            "凭据",
        )
        return any(term in lowered for term in blocked_terms) or bool(re.search(r"sk-[A-Za-z0-9_-]{6,}", text))


class MemoryCandidateService:
    def __init__(self, memories: MemoryRepository, settings: Settings, llm_provider: LLMProvider | None = None) -> None:
        self._memories = memories
        self._settings = settings
        self._llm_extractor = MemoryCandidateLLMExtractor(llm_provider, settings) if llm_provider is not None else None

    async def create_candidates_from_user_text(self, *, session_id: str | None, user_text: str) -> list[Memory]:
        if not self._settings.memory_candidates_enabled:
            return []

        drafts: list[MemoryCandidateDraft]
        if self._settings.memory_candidate_provider == "heuristic":
            drafts = self._extract_heuristic_drafts(user_text)
        elif self._settings.memory_candidate_provider == "llm" and self._llm_extractor is not None:
            drafts = await self._llm_extractor.extract(user_text)
        else:
            return []

        created: list[Memory] = []
        for draft in drafts:
            metadata: dict[str, Any] = {
                "candidate_reason": draft.candidate_reason,
                "extraction_provider": draft.extraction_provider,
            }
            if draft.extraction_schema is not None:
                metadata["extraction_schema"] = draft.extraction_schema
            if draft.source_quote is not None:
                metadata["source_quote"] = draft.source_quote
            if draft.extraction_provider == "llm":
                metadata["raw_confidence"] = draft.confidence

            memory, _conflicts = self._memories.create_candidate(
                content=draft.content,
                memory_type=draft.memory_type,
                source_session_id=session_id,
                importance=draft.importance,
                confidence=draft.confidence,
                metadata=metadata,
            )
            if memory is not None:
                created.append(memory)
        return created

    def _extract_heuristic_drafts(self, user_text: str) -> list[MemoryCandidateDraft]:
        normalized = user_text.strip().replace("，", "。").replace("!", "。").replace("！", "。")
        if not normalized:
            return []

        patterns: list[tuple[re.Pattern[str], MemoryType, str, str]] = [
            (re.compile(r"(?:^|。)我喜欢([^。]{1,40})"), MemoryType.PREFERENCE, "用户喜欢{value}。", "explicit_like_statement"),
            (re.compile(r"(?:^|。)我不喜欢([^。]{1,40})"), MemoryType.PREFERENCE, "用户不喜欢{value}。", "explicit_dislike_statement"),
            (re.compile(r"(?:^|。)我的目标是([^。]{2,80})"), MemoryType.LONG_TERM_GOAL, "用户的目标是{value}。", "explicit_goal_statement"),
            (re.compile(r"(?:^|。)我正在准备([^。]{2,80})"), MemoryType.LONG_TERM_GOAL, "用户正在准备{value}。", "explicit_goal_preparation_statement"),
            (re.compile(r"(?:^|。)我住在([^。]{2,40})"), MemoryType.USER_FACT, "用户住在{value}。", "explicit_residence_statement"),
            (re.compile(r"(?:^|。)我的职业是([^。]{2,40})"), MemoryType.USER_FACT, "用户的职业是{value}。", "explicit_occupation_statement"),
        ]

        drafts: list[MemoryCandidateDraft] = []
        seen: set[tuple[MemoryType, str]] = set()
        for pattern, memory_type, template, reason in patterns:
            for match in pattern.finditer(normalized):
                value = self._clean_value(match.group(1))
                if not value:
                    continue
                content = template.format(value=value)
                key = (memory_type, content)
                if key in seen:
                    continue
                seen.add(key)
                drafts.append(MemoryCandidateDraft(content=content, memory_type=memory_type, candidate_reason=reason))
        return drafts

    def _clean_value(self, value: str) -> str:
        cleaned = value.strip(" 。.，,；;：:、\"'“”‘’")
        if len(cleaned) < 2:
            return ""
        blocked_fragments = {"现在", "刚才", "今天", "有点开心", "有点难过", "生气", "开心"}
        if cleaned in blocked_fragments:
            return ""
        return cleaned
