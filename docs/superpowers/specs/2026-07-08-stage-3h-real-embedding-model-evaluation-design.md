# Stage 3H Isolated Real Embedding Model Evaluation Design

Date: 2026-07-08
Status: Recommended design selected by user default; ready for implementation planning

## Context

Stage 3F added opt-in memory embedding retrieval with a fake provider and an optional lazy `sentence-transformers` provider. Stage 3G added `scripts/evaluate_memory_embeddings.py`, a standalone Chinese fixture smoke/evaluation script. The fake provider passed the smoke, while the current main Python environment reported that `sentence-transformers` was not installed.

The next smallest useful loop is to create an isolated environment for real embedding dependencies and run the existing 3G evaluation script against a small multilingual model. This should produce real top-k retrieval evidence without changing product defaults or adding mandatory dependencies.

This design stays within Stage 3. It does not implement LLM-based memory extraction, session summaries, automatic memory writes, vector index integration, or Stage 4 emotion state.

## Goals

- Create an isolated environment for real embedding smoke/evaluation.
- Install only the dependencies needed to run the existing `SentenceTransformersMemoryEmbeddingProvider` path.
- Run the Stage 3G Chinese fixture evaluation with a lightweight multilingual model.
- Record exact success/failure, retrieval metrics, timing, and environment limitations.
- Keep the main backend environment and product defaults unchanged.

## Non-goals

- No production embedding model selection.
- No default switch to real embeddings.
- No mandatory backend dependency change.
- No sqlite-vec, Faiss, Chroma, LanceDB, or other vector index integration.
- No LLM-based memory candidate extraction.
- No session-summary storage.
- No Stage 4 mood, trust, concern, distance, irritation, formality, relationship score, or emotional expression strategy.
- No use of private chat history or production data.

## Recommended approach

Use a project-local isolated virtual environment named `.venv-memory-embed`.

Add `.venv-memory-embed/` to `.gitignore` so large dependencies and model-related local files are never committed. Do not add `sentence-transformers` to the main backend dependencies yet.

Add a small setup helper:

- `scripts/setup_memory_embedding_env.ps1`

The helper should:

1. create `.venv-memory-embed` if missing;
2. upgrade pip;
3. install the backend package in editable mode;
4. install `sentence-transformers`;
5. print the exact evaluation command.

This helper is convenience only. The evidence command should still be a plain Python invocation using the isolated interpreter.

## First model

Evaluate exactly one real model in the required path:

```text
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

Rationale:

- multilingual model;
- comparatively small, around 0.1B parameters;
- 384-dimensional embeddings;
- documented `SentenceTransformer(...)` usage;
- suitable for validating the 3F provider boundary before evaluating heavier models.

`BAAI/bge-m3` remains a later candidate. It is stronger and retrieval-oriented but larger, 1024-dimensional, and more likely to create a long-running download/load task. It should not block this minimal loop.

## Evaluation command

After setup, run:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

Also keep the fake baseline:

```powershell
python scripts\evaluate_memory_embeddings.py --provider fake --details
```

## Pass/fail interpretation

A successful real run should output JSON including:

- `provider = sentence-transformers`
- `model = sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- `case_count = 8`
- `top1_accuracy`
- `top3_recall`
- `load_ms`
- `embed_ms`
- `passed`

The initial real thresholds remain Stage 3G's smoke thresholds:

- `top1_accuracy >= 0.5`
- `top3_recall >= 0.75`

If installation, download, import, or model loading fails, record the exact failure as an environment limitation. Do not claim real-provider PASS. The Stage 3H task can still complete as an environment-preparation attempt only if the failure is documented and existing automated tests remain passing.

## Files

Modify:

- `.gitignore`: add `.venv-memory-embed/`.
- `README.md`: add optional isolated real embedding smoke command.
- `CLAUDE.md`: update only after validation/evidence is recorded.

Create:

- `scripts/setup_memory_embedding_env.ps1`
- `docs/stage3h-real-embedding-model-evaluation.md`
- `docs/superpowers/plans/2026-07-08-stage-3h-real-embedding-model-evaluation.md`

No product source files should be changed unless implementation reveals a defect in the existing 3G script.

## Validation plan

1. Run existing Stage 3G tests:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py -q
```

2. Run fake baseline:

```powershell
python scripts\evaluate_memory_embeddings.py --provider fake --details
```

3. Create/setup isolated environment:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_memory_embedding_env.ps1
```

4. Run real evaluation:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

5. Run focused backend regression:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q
```

6. Run full backend tests if implementation touched any Python source beyond script/docs:

```powershell
python -m pytest backend/tests -q
```

Frontend tests are not required for this slice unless frontend files change.

## Documentation requirements

`docs/stage3h-real-embedding-model-evaluation.md` must record:

- environment path;
- Python version inside isolated env;
- installed dependency outcome;
- fake baseline result;
- real model command and exact result;
- whether thresholds passed;
- limitations;
- confirmation that Stage 4 remains unstarted.

## Risks and mitigations

- Risk: dependency install is slow or fails.
  - Mitigation: use an isolated environment and record exact failure without changing product behavior.

- Risk: model download is blocked.
  - Mitigation: record as environment limitation; do not claim real PASS.

- Risk: large dependencies accidentally enter git.
  - Mitigation: add `.venv-memory-embed/` to `.gitignore` before setup.

- Risk: scope creep into product retrieval behavior.
  - Mitigation: do not change app defaults or product code in this slice.

## Future work after 3H

If MiniLM real smoke passes, a later Stage 3 task can compare it against `BAAI/bge-m3` and decide whether to add a documented optional backend extra or model cache instructions.
