# Stage 3G Real Embedding Smoke Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repeatable fake-provider and optional real-provider smoke script for Chinese long-term memory embedding retrieval quality.

**Architecture:** Implement a standalone evaluation script that imports the existing Stage 3F memory embedding providers, evaluates fixed Chinese memory/query fixtures in memory, and prints JSON metrics. Automated tests cover fake-provider metrics and missing real-provider dependency behavior; real `sentence-transformers` smoke remains manual/optional.

**Tech Stack:** Python 3.11+, pytest, existing backend `MemoryEmbeddingProvider` implementations, no new mandatory dependency.

---

## Scope and constraints

This plan implements Stage 3G only.

It must not implement:

- Stage 4 emotion state or expression strategy;
- LLM-based memory candidate extraction;
- automatic memory writes from chat history;
- session summaries;
- sqlite-vec or another vector index;
- mandatory `sentence-transformers` dependency.

Do not commit unless the user explicitly asks for a commit. The writing-plans skill template suggests frequent commits, but this project session rule is stricter: commits require explicit user authorization.

## File structure

Create:

- `scripts/evaluate_memory_embeddings.py`
  - Standalone CLI and importable helpers for fixed Chinese retrieval fixture evaluation.
  - Imports existing `FakeMemoryEmbeddingProvider` and `SentenceTransformersMemoryEmbeddingProvider` from `backend/app/services/memory_embedding_service.py`.
  - Does not touch the app database.

- `backend/tests/test_memory_embedding_evaluation.py`
  - Tests fixture uniqueness, cosine/ranking logic, fake provider metrics, JSON-compatible summary, and missing real-provider dependency handling.

- `docs/stage3g-real-embedding-smoke.md`
  - Evidence document after implementation and validation.

Modify:

- `README.md`
  - Add optional Stage 3G smoke command after validation.

- `CLAUDE.md`
  - Update Stage 3 current status after validation passes.

No source product behavior should change.

---

### Task 1: Evaluation script fixtures and fake-provider metrics

**Files:**
- Create: `scripts/evaluate_memory_embeddings.py`
- Create: `backend/tests/test_memory_embedding_evaluation.py`

- [ ] **Step 1: Write failing tests for fixtures and fake evaluation**

Create `backend/tests/test_memory_embedding_evaluation.py` with:

```python
import json
from pathlib import Path

import pytest

import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate_memory_embeddings import (  # noqa: E402
    EVALUATION_CASES,
    MEMORY_FIXTURES,
    evaluate_provider,
    rank_memories,
)
from app.services.memory_embedding_service import FakeMemoryEmbeddingProvider  # noqa: E402


def test_memory_embedding_fixtures_have_unique_ids() -> None:
    ids = [memory["id"] for memory in MEMORY_FIXTURES]

    assert len(ids) == len(set(ids))
    assert len(MEMORY_FIXTURES) >= 8
    assert len(EVALUATION_CASES) >= 8


def test_rank_memories_orders_expected_memory_first() -> None:
    provider = FakeMemoryEmbeddingProvider()
    ranked = rank_memories(
        provider=provider,
        query="我平时爱喝什么？",
        memories=MEMORY_FIXTURES,
        top_k=3,
    )

    assert ranked[0]["id"] == "pref_tea"
    assert len(ranked) == 3
    assert ranked[0]["score"] >= ranked[1]["score"]


def test_fake_provider_evaluation_summary_is_json_compatible_and_passes() -> None:
    provider = FakeMemoryEmbeddingProvider()

    summary = evaluate_provider(
        provider=provider,
        min_top1_accuracy=0.5,
        min_top3_recall=0.75,
        include_details=True,
    )

    assert summary["provider"] == "fake"
    assert summary["model"] == "fake-memory-embedding-v1"
    assert summary["case_count"] == len(EVALUATION_CASES)
    assert summary["top1_accuracy"] >= 0.5
    assert summary["top3_recall"] >= 0.75
    assert summary["passed"] is True
    assert len(summary["details"]) == len(EVALUATION_CASES)
    json.dumps(summary, ensure_ascii=False)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.evaluate_memory_embeddings'` or missing exported names.

- [ ] **Step 3: Implement evaluation script**

Create `scripts/evaluate_memory_embeddings.py`:

```python
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
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py -q
```

Expected: PASS.

---

### Task 2: Missing real dependency behavior and CLI smoke

**Files:**
- Modify: `backend/tests/test_memory_embedding_evaluation.py`
- Modify: `scripts/evaluate_memory_embeddings.py` only if tests reveal missing behavior

- [ ] **Step 1: Add failing test for missing real provider dependency**

Append to `backend/tests/test_memory_embedding_evaluation.py`:

```python
from app.services.memory_embedding_service import MemoryEmbeddingUnavailableError  # noqa: E402
from scripts import evaluate_memory_embeddings  # noqa: E402


def test_create_sentence_transformers_provider_surfaces_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    class MissingProvider:
        def __init__(self, model: str) -> None:
            raise MemoryEmbeddingUnavailableError("sentence-transformers is not installed")

    monkeypatch.setattr(evaluate_memory_embeddings, "SentenceTransformersMemoryEmbeddingProvider", MissingProvider)

    with pytest.raises(MemoryEmbeddingUnavailableError, match="sentence-transformers is not installed"):
        evaluate_memory_embeddings.create_provider("sentence-transformers", "test-model")
```

