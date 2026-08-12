from collections import Counter
from datetime import UTC, datetime
import json
import math

import pytest

from app.core.config import Settings
from app.domain.models import ChatRole, MemoryType, Message
from app.providers.base import LLMMessage, LLMOptions, LLMResponse
from app.services.memory_candidate_service import MAX_LLM_CANDIDATE_CONTENT_CHARS
from app.services.memory_extractor import (
    MEMORY_EXTRACTION_DISCLOSURE_VERSION,
    MEMORY_EXTRACTION_SCHEMA_VERSION,
    MEMORY_LOCAL_RULES_VERSION,
    LocalMemoryExtractor,
    MemoryExtractionFakeProvider,
    MemoryExtractionInvalidOutputError,
    ProviderMemoryExtractor,
)
from app.services.memory_governor import MemoryGovernor


class RecordingProvider:
    def __init__(self, text: object) -> None:
        self.text = text
        self.messages: list[LLMMessage] = []
        self.options: LLMOptions | None = None

    async def generate(
        self,
        messages: list[LLMMessage],
        options: LLMOptions,
    ) -> LLMResponse:
        self.messages = messages
        self.options = options
        return LLMResponse(
            text=self.text,  # type: ignore[arg-type]
            provider="recording-provider",
            model="recording-model",
        )


def settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "memory_extractor_model": "memory-test-model",
        "memory_extractor_max_tokens": 512,
        "memory_extractor_timeout_seconds": 15.0,
        "memory_extractor_max_retries": 0,
        "memory_extractor_max_proposals": 3,
        "memory_extractor_max_proposal_characters": 200,
        "memory_extractor_max_total_characters": 600,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def message(
    message_id: str,
    role: ChatRole,
    content: object,
    *,
    session_id: object = "session-1",
) -> Message:
    return Message(
        id=message_id,
        session_id=session_id,  # type: ignore[arg-type]
        role=role,
        content=content,  # type: ignore[arg-type]
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
        metadata={},
    )


def user_message(content: object = "我喜欢黑咖啡") -> Message:
    return message("user-1", ChatRole.USER, content)


def assistant_message(content: object = "我知道了。") -> Message:
    return message("assistant-1", ChatRole.ASSISTANT, content)


def proposal_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "memory_type": "preference",
        "subject": "饮品偏好",
        "content": "用户喜欢黑咖啡",
        "canonical_key_hint": "drink:coffee",
        "confidence": 0.91,
        "source_message_ids": ["user-1"],
    }
    document.update(overrides)
    return document


