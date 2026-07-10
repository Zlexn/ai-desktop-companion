# Stage 3H Isolated Real Embedding Model Evaluation

Date: 2026-07-09
Status: VERIFIED PASS

## Scope

Stage 3H creates and uses the project-local `.venv-memory-embed` environment to run the Stage 3G Chinese memory retrieval evaluation with a real `sentence-transformers` model.

This is an isolated evaluation path only. It does not change product defaults, add mandatory backend dependencies, create memories, summarize sessions, or implement emotional state.

## Non-goals

- No LLM-based memory extraction.
- No automatic memory writes from chat history.
- No session summaries.
- No Stage 4 emotion system.
- No vector index integration.
- No production embedding model selection.

## Environment

- Environment path: `.venv-memory-embed`
- Isolated Python command: `.\.venv-memory-embed\Scripts\python.exe`
- Python version: `3.12.6`
- `sentence-transformers` import: `5.6.0`
- Backend editable install in isolated environment: PASS

Setup note: the planned helper command using `-ExecutionPolicy Bypass` was blocked by the Claude Code auto-mode classifier because it bypasses PowerShell execution policy. The same setup steps from `scripts/setup_memory_embedding_env.ps1` were executed directly without changing execution policy:

```powershell
$VenvPython = ".\.venv-memory-embed\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) { python -m venv ".venv-memory-embed" }
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e "backend"
& $VenvPython -m pip install sentence-transformers
& $VenvPython -c "import sentence_transformers; print(sentence_transformers.__version__)"
```

Observed result: PASS; import printed `5.6.0`.

## Fake baseline

Command:

```powershell
python scripts\evaluate_memory_embeddings.py --provider fake --details
```

Observed JSON summary:

```json
{
  "provider": "fake",
  "model": "fake-memory-embedding-v1",
  "case_count": 8,
  "top1_accuracy": 0.75,
  "top3_recall": 1.0,
  "embed_ms": 0.52,
  "passed": true,
  "load_ms": 0.0
}
```

## Real MiniLM evaluation

Command:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

Observed JSON summary:

```json
{
  "provider": "sentence-transformers",
  "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
  "case_count": 8,
  "top1_accuracy": 0.75,
  "top3_recall": 1.0,
  "embed_ms": 1214.05,
  "passed": true,
  "load_ms": 29634.44
}
```

Thresholds:

- `min_top1_accuracy = 0.5`
- `min_top3_recall = 0.75`

Result: PASS.

Runtime warnings observed:

- Hugging Face Hub request was unauthenticated; this may reduce rate limits/download speed.
- Hugging Face Hub symlink cache optimization is degraded on this Windows machine unless Developer Mode or administrator symlink support is enabled. Caching still works, but may use more disk.
- Terminal output rendered Chinese fixture strings as mojibake, matching the Stage 3G terminal behavior. Metrics, IDs, and pass/fail status remained valid.

## Validation

Commands run on 2026-07-09:

- `python scripts\evaluate_memory_embeddings.py --provider fake --details` → PASS; `top1_accuracy=0.75`, `top3_recall=1.0`, `case_count=8`, `passed=true`.
- isolated setup/import commands listed above → PASS; `sentence-transformers=5.6.0`.
- `.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details` → PASS; `top1_accuracy=0.75`, `top3_recall=1.0`, `case_count=8`, `passed=true`.
- `python -m pytest backend/tests/test_memory_embedding_evaluation.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q` → 48 passed.
- `python -m pytest backend/tests -q` → 305 passed.

Frontend tests were skipped because Stage 3H changed only ignore/setup/docs/status files and no frontend runtime source.

## Limitations

This is a fixed-fixture smoke/evaluation, not a production benchmark. Passing it does not select a production embedding model, does not switch app defaults to real embeddings, and does not add `sentence-transformers` as a mandatory backend dependency.

Current next Stage 3 task: **3I User-Confirmed LLM Memory Candidate Extraction**. It should add an opt-in LLM candidate extraction path while preserving user confirmation and keeping pending candidates out of chat context.

Later Stage 3 embedding work can compare this MiniLM result against larger retrieval-oriented models such as `BAAI/bge-m3`, decide whether to add an optional backend extra, and document model cache/resource requirements before production selection.

Stage 4 remains unstarted.
