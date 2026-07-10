# Stage 3J Real Embedding Production Selection

Date: 2026-07-10
Status: VERIFIED PASS

## Scope

Stage 3J compares real embedding model candidates using the fixed synthetic Chinese memory retrieval fixture from Stage 3G/3H. It records model quality, dimensions, load/embedding timing, dependency/cache notes, and a production-selection recommendation.

This remains evaluation evidence only. It does not change default retrieval, does not add mandatory backend dependencies, does not create memories, does not summarize sessions, and does not implement emotional state.

## Non-goals

- No default switch to real embeddings.
- No mandatory `sentence-transformers` dependency in the main backend environment.
- No automatic active memory writes.
- No conversation backfill.
- No session summaries.
- No vector index integration.
- No automatic conflict resolution.
- No Stage 4 emotion state.
- No private chat history, app database, or production memory data.

## Environment

- Main Python command: `python`
- Isolated Python command: `.\.venv-memory-embed\Scripts\python.exe`
- Isolated Python version: `Python 3.12.6`
- `sentence-transformers` version: `5.6.0`
- Backend editable install in isolated environment: PASS
- Main backend environment dependency change: none

Observed model/cache notes:

- Hugging Face Hub requests were unauthenticated. This may reduce rate limits and download speed.
- Windows symlink cache optimization is degraded for Hugging Face cache paths such as `C:\Users\张乐航\.cache\huggingface\hub\models--BAAI--bge-m3` unless Developer Mode or administrator symlink support is enabled. Caching still works, but may use more disk.
- Chinese fixture strings rendered as mojibake in terminal output, matching prior Stage 3G/3H behavior. IDs, metrics, and pass/fail results remained readable and valid.
- Initial bge-m3 background run was stopped after weights loaded but before JSON output. A foreground retry after cache warmup completed successfully.

## Thresholds

- `min_top1_accuracy = 0.5`
- `min_top3_recall = 0.75`

These are smoke thresholds, not sufficient by themselves to justify changing product defaults.

## Fake baseline

Command:

```powershell
python scripts\evaluate_memory_embeddings.py --provider fake --details
```

Observed summary:

```json
{
  "provider": "fake",
  "model": "fake-memory-embedding-v1",
  "case_count": 8,
  "top1_accuracy": 0.75,
  "top3_recall": 1.0,
  "embed_ms": 0.72,
  "passed": true,
  "embedding_dimension": 6,
  "load_ms": 0.0
}
```

Result: PASS.

## MiniLM candidate

Command:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

Observed summary:

```json
{
  "provider": "sentence-transformers",
  "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
  "case_count": 8,
  "top1_accuracy": 0.75,
  "top3_recall": 1.0,
  "embed_ms": 2567.37,
  "passed": true,
  "embedding_dimension": 384,
  "load_ms": 18106.83
}
```

Result: PASS.

Operational notes:

- Lightweight compared with bge-m3.
- Quality matched the fake baseline on aggregate fixture metrics, though the individual top-1 misses differed.
- Suitable as a lightweight future opt-in fallback candidate, but the current 8-case fixture is too small to justify changing defaults.

## bge-m3 candidate

Command:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model BAAI/bge-m3 --details
```

Observed summary:

```json
{
  "provider": "sentence-transformers",
  "model": "BAAI/bge-m3",
  "case_count": 8,
  "top1_accuracy": 1.0,
  "top3_recall": 1.0,
  "embed_ms": 8435.33,
  "passed": true,
  "embedding_dimension": 1024,
  "load_ms": 28846.13
}
```

Result: PASS.

Operational notes:

- bge-m3 improved top-1 accuracy from `0.75` to `1.0` on the fixed 8-case fixture.
- bge-m3 uses larger 1024-dimensional embeddings and had slower embedding time than MiniLM in this local run.
- Initial background run was stopped after loading weights but before JSON output; a foreground retry completed. This suggests bge-m3 is operationally heavier and should not be enabled without explicit opt-in and fallback.

## Batch comparison

Command:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --compare-models sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2,BAAI/bge-m3 --details
```

