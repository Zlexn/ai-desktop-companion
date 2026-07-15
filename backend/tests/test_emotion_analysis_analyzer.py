import json

import pytest

from app.domain.models import ChatRole, EmotionVector
from app.providers.base import LLMResponse
from app.services.emotion_analysis_analyzer import (
    EMOTION_ANALYSIS_SCHEMA_VERSION,
    EmotionAnalysisParseError,
    EmotionAnalysisParser,
    LLMEmotionAnalyzer,
)
from app.services.emotion_analysis_input import (
    AnalysisCurrentTurn,
    EmotionAnalysisInput,
)


VALID_OUTPUT = {
    "schema_version": "emotion_analysis_v1",
    "should_apply": True,
    "signals": ["distress"],
    "proposed_delta": {
        "mood": -0.03,
        "trust": 0.0,
        "concern": 0.08,
        "distance": 0.0,
        "irritation": 0.0,
        "formality": 0.01,
    },
    "source_ids": ["user-1", "assistant-1"],
    "reason_codes": ["user_distress"],
}


def _input() -> EmotionAnalysisInput:
    return EmotionAnalysisInput(
        current_turn=AnalysisCurrentTurn(
            user_message_id="user-1",
            user_content="我今天有点难过",
            assistant_message_id="assistant-1",
            assistant_content="先休息一下。",
        ),
        recent_messages=(),
        memories=(),
        input_characters=15,
        redaction_count=0,
    )


class RecordingProvider:
    provider_name = "fake-analysis"

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = []

    async def generate(self, messages, options):
        self.calls.append((messages, options))
        return LLMResponse(text=self.text, provider=self.provider_name, model=options.model)


def test_parser_accepts_exact_valid_schema() -> None:
    parsed = EmotionAnalysisParser().parse(
        json.dumps(VALID_OUTPUT),
        allowed_source_ids={"user-1", "assistant-1"},
    )

    assert parsed.schema_version == EMOTION_ANALYSIS_SCHEMA_VERSION
    assert parsed.should_apply is True
    assert parsed.signals == ("distress",)
    assert parsed.proposed_delta == EmotionVector(-0.03, 0.0, 0.08, 0.0, 0.0, 0.01)
    assert parsed.source_ids == ("user-1", "assistant-1")
    assert parsed.reason_codes == ("user_distress",)


@pytest.mark.parametrize(
    "payload",
    [
        "```json\n{}\n```",
        "analysis: {}",
        json.dumps({**VALID_OUTPUT, "extra": "forbidden"}),
        json.dumps({key: value for key, value in VALID_OUTPUT.items() if key != "signals"}),
        json.dumps({**VALID_OUTPUT, "signals": ["unknown"]}),
        json.dumps({**VALID_OUTPUT, "reason_codes": ["free text"]}),
        json.dumps({**VALID_OUTPUT, "source_ids": ["forged-id"]}),
        json.dumps({**VALID_OUTPUT, "signals": []}),
        json.dumps({**VALID_OUTPUT, "source_ids": []}),
        json.dumps({**VALID_OUTPUT, "reason_codes": []}),
        json.dumps({**VALID_OUTPUT, "proposed_delta": {**VALID_OUTPUT["proposed_delta"], "mood": True}}),
        json.dumps({**VALID_OUTPUT, "proposed_delta": {**VALID_OUTPUT["proposed_delta"], "mood": float("nan")}}),
        json.dumps({**VALID_OUTPUT, "proposed_delta": {**VALID_OUTPUT["proposed_delta"], "mood": float("inf")}}),
    ],
)
def test_parser_rejects_wrappers_unknown_fields_types_and_forged_ids(payload: str) -> None:
    with pytest.raises(EmotionAnalysisParseError):
        EmotionAnalysisParser().parse(
            payload,
            allowed_source_ids={"user-1", "assistant-1"},
        )


def test_parser_rejects_duplicate_keys_at_any_depth() -> None:
    duplicate_top_level = json.dumps(VALID_OUTPUT).replace(
        '"should_apply": true,',
        '"should_apply": false, "should_apply": true,',
    )
    duplicate_nested = json.dumps(VALID_OUTPUT).replace(
        '"mood": -0.03,',
        '"mood": 0.0, "mood": -0.03,',
    )

    for payload in (duplicate_top_level, duplicate_nested):
        with pytest.raises(EmotionAnalysisParseError, match="duplicate"):
            EmotionAnalysisParser().parse(
                payload,
                allowed_source_ids={"user-1", "assistant-1"},
            )


    payload = {
        **VALID_OUTPUT,
        "should_apply": False,
        "proposed_delta": {**VALID_OUTPUT["proposed_delta"], "concern": 0.01},
    }

    with pytest.raises(EmotionAnalysisParseError, match="zero delta"):
        EmotionAnalysisParser().parse(
            json.dumps(payload),
            allowed_source_ids={"user-1", "assistant-1"},
        )


@pytest.mark.asyncio
async def test_analyzer_marks_payload_untrusted_and_requests_json_only() -> None:
    provider = RecordingProvider(json.dumps(VALID_OUTPUT))
    analyzer = LLMEmotionAnalyzer(
        provider=provider,
        model="analysis-model",
        max_tokens=384,
        timeout_seconds=10.0,
        max_retries=0,
    )

    result = await analyzer.analyze(_input())

    assert result.should_apply is True
    assert len(provider.calls) == 1
    messages, options = provider.calls[0]
    assert [message.role for message in messages] == [ChatRole.SYSTEM, ChatRole.USER]
    assert "untrusted" in messages[0].content.lower()
    assert "JSON" in messages[0].content
    assert "Required top-level fields exactly" in messages[0].content
    assert "proposed_delta fields exactly" in messages[0].content
    assert "不得诊断" in messages[0].content
    assert json.loads(messages[1].content)["current_turn"]["user_message_id"] == "user-1"
    assert options.model == "analysis-model"
    assert options.max_tokens == 384
    assert options.max_retries == 0


@pytest.mark.asyncio
async def test_analyzer_rejects_empty_or_invalid_provider_output() -> None:
    for output in ("", "not json"):
        provider = RecordingProvider(output)
        analyzer = LLMEmotionAnalyzer(
            provider=provider,
            model="analysis-model",
            max_tokens=384,
            timeout_seconds=10.0,
            max_retries=0,
        )
        with pytest.raises(EmotionAnalysisParseError):
            await analyzer.analyze(_input())
