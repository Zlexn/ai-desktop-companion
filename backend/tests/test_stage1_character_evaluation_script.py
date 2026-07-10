from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from scripts.run_stage1_character_evaluation import (
    EVAL_CASES,
    EvaluationError,
    Stage1CharacterEvaluator,
    main,
)


class FakeStage1Api:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.sessions_created: list[str] = []
        self.sessions_deleted: list[str] = []
        self.messages_by_session: dict[str, list[dict[str, Any]]] = {}
        self.fail_once = False
        self.provider = "deepseek"
        self.model = "deepseek-v4-flash"
        self.reply = "有效回复"

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(
            {
                "method": request.method,
                "path": request.url.path,
                "body": request.content.decode("utf-8") if request.content else "",
                "headers": dict(request.headers),
            }
        )
        if request.method == "POST" and request.url.path == "/api/sessions":
            session_id = f"session-{len(self.sessions_created) + 1}"
            self.sessions_created.append(session_id)
            self.messages_by_session[session_id] = []
            return httpx.Response(201, json={"id": session_id, "title": session_id})
        if request.method == "POST" and request.url.path.endswith("/messages"):
            if self.fail_once:
                self.fail_once = False
                return httpx.Response(500, json={"error": {"code": "provider_error"}})
            session_id = request.url.path.split("/")[3]
            payload = json.loads(request.content.decode("utf-8"))
            self.messages_by_session[session_id].append({"role": "user", "content": payload["content"], "metadata": {}})
            self.messages_by_session[session_id].append(
                {
                    "role": "assistant",
                    "content": self.reply,
                    "metadata": {
                        "provider": self.provider,
                        "model": self.model,
                        "finish_reason": "stop",
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            )
            return httpx.Response(
                200,
                json={
                    "reply": self.reply,
                    "metadata": {"provider": self.provider, "model": self.model},
                },
            )
        if request.method == "GET" and request.url.path.endswith("/messages"):
            session_id = request.url.path.split("/")[3]
            return httpx.Response(200, json=self.messages_by_session[session_id])
        if request.method == "DELETE" and request.url.path.startswith("/api/sessions/"):
            self.sessions_deleted.append(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(204)
        return httpx.Response(404, json={"error": "not found"})


def make_evaluator(tmp_path: Path, api: FakeStage1Api) -> Stage1CharacterEvaluator:
    client = httpx.Client(
        transport=httpx.MockTransport(api.handler),
        base_url="http://127.0.0.1:18083",
        timeout=120,
    )
    return Stage1CharacterEvaluator(
        base_url="http://127.0.0.1:18083",
        output_path=tmp_path / "results.json",
        expected_provider="deepseek",
        expected_model="deepseek-v4-flash",
        timeout=120,
        client=client,
    )


def test_dry_run_sends_no_requests(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--dry-run"]) == 0

    output = capsys.readouterr().out

    assert "dry-run: no HTTP requests will be sent" in output
    assert "planned_generation_calls=12" in output
    assert "T01" in output
    assert "T07-R" in output


def test_run_makes_exactly_12_generation_calls(tmp_path: Path) -> None:
    api = FakeStage1Api()
    evaluator = make_evaluator(tmp_path, api)

    evaluator.run()

    generation_requests = [request for request in api.requests if request["method"] == "POST" and request["path"].endswith("/messages")]
    assert len(generation_requests) == 12
    assert evaluator.generation_calls == 12
    result = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert result["planned_generation_calls"] == 12
    assert result["actual_generation_calls"] == 12
    assert result["automatic_retries"] == 0


def test_generation_budget_prevents_thirteenth_call(tmp_path: Path) -> None:
    api = FakeStage1Api()
    evaluator = make_evaluator(tmp_path, api)
    extra_case = EVAL_CASES[0]
    object.__setattr__(evaluator, "cases", (*EVAL_CASES, extra_case))

    with pytest.raises(EvaluationError) as exc_info:
        evaluator.run()

    generation_requests = [request for request in api.requests if request["method"] == "POST" and request["path"].endswith("/messages")]
    assert exc_info.value.category == "generation_budget_exceeded"
    assert len(generation_requests) == 12


def test_t08_uses_same_session_and_other_cases_use_independent_sessions(tmp_path: Path) -> None:
    api = FakeStage1Api()
    evaluator = make_evaluator(tmp_path, api)

    evaluator.run()

    result = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    session_by_case = {case["id"]: case["session_id"] for case in result["cases"]}
    assert session_by_case["T08-1"] == session_by_case["T08-2"]
    assert session_by_case["T04"] != session_by_case["T04-R"]
    assert session_by_case["T05"] != session_by_case["T05-R"]
    assert session_by_case["T07"] != session_by_case["T07-R"]
    independent_session_ids = [session_by_case[case_id] for case_id in session_by_case if case_id != "T08-2"]
    assert len(independent_session_ids) == len(set(independent_session_ids))


def test_single_failure_stops_without_retry(tmp_path: Path) -> None:
    api = FakeStage1Api()
    api.fail_once = True
    evaluator = make_evaluator(tmp_path, api)

    with pytest.raises(EvaluationError) as exc_info:
        evaluator.run()

    generation_requests = [request for request in api.requests if request["method"] == "POST" and request["path"].endswith("/messages")]
    assert exc_info.value.category == "http_status_error"
    assert len(generation_requests) == 1


def test_result_file_excludes_secrets_and_system_prompt_fields(tmp_path: Path) -> None:
    api = FakeStage1Api()
    evaluator = make_evaluator(tmp_path, api)

    evaluator.run()

    raw_result = (tmp_path / "results.json").read_text(encoding="utf-8")
    assert "api_key" not in raw_result.lower()
    assert "authorization" not in raw_result.lower()
    assert "system_prompt" not in raw_result
    assert "reasoning_content" not in raw_result


def test_finally_deletes_created_sessions_after_failure(tmp_path: Path) -> None:
    api = FakeStage1Api()
    evaluator = make_evaluator(tmp_path, api)
    api.provider = "wrong-provider"

    with pytest.raises(EvaluationError):
        evaluator.run()

    assert api.sessions_created
    assert api.sessions_deleted == api.sessions_created


def test_provider_mismatch_fails(tmp_path: Path) -> None:
    api = FakeStage1Api()
    api.provider = "fake"
    evaluator = make_evaluator(tmp_path, api)

    with pytest.raises(EvaluationError) as exc_info:
        evaluator.run()

    assert exc_info.value.category == "provider_mismatch"


def test_model_mismatch_fails(tmp_path: Path) -> None:
    api = FakeStage1Api()
    api.model = "other-model"
    evaluator = make_evaluator(tmp_path, api)

    with pytest.raises(EvaluationError) as exc_info:
        evaluator.run()

    assert exc_info.value.category == "model_mismatch"


def test_empty_reply_fails(tmp_path: Path) -> None:
    api = FakeStage1Api()
    api.reply = "   "
    evaluator = make_evaluator(tmp_path, api)

    with pytest.raises(EvaluationError) as exc_info:
        evaluator.run()

    assert exc_info.value.category == "empty_reply"