- [ ] **Step 2: Run tests and verify behavior**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py -q
```

Expected: PASS if Task 1's provider factory is already correct. If it fails, update `create_provider` so it does not swallow `MemoryEmbeddingUnavailableError`.

- [ ] **Step 3: Run fake CLI smoke**

Run:

```powershell
python scripts/evaluate_memory_embeddings.py --provider fake --details
```

Expected: exit code 0 and JSON output with:

```json
"provider": "fake"
"passed": true
```

Record exact metrics for the evidence doc.

- [ ] **Step 4: Run optional real-provider probe**

Run:

```powershell
python scripts/evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

Expected if dependency is not installed: exit code 2 and stderr containing:

```text
sentence-transformers is not installed
```

If dependency is installed locally, expected: JSON output with provider `sentence-transformers`. Record exact metrics and whether thresholds passed. Do not fail the Stage 3G implementation solely because the optional dependency is absent.

---

### Task 3: Documentation and status update

**Files:**
- Create: `docs/stage3g-real-embedding-smoke.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Create evidence document**

Create `docs/stage3g-real-embedding-smoke.md`:

```markdown
# Stage 3G Real Embedding Smoke and Chinese Retrieval Evaluation

Date: 2026-07-08
Status: VERIFIED PASS

## Scope

Stage 3G adds a repeatable smoke/evaluation script for Stage 3F memory embedding retrieval. It uses fixed Chinese fixture memories and queries to evaluate top-k retrieval quality for the fake provider and optional local `sentence-transformers` provider.

## Non-goals

- No LLM-based memory extraction.
- No automatic long-term memory writes from chat history.
- No session summaries.
- No Stage 4 emotion system.
- No sqlite-vec or vector database integration.
- No mandatory real embedding dependency.

## Commands

```powershell
python scripts/evaluate_memory_embeddings.py --provider fake --details
python scripts/evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

## Validation

Record exact command results after running:

- `python -m pytest backend/tests/test_memory_embedding_evaluation.py -q`
- `python scripts/evaluate_memory_embeddings.py --provider fake --details`
- optional real provider command result
- focused/full backend tests as run

## Result summary

Fill this section with exact observed fake-provider metrics and optional real-provider status.

## Limitations

This is a smoke fixture, not a production benchmark. Passing it does not choose a production embedding model. If the real provider is unavailable because `sentence-transformers` is not installed, that is recorded as an environment limitation rather than a product failure.
```

Replace the `Fill this section` line with actual observed results before final response.

- [ ] **Step 2: Update README**

Add after the Stage 3F README note:

```markdown
### Stage 3G real embedding smoke

A standalone smoke/evaluation script checks Chinese memory retrieval quality without touching the app database:

```powershell
python scripts/evaluate_memory_embeddings.py --provider fake --details
python scripts/evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

The real provider command is optional and requires `sentence-transformers` plus model download availability. This smoke does not create memories, summarize sessions, or implement emotional state.
```

- [ ] **Step 3: Update CLAUDE.md after validation**

After tests and smoke pass, add under Stage 3 current entry:

```markdown
- 3G Real Embedding Smoke and Chinese Retrieval Evaluation 已完成（2026-07-08；新增 `scripts/evaluate_memory_embeddings.py`，使用固定中文长期记忆 fixture 评估 fake provider 和可选 `sentence-transformers` provider 的 top-k 检索；默认不新增强制依赖、不改产品行为、不写入聊天历史或长期记忆；证据记录于 `docs/stage3g-real-embedding-smoke.md`）。验证：按实际命令结果填写。
```

Also update the Stage 3 table row so the next allowed tasks mention LLM candidate extraction, session summaries, or real embedding model production selection rather than the just-finished smoke.

---

### Task 4: Verification run

**Files:**
- No source edits unless a command fails due a real defect.

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 2: Run fake evaluation smoke**

Run:

```powershell
python scripts/evaluate_memory_embeddings.py --provider fake --details
```

Expected: exit code 0 and `"passed": true`.

- [ ] **Step 3: Run optional real-provider command**

Run:

```powershell
python scripts/evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

Expected in current checked environment: likely exit code 2 with missing dependency message because `sentence_transformers` was not installed during design exploration. If it runs successfully, record exact metrics.

- [ ] **Step 4: Run backend full tests**

Run:

```powershell
python -m pytest backend/tests -q
```

Expected: PASS.

- [ ] **Step 5: Run frontend regression if source docs only changed plus script**

Because this task does not modify frontend source, frontend full regression is optional. If time allows, run:

```powershell
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Expected: PASS. If skipped, state that it was skipped because no frontend runtime code changed.

- [ ] **Step 6: Scope/privacy check**

Run:

```powershell
git diff -- scripts/evaluate_memory_embeddings.py backend/tests/test_memory_embedding_evaluation.py docs/stage3g-real-embedding-smoke.md README.md CLAUDE.md
```

Expected: diff contains only fixed fixture data, smoke/evaluation logic, and documentation. It must not include API keys, real private chat history, automatic memory writes, session summaries, or Stage 4 emotion state.

---

## Self-review checklist

- Spec coverage: The plan covers script, fake-provider evaluation, optional real-provider behavior, metrics, docs, and status update.
- Placeholder scan: The evidence doc task instructs replacing the temporary result line before final response.
- Type consistency: `MEMORY_FIXTURES`, `EVALUATION_CASES`, `rank_memories`, `evaluate_provider`, and `create_provider` are introduced in Task 1 before later tests use them.
- Scope check: The plan does not implement LLM extraction, session summaries, vector index integration, or Stage 4 emotion state.
