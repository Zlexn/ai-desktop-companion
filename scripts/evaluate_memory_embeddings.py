from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.memory_embedding_service import (  # noqa: E402
    FakeMemoryEmbeddingProvider,
    MemoryEmbeddingProvider,
    MemoryEmbeddingUnavailableError,
    SentenceTransformersMemoryEmbeddingProvider,
)

MEMORY_FIXTURES: list[dict[str, str]] = [
    {"id": "pref_tea", "memory_type": "preference", "content": "用户喜欢红茶。"},
    {"id": "pref_coffee", "memory_type": "preference", "content": "用户不喜欢咖啡。"},
    {"id": "pref_language", "memory_type": "preference", "content": "用户偏好简洁中文回复。"},
    {"id": "fact_city", "memory_type": "user_fact", "content": "用户住在上海。"},
    {"id": "fact_job", "memory_type": "user_fact", "content": "用户的职业是后端工程师。"},
    {"id": "goal_pet", "memory_type": "long_term_goal", "content": "用户的目标是完成本地 AI 桌宠项目。"},
    {"id": "goal_exam", "memory_type": "long_term_goal", "content": "用户正在准备日语考试。"},
    {"id": "event_trip", "memory_type": "important_event", "content": "用户去年冬天去过北海道。"},
    {"id": "relationship_help", "memory_type": "relationship_event", "content": "用户希望角色在项目推进时多提醒风险。"},
]

EVALUATION_CASES: list[dict[str, str]] = [
    {"query": "我平时爱喝什么？", "expected_id": "pref_tea"},
    {"query": "我不爱喝哪种饮料？", "expected_id": "pref_coffee"},
    {"query": "你回复我时语言上有什么偏好？", "expected_id": "pref_language"},
    {"query": "我现在住在哪个城市？", "expected_id": "fact_city"},
    {"query": "我的工作是什么？", "expected_id": "fact_job"},
    {"query": "我的长期项目目标是什么？", "expected_id": "goal_pet"},
    {"query": "我最近在准备什么考试？", "expected_id": "goal_exam"},
    {"query": "我希望你在推进项目时怎么帮助我？", "expected_id": "relationship_help"},
]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def rank_memories(
    *,
    provider: MemoryEmbeddingProvider,
    query: str,
    memories: list[dict[str, str]],
    top_k: int,
) -> list[dict[str, Any]]:
    query_embedding = provider.embed_text(query)
    ranked: list[dict[str, Any]] = []
    for memory in memories:
        score = cosine_similarity(query_embedding, provider.embed_text(memory["content"]))
        ranked.append({**memory, "score": score})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:top_k]


def evaluate_provider(
    *,
    provider: MemoryEmbeddingProvider,
    min_top1_accuracy: float,
    min_top3_recall: float,
    include_details: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    details: list[dict[str, Any]] = []
    top1_hits = 0
    top3_hits = 0
    for case in EVALUATION_CASES:
        ranked = rank_memories(provider=provider, query=case["query"], memories=MEMORY_FIXTURES, top_k=3)
        top_ids = [item["id"] for item in ranked]
        hit_top1 = bool(top_ids and top_ids[0] == case["expected_id"])
        hit_top3 = case["expected_id"] in top_ids
        top1_hits += int(hit_top1)
        top3_hits += int(hit_top3)
        details.append(
            {
                "query": case["query"],
                "expected_id": case["expected_id"],
                "top_ids": top_ids,
                "hit_top1": hit_top1,
                "hit_top3": hit_top3,
            }
        )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    case_count = len(EVALUATION_CASES)
    top1_accuracy = top1_hits / case_count
    top3_recall = top3_hits / case_count
    summary: dict[str, Any] = {
        "provider": provider.provider_name,
        "model": provider.model_name,
        "case_count": case_count,
        "top1_accuracy": round(top1_accuracy, 4),
        "top3_recall": round(top3_recall, 4),
        "embed_ms": round(elapsed_ms, 2),
        "passed": top1_accuracy >= min_top1_accuracy and top3_recall >= min_top3_recall,
        "thresholds": {
            "min_top1_accuracy": min_top1_accuracy,
            "min_top3_recall": min_top3_recall,
        },
    }
    if include_details:
        summary["details"] = details
    return summary


def create_provider(provider_name: str, model: str) -> MemoryEmbeddingProvider:
    if provider_name == "fake":
        return FakeMemoryEmbeddingProvider(model=model)
    if provider_name == "sentence-transformers":
        return SentenceTransformersMemoryEmbeddingProvider(model=model)
    raise ValueError("provider must be one of: fake, sentence-transformers")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Stage 3 memory embedding retrieval on fixed Chinese fixtures.")
    parser.add_argument("--provider", choices=("fake", "sentence-transformers"), default="fake")
    parser.add_argument("--model", default="fake-memory-embedding-v1")
    parser.add_argument("--min-top1-accuracy", type=float, default=0.5)
    parser.add_argument("--min-top3-recall", type=float, default=0.75)
    parser.add_argument("--details", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model = args.model
    if args.provider == "sentence-transformers" and model == "fake-memory-embedding-v1":
        model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    load_started = time.perf_counter()
    try:
        provider = create_provider(args.provider, model)
        if args.provider == "sentence-transformers":
            provider.embed_text("加载测试")
    except MemoryEmbeddingUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    load_ms = (time.perf_counter() - load_started) * 1000.0
    summary = evaluate_provider(
        provider=provider,
        min_top1_accuracy=args.min_top1_accuracy,
        min_top3_recall=args.min_top3_recall,
        include_details=args.details,
    )
    summary["load_ms"] = round(load_ms, 2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
