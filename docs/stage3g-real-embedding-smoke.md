# Stage 3G Real Embedding Smoke and Chinese Retrieval Evaluation

Date: 2026-07-08
Status: VERIFIED PASS

## Scope

Stage 3G adds a repeatable smoke/evaluation script for Stage 3F memory embedding retrieval. It uses fixed Chinese fixture memories and queries to evaluate top-k retrieval quality for the fake provider and optional local `sentence-transformers` provider.

The script does not touch the app database and does not read real chat history or production data.

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

Commands run on 2026-07-08:

- `python -m pytest backend/tests/test_memory_embedding_evaluation.py -q` → 4 passed.
- `python -m pytest backend/tests/test_memory_embedding_evaluation.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q` → 48 passed.
- `python scripts/evaluate_memory_embeddings.py --provider fake --details` → PASS; `top1_accuracy=0.75`, `top3_recall=1.0`, `case_count=8`, `passed=true`.
- `python scripts/evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details` → expected optional-provider environment limitation; exit code 2 with `sentence-transformers is not installed; install it before enabling MEMORY_EMBEDDING_PROVIDER=sentence-transformers`.
- `python -m pytest backend/tests -q` → 305 passed.
- `npm --prefix frontend test -- --run` → 17 files / 152 tests passed.
- `npm --prefix frontend run typecheck` → PASS.
- `npm --prefix frontend run build` → PASS; Vite built 36 modules.

Playwright E2E was not rerun for 3G because this slice adds a backend-side standalone smoke/evaluation script, tests, and docs only; no frontend runtime source changed.

## Result summary

Fake-provider evaluation result:

```json
{
  "provider": "fake",
  "model": "fake-memory-embedding-v1",
  "case_count": 8,
  "top1_accuracy": 0.75,
  "top3_recall": 1.0,
  "passed": true
}
```

Real-provider status:

- Current environment does not have `sentence-transformers` installed.
- The real provider command exits clearly with code 2 and an actionable dependency message.
- This is recorded as an environment limitation, not a Stage 3G product failure.

Terminal note: the Windows terminal output rendered Chinese fixture strings as mojibake during smoke output, but JSON metrics, IDs, and pass/fail status were valid.

## Limitations

This is a smoke fixture, not a production benchmark. Passing it does not choose a production embedding model. The originally suggested isolated dependency/model check was completed later as Stage 3H and recorded in `docs/stage3h-real-embedding-model-evaluation.md`. Further Stage 3 embedding work can compare additional retrieval-oriented models such as `BAAI/bge-m3`, then decide whether to add an optional backend extra and document model cache/resource requirements before production selection.

Stage 4 remains unstarted.