Observed summary:

```json
{
  "provider": "sentence-transformers",
  "case_count": 8,
  "model_count": 2,
  "passed": true,
  "models": [
    {
      "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
      "top1_accuracy": 0.75,
      "top3_recall": 1.0,
      "embed_ms": 2484.52,
      "passed": true,
      "embedding_dimension": 384,
      "load_ms": 19271.83
    },
    {
      "model": "BAAI/bge-m3",
      "top1_accuracy": 1.0,
      "top3_recall": 1.0,
      "embed_ms": 10782.96,
      "passed": true,
      "embedding_dimension": 1024,
      "load_ms": 9669.89
    }
  ]
}
```

Result: PASS.

## Recommendation

Recommended production-selection outcome for future opt-in work:

- Preferred quality candidate: `BAAI/bge-m3`.
- Lightweight fallback candidate: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
- Always-available fallback: deterministic relevance retrieval.

Rationale:

- Both real candidates passed the existing smoke thresholds.
- bge-m3 materially improved retrieval quality on this fixture: `top1_accuracy=1.0` versus MiniLM `top1_accuracy=0.75`, with both at `top3_recall=1.0`.
- bge-m3 is heavier: larger vectors (`1024` vs `384`) and slower embedding time in local runs. Its initial background evaluation was stopped before output, though a foreground retry succeeded after cache warmup.
- MiniLM remains valuable when a smaller, faster, lower-resource model is preferred.

No Stage 3J default product configuration changes are recommended. The evidence supports bge-m3 as the preferred quality candidate only for a future explicitly opt-in configuration, not as a default switch.

## Conditions before future enablement

Before any later opt-in production configuration uses the recommended model, require:

- an explicit environment/config opt-in;
- fallback to deterministic relevance on provider failure;
- no mandatory dependency added to the default backend install;
- no committed model cache or `.venv-memory-embed` files;
- retrieval limited to confirmed active long-term memories;
- pending/dismissed/archived candidates kept out of chat context;
- a larger evaluation set before claiming production correctness beyond this synthetic fixture;
- clear disk/cache guidance for Hugging Face model files on Windows;
- latency/resource acceptance criteria for local development and any packaged runtime.

## Validation

Commands run:

- `python -m pytest backend/tests/test_memory_embedding_evaluation.py -q` → 14 passed.
- `python -m pytest backend/tests/test_memory_embedding_evaluation.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q` → 59 passed.
- `python scripts\evaluate_memory_embeddings.py --provider fake --details` → PASS; `top1_accuracy=0.75`, `top3_recall=1.0`, `embedding_dimension=6`.
- `.\.venv-memory-embed\Scripts\python.exe --version` → `Python 3.12.6`.
- `.\.venv-memory-embed\Scripts\python.exe -c "import sentence_transformers; print(sentence_transformers.__version__)"` → `5.6.0`.
- `.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details` → PASS; `top1_accuracy=0.75`, `top3_recall=1.0`, `embedding_dimension=384`.
- `.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model BAAI/bge-m3 --details` → PASS on foreground retry; `top1_accuracy=1.0`, `top3_recall=1.0`, `embedding_dimension=1024`.
- `.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --compare-models sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2,BAAI/bge-m3 --details` → PASS; `model_count=2`, `passed=true`.

Frontend tests were skipped because Stage 3J changed only backend evaluation scripts, backend tests, setup helper output, and documentation/status files. No frontend runtime source changed.

## Stage boundary check

Stage 3J did not implement session summaries, automatic active memory writes, vector indexes, automatic conflict resolution, or Stage 4 emotion state.

The evaluation used fixed synthetic fixture memories and queries only. It did not read app databases, chat history, private user memories, or production data.
