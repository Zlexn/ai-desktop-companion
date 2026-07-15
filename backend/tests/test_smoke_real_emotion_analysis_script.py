import json
from pathlib import Path

from app.providers.base import LLMResponse
from scripts.smoke_real_emotion_analysis import SKIPPED_EXIT_CODE, main


class DeterministicAnalysisProvider:
    provider_name = "deepseek"

    async def generate(self, messages, options):
        current_turn = json.loads(messages[1].content)["current_turn"]
        return LLMResponse(
            text=json.dumps(
                {
                    "schema_version": "emotion_analysis_v1",
                    "should_apply": True,
                    "signals": ["support_request"],
                    "proposed_delta": {
                        "mood": 0.0,
                        "trust": 0.0,
                        "concern": 0.03,
                        "distance": 0.0,
                        "irritation": 0.0,
                        "formality": 0.0,
                    },
                    "source_ids": [
                        current_turn["user_message_id"],
                        current_turn["assistant_message_id"],
                    ],
                    "reason_codes": ["user_requested_support"],
                }
            ),
            provider="deepseek",
            model=options.model,
        )

    async def aclose(self) -> None:
        return None


def test_smoke_skips_without_explicit_environment_key(
    tmp_path: Path,
    capsys,
) -> None:
    result = main(
        ["--database", str(tmp_path / "skip.db")],
        environ={},
    )

    assert result == SKIPPED_EXIT_CODE
    assert "SKIPPED" in capsys.readouterr().out


def test_smoke_reports_safe_pass_with_injected_provider(
    tmp_path: Path,
    capsys,
) -> None:
    database_path = tmp_path / "smoke.db"
    result = main(
        ["--database", str(database_path), "--model", "test-analysis-model"],
        environ={"DEEPSEEK_API_KEY": "real-smoke-test-key"},
        emotion_provider_factory=DeterministicAnalysisProvider,
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "PASS" in output
    assert "audit_outcome=applied" in output
    assert "real-smoke-test-key" not in output
    assert "虚构测试" not in output
    assert "schema_version" not in output
    assert not database_path.exists()