def response_document(proposals: object) -> str:
    return json.dumps(
        {
            "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
            "proposals": proposals,
        },
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_provider_extractor_accepts_exact_strict_document_and_minimal_disclosure():
    provider = RecordingProvider(response_document([proposal_document()]))
    extractor = ProviderMemoryExtractor(provider, settings())

    result = await extractor.extract(
        user_message=user_message(),
        assistant_message=assistant_message(),
    )

    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.memory_type is MemoryType.PREFERENCE
    assert proposal.subject == "饮品偏好"
    assert proposal.content == "用户喜欢黑咖啡"
    assert proposal.canonical_key_hint == "drink:coffee"
    assert proposal.confidence == 0.91
    assert proposal.source_message_ids == ("user-1",)
    assert result.provider == "recording-provider"
    assert result.model == "recording-model"
    assert result.elapsed_ms >= 0

    assert [current.role for current in provider.messages] == [
        ChatRole.SYSTEM,
        ChatRole.USER,
    ]
    payload = json.loads(provider.messages[1].content)
    assert set(payload) == {
        "disclosure_version",
        "schema_version",
        "user_message",
        "assistant_message",
    }
    assert payload == {
        "disclosure_version": MEMORY_EXTRACTION_DISCLOSURE_VERSION,
        "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
        "user_message": {"id": "user-1", "content": "我喜欢黑咖啡"},
        "assistant_message": {"id": "assistant-1", "content": "我知道了。"},
    }
    assert "session_id" not in provider.messages[1].content
    assert "session_summary" not in provider.messages[1].content
    assert "active_memories" not in provider.messages[1].content
    assert "metadata" not in provider.messages[1].content
    assert provider.options == LLMOptions(
        model="memory-test-model",
        timeout_seconds=15.0,
        max_retries=0,
        max_tokens=512,
    )


@pytest.mark.asyncio
async def test_provider_extractor_canonical_hint_never_controls_governor_key():
    provider = RecordingProvider(
        response_document([proposal_document(canonical_key_hint="remote-controlled")])
    )
    extractor = ProviderMemoryExtractor(provider, settings())
    result = await extractor.extract(
        user_message=user_message(),
        assistant_message=assistant_message(),
    )
    governor = MemoryGovernor(
        max_proposals=3,
        max_proposal_characters=200,
        max_total_characters=600,
    )

    governed = governor.evaluate(
        proposal=result.proposals[0],
        user_text="我喜欢黑咖啡",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )

    assert governed.canonical_key is not None
    assert governed.canonical_key != "remote-controlled"


@pytest.mark.parametrize(
    "text",
    [
        "```json\n{}\n```",
        "prefix " + response_document([]),
        response_document([]) + " suffix",
        "not-json",
        "",
        "null",
        "NaN",
    ],
)
@pytest.mark.asyncio
async def test_provider_extractor_rejects_non_exact_json_without_recovery(text):
    provider = RecordingProvider(text)
    extractor = ProviderMemoryExtractor(provider, settings())

    with pytest.raises(MemoryExtractionInvalidOutputError):
        await extractor.extract(
            user_message=user_message(),
            assistant_message=assistant_message(),
        )


@pytest.mark.parametrize(
    "text",
    [
        '{"schema_version":"memory-shadow-schema-v1",'
        '"schema_version":"memory-shadow-schema-v1","proposals":[]}',
        '{"schema_version":"memory-shadow-schema-v1","proposals":['
        '{"memory_type":"preference","memory_type":"other",'
        '"subject":"偏好","content":"用户喜欢咖啡",'
        '"canonical_key_hint":null,"confidence":0.9,'
        '"source_message_ids":["user-1"]}]}',
    ],
)
@pytest.mark.asyncio
async def test_provider_extractor_rejects_duplicate_json_keys(text):
    extractor = ProviderMemoryExtractor(RecordingProvider(text), settings())

    with pytest.raises(MemoryExtractionInvalidOutputError):
        await extractor.extract(
            user_message=user_message(),
            assistant_message=assistant_message(),
        )


@pytest.mark.asyncio
async def test_provider_extractor_maps_deep_json_to_invalid_output():
    deep_document = '{"x":' * 1200 + "null" + "}" * 1200
    extractor = ProviderMemoryExtractor(RecordingProvider(deep_document), settings())

    with pytest.raises(MemoryExtractionInvalidOutputError):
        await extractor.extract(
            user_message=user_message(),
            assistant_message=assistant_message(),
        )


@pytest.mark.parametrize(
    "document",
    [
        {"schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION, "proposals": [], "extra": 1},
        {"schema_version": "memory-shadow-schema-v2", "proposals": []},
        {"schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION},
        {"schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION, "proposals": {}},
    ],
)
@pytest.mark.asyncio
async def test_provider_extractor_rejects_wrong_top_level_contract(document):
    extractor = ProviderMemoryExtractor(
        RecordingProvider(json.dumps(document)),
        settings(),
    )

    with pytest.raises(MemoryExtractionInvalidOutputError):
        await extractor.extract(
            user_message=user_message(),
            assistant_message=assistant_message(),
        )


@pytest.mark.parametrize(
    "raw_proposal",
    [
        {**proposal_document(), "extra": "not-allowed"},
        {key: value for key, value in proposal_document().items() if key != "subject"},
        proposal_document(memory_type="commitment"),
        proposal_document(memory_type=1),
        proposal_document(subject=""),
        proposal_document(subject="s" * 121),
        proposal_document(content=""),
        proposal_document(content="c" * 201),
        proposal_document(canonical_key_hint=1),
        proposal_document(canonical_key_hint="h" * 121),
        proposal_document(confidence=True),
        proposal_document(confidence="0.9"),
        proposal_document(confidence=math.nan),
        proposal_document(confidence=math.inf),
        proposal_document(confidence=-0.1),
        proposal_document(confidence=1.1),
        proposal_document(source_message_ids=[]),
        proposal_document(source_message_ids=["assistant-1"]),
        proposal_document(source_message_ids=["user-1", "other-1"]),
        proposal_document(source_message_ids=["user-1", "user-1"]),
        proposal_document(source_message_ids=[1]),
    ],
)
@pytest.mark.asyncio
async def test_provider_extractor_rejects_invalid_proposal_contract(raw_proposal):
    extractor = ProviderMemoryExtractor(
        RecordingProvider(response_document([raw_proposal])),
        settings(),
    )

    with pytest.raises(MemoryExtractionInvalidOutputError):
        await extractor.extract(
            user_message=user_message(),
            assistant_message=assistant_message(),
        )


@pytest.mark.asyncio
async def test_provider_extractor_rejects_raw_proposal_count_over_budget_before_dedup():
    duplicate = proposal_document()
    extractor = ProviderMemoryExtractor(
        RecordingProvider(response_document([duplicate, duplicate, duplicate, duplicate])),
        settings(memory_extractor_max_proposals=3),
    )

    with pytest.raises(MemoryExtractionInvalidOutputError):
        await extractor.extract(
            user_message=user_message(),
            assistant_message=assistant_message(),
        )


@pytest.mark.asyncio
async def test_provider_extractor_rejects_raw_total_characters_over_budget_before_dedup():
    duplicate = proposal_document(content="重" * 11)
    extractor = ProviderMemoryExtractor(
        RecordingProvider(response_document([duplicate, duplicate])),
        settings(
            memory_extractor_max_proposals=2,
            memory_extractor_max_proposal_characters=20,
            memory_extractor_max_total_characters=20,
        ),
    )

    with pytest.raises(MemoryExtractionInvalidOutputError):
        await extractor.extract(
            user_message=user_message(),
            assistant_message=assistant_message(),
        )


@pytest.mark.asyncio
async def test_provider_extractor_preserves_duplicate_proposals_for_governor_handling():
    duplicate = proposal_document()
    provider = RecordingProvider(response_document([duplicate, duplicate]))
    extractor = ProviderMemoryExtractor(provider, settings())

    result = await extractor.extract(
        user_message=user_message(),
        assistant_message=assistant_message(),
    )

    assert [proposal.content for proposal in result.proposals] == [
        "用户喜欢黑咖啡",
        "用户喜欢黑咖啡",
    ]


@pytest.mark.asyncio
async def test_provider_extractor_allows_exact_raw_budgets():
    raw_proposals = [
        proposal_document(content="一" * 200),
        proposal_document(content="二" * 200),
        proposal_document(content="三" * 200),
    ]
    extractor = ProviderMemoryExtractor(
        RecordingProvider(response_document(raw_proposals)),
        settings(),
    )

    result = await extractor.extract(
        user_message=user_message(),
        assistant_message=assistant_message(),
    )

    assert len(result.proposals) == 3


@pytest.mark.parametrize(
    ("current_user", "current_assistant"),
    [
        (assistant_message(), assistant_message()),
        (user_message(), user_message()),
        (
            user_message(),
            message("assistant-1", ChatRole.ASSISTANT, "reply", session_id="session-2"),
        ),
        (
            message("same", ChatRole.USER, "user"),
            message("same", ChatRole.ASSISTANT, "assistant"),
        ),
        (user_message(content=1), assistant_message()),
        (user_message(), assistant_message(content=None)),
    ],
)
@pytest.mark.asyncio
async def test_extractors_reject_invalid_current_turn_messages(
    current_user,
    current_assistant,
):
    provider_extractor = ProviderMemoryExtractor(RecordingProvider(response_document([])), settings())
    local_extractor = LocalMemoryExtractor(settings())

    with pytest.raises((TypeError, ValueError)):
        await provider_extractor.extract(
            user_message=current_user,
            assistant_message=current_assistant,
        )
    with pytest.raises((TypeError, ValueError)):
        await local_extractor.extract(
            user_message=current_user,
            assistant_message=current_assistant,
        )


@pytest.mark.asyncio
async def test_provider_invalid_output_never_exposes_raw_response_in_exception_chain():
    secret = "RAW_RESPONSE_SENTINEL_03c1 sk-secret-private"
    extractor = ProviderMemoryExtractor(RecordingProvider(secret), settings())

    with pytest.raises(MemoryExtractionInvalidOutputError) as caught:
        await extractor.extract(
            user_message=user_message(),
            assistant_message=assistant_message(),
        )

    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    ("text", "expected_type", "expected_subject", "expected_content"),
    [
        ("我叫小航。", MemoryType.USER_FACT, "姓名", "用户叫小航"),
        ("我喜欢黑咖啡", MemoryType.PREFERENCE, "偏好", "用户喜欢黑咖啡"),
        ("我不喜欢香菜！", MemoryType.PREFERENCE, "不喜欢的事物", "用户不喜欢香菜"),
        ("我的目标是完成毕业论文。", MemoryType.LONG_TERM_GOAL, "长期目标", "用户的目标是完成毕业论文"),
        ("我计划明年去日本。", MemoryType.LONG_TERM_GOAL, "计划", "用户计划明年去日本"),
    ],
)
@pytest.mark.asyncio
async def test_local_extractor_only_extracts_anchored_stable_first_person_statements(
    text,
    expected_type,
    expected_subject,
    expected_content,
):
    extractor = LocalMemoryExtractor(settings())

    result = await extractor.extract(
        user_message=user_message(text),
        assistant_message=assistant_message("助手猜测用户也许喜欢茶"),
    )

    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.memory_type is expected_type
    assert proposal.subject == expected_subject
    assert proposal.content == expected_content
    assert proposal.source_message_ids == ("user-1",)
    assert result.provider == "local"
    assert result.model == MEMORY_LOCAL_RULES_VERSION


@pytest.mark.parametrize(
    "text",
    [
        "你好",
        "也许我喜欢咖啡",
        "助手说我喜欢咖啡",
        "他喜欢咖啡",
        "我今天有点难过",
        "我可能患有焦虑症",
        "我和助手很亲密",
        "我喜欢",
    ],
)
@pytest.mark.asyncio
async def test_local_extractor_does_not_infer_or_use_assistant_facts(text):
    extractor = LocalMemoryExtractor(settings())

    result = await extractor.extract(
        user_message=user_message(text),
        assistant_message=assistant_message("你喜欢咖啡，你的关系分数是 99"),
    )

    assert result.proposals == []


@pytest.mark.asyncio
async def test_local_extractor_respects_count_and_character_budgets():
    extractor = LocalMemoryExtractor(
        settings(
            memory_extractor_max_proposals=2,
            memory_extractor_max_proposal_characters=20,
            memory_extractor_max_total_characters=20,
        )
    )

    result = await extractor.extract(
        user_message=user_message("我喜欢咖啡。\n我不喜欢茶。\n我叫小航。"),
        assistant_message=assistant_message(),
    )

    assert len(result.proposals) == 2
    assert sum(len(item.content) for item in result.proposals) <= 20


@pytest.mark.asyncio
async def test_local_extractor_preserves_repeated_current_turn_matches_for_governor():
    extractor = LocalMemoryExtractor(settings())
    current_user = user_message("我喜欢黑咖啡。我喜欢黑咖啡。")

    result = await extractor.extract(
        user_message=current_user,
        assistant_message=assistant_message(),
    )

    assert [proposal.content for proposal in result.proposals] == [
        "用户喜欢黑咖啡",
        "用户喜欢黑咖啡",
    ]


@pytest.mark.asyncio
async def test_fake_provider_uses_disclosed_current_user_and_same_strict_parser():
    current_settings = settings()
    fake_provider = MemoryExtractionFakeProvider(current_settings)
    extractor = ProviderMemoryExtractor(fake_provider, current_settings)

    result = await extractor.extract(
        user_message=user_message("我喜欢红茶。"),
        assistant_message=assistant_message("我会记住。"),
    )

    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.memory_type is MemoryType.PREFERENCE
    assert proposal.content == "用户喜欢红茶"
    assert proposal.source_message_ids == ("user-1",)
    assert result.provider == "memory-fake"
    assert result.model == "memory-test-model"


@pytest.mark.asyncio
async def test_fake_provider_preserves_repeated_matching_clauses_for_governor():
    current_settings = settings()
    extractor = ProviderMemoryExtractor(
        MemoryExtractionFakeProvider(current_settings),
        current_settings,
    )

    result = await extractor.extract(
        user_message=user_message("我喜欢红茶。\n我喜欢红茶。"),
        assistant_message=assistant_message(),
    )

    assert [proposal.content for proposal in result.proposals] == [
        "用户喜欢红茶",
        "用户喜欢红茶",
    ]


@pytest.mark.asyncio
async def test_fake_provider_returns_empty_strict_document_for_bad_envelope():
    fake = MemoryExtractionFakeProvider(settings())

    response = await fake.generate(
        [LLMMessage(role=ChatRole.USER, content="not-the-approved-envelope")],
        LLMOptions(
            model="memory-test-model",
            timeout_seconds=1,
            max_retries=0,
            max_tokens=64,
        ),
    )

    assert json.loads(response.text) == {
        "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
        "proposals": [],
    }


def test_extractor_and_legacy_candidate_share_compatible_single_content_limit():
    assert settings().memory_extractor_max_proposal_characters == MAX_LLM_CANDIDATE_CONTENT_CHARS
