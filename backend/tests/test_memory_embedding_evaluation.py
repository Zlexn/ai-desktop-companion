import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.memory_embedding_service import FakeMemoryEmbeddingProvider, MemoryEmbeddingUnavailableError  # noqa: E402
from scripts import evaluate_memory_embeddings  # noqa: E402
from scripts.evaluate_memory_embeddings import (  # noqa: E402
    EVALUATION_CASES,
    MEMORY_FIXTURES,
    evaluate_provider,
    rank_memories,
)


def test_stage3h_setup_helper_uses_isolated_memory_embedding_env() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    setup_script = (ROOT / "scripts" / "setup_memory_embedding_env.ps1").read_text(encoding="utf-8")

    assert ".venv-memory-embed/" in gitignore
    assert ".venv-memory-embed" in setup_script
    assert "sentence-transformers" in setup_script
    assert "pip install -e" in setup_script
    assert "evaluate_memory_embeddings.py --provider sentence-transformers" in setup_script


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


def test_measure_embedding_dimension_uses_provider_vector_length() -> None:
    provider = FakeMemoryEmbeddingProvider()

    dimension = evaluate_memory_embeddings.measure_embedding_dimension(provider)

    assert dimension == 6


def test_split_compare_models_trims_and_drops_empty_items() -> None:
    models = evaluate_memory_embeddings.split_compare_models(
        " sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2, , BAAI/bge-m3 "
    )

    assert models == [
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "BAAI/bge-m3",
    ]


def test_split_compare_models_returns_empty_list_for_blank_value() -> None:
    assert evaluate_memory_embeddings.split_compare_models(" ,  , ") == []


def test_create_sentence_transformers_provider_surfaces_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    class MissingProvider:
        def __init__(self, model: str) -> None:
            raise MemoryEmbeddingUnavailableError("sentence-transformers is not installed")

    monkeypatch.setattr(evaluate_memory_embeddings, "SentenceTransformersMemoryEmbeddingProvider", MissingProvider)

    with pytest.raises(MemoryEmbeddingUnavailableError, match="sentence-transformers is not installed"):
        evaluate_memory_embeddings.create_provider("sentence-transformers", "test-model")
