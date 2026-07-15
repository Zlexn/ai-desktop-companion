import json
from threading import Lock
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict

TEST_TOKEN = "stage4c-e2e-token"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    messages: list[ChatMessage]
    max_tokens: int
    stream: bool
    thinking: dict[str, object] | None = None


app = FastAPI(title="Stage 4C Fake DeepSeek")
_requests: list[dict[str, object]] = []
_lock = Lock()


def _analysis_input(payload: ChatCompletionRequest) -> dict[str, Any]:
    user_messages = [message for message in payload.messages if message.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=422, detail="missing user analysis payload")
    try:
        value = json.loads(user_messages[-1].content)
        current_turn = value["current_turn"]
        if not isinstance(value, dict) or not isinstance(current_turn, dict):
            raise TypeError
        for key in ("user_message_id", "assistant_message_id"):
            if not isinstance(current_turn.get(key), str) or not current_turn[key]:
                raise TypeError
    except (json.JSONDecodeError, KeyError, TypeError):
        raise HTTPException(status_code=422, detail="invalid user analysis payload") from None
    return value


@app.post("/chat/completions")
def chat_completions(
    request: Request,
    payload: ChatCompletionRequest,
) -> dict[str, object]:
    if request.headers.get("authorization") != f"Bearer {TEST_TOKEN}":
        raise HTTPException(status_code=401, detail="invalid test token")

    analysis_input = _analysis_input(payload)
    current_turn = analysis_input["current_turn"]
    recorded_request = {
        "model": payload.model,
        "messages": [message.model_dump() for message in payload.messages],
        "max_tokens": payload.max_tokens,
        "stream": payload.stream,
        "thinking": payload.thinking,
    }
    with _lock:
        _requests.append(recorded_request)
        request_number = len(_requests)

    proposal = {
        "schema_version": "emotion_analysis_v1",
        "should_apply": True,
        "signals": ["distress"],
        "proposed_delta": {
            "mood": -0.02,
            "trust": 0.0,
            "concern": 0.04,
            "distance": 0.0,
            "irritation": 0.0,
            "formality": 0.0,
        },
        "source_ids": [
            current_turn["user_message_id"],
            current_turn["assistant_message_id"],
        ],
        "reason_codes": ["user_distress"],
    }
    return {
        "id": f"stage4c-e2e-{request_number}",
        "model": payload.model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(proposal, ensure_ascii=False),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
        },
    }


@app.get("/__test__/state")
def test_state() -> dict[str, object]:
    with _lock:
        requests = list(_requests)
    return {"request_count": len(requests), "requests": requests}


@app.post("/__test__/reset")
def reset_test_state() -> dict[str, object]:
    with _lock:
        _requests.clear()
    return {"request_count": 0, "requests": []}
