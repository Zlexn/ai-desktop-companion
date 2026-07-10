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
    assert "BAAI/bge-m3" in setup_script
    assert "--compare-models" in setup_script

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


def test_default_model_for_provider_keeps_fake_default() -> None:
    assert evaluate_memory_embeddings.default_model_for_provider("fake", "fake-memory-embedding-v1") == "fake-memory-embedding-v1"


def test_default_model_for_provider_replaces_fake_default_for_sentence_transformers() -> None:
    assert (
        evaluate_memory_embeddings.default_model_for_provider("sentence-transformers", "fake-memory-embedding-v1")
        == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )


def test_evaluate_model_adds_load_time_and_embedding_dimension() -> None:
    summary = evaluate_memory_embeddings.evaluate_model(
        provider_name="fake",
        model="fake-memory-embedding-v1",
        min_top1_accuracy=0.5,
        min_top3_recall=0.75,
        include_details=False,
    )

    assert summary["provider"] == "fake"
    assert summary["model"] == "fake-memory-embedding-v1"
    assert summary["embedding_dimension"] == 6
    assert summary["load_ms"] >= 0.0
    assert "details" not in summary
    assert summary["passed"] is True


def test_models_for_args_uses_single_resolved_model_when_compare_models_is_empty() -> None:
    args = type(
        "Args",
        (),
        {
            "provider": "sentence-transformers",
            "model": "fake-memory-embedding-v1",
            "compare_models": "",
        },
    )()

    assert evaluate_memory_embeddings.models_for_args(args) == [
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    ]


def test_models_for_args_uses_compare_models_when_provided() -> None:
    args = type(
        "Args",
        (),
        {
            "provider": "sentence-transformers",
            "model": "ignored-model",
            "compare_models": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2,BAAI/bge-m3",
        },
    )()

    assert evaluate_memory_embeddings.models_for_args(args) == [
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "BAAI/bge-m3",
    ]


def test_build_cli_result_returns_single_summary_without_compare_wrapper() -> None:
    summaries = [{"model": "fake-memory-embedding-v1", "passed": True}]

    result = evaluate_memory_embeddings.build_cli_result(
        provider_name="fake",
        summaries=summaries,
        compare_mode=False,
    )

    assert result == summaries[0]


def test_build_cli_result_wraps_multiple_model_summaries() -> None:
    summaries = [
        {"model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "passed": True},
        {"model": "BAAI/bge-m3", "passed": False},
    ]

    result = evaluate_memory_embeddings.build_cli_result(
        provider_name="sentence-transformers",
        summaries=summaries,
        compare_mode=True,
    )

    assert result == {
        "provider": "sentence-transformers",
        "case_count": len(EVALUATION_CASES),
        "model_count": 2,
        "passed": False,
        "models": summaries,
    }


def test_create_sentence_transformers_provider_surfaces_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    class MissingProvider:
        def __init__(self, model: str) -> None:
            raise MemoryEmbeddingUnavailableError("sentence-transformers is not installed")

    monkeypatch.setattr(evaluate_memory_embeddings, "SentenceTransformersMemoryEmbeddingProvider", MissingProvider)

    with pytest.raises(MemoryEmbeddingUnavailableError, match="sentence-transformers is not installed"):
        evaluate_memory_embeddings.create_provider("sentence-transformers", "test-model")
