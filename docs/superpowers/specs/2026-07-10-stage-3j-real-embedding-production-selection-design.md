# Stage 3J Real Embedding Production Selection Design

Date: 2026-07-10
Status: Design recorded; pending user review before implementation planning

## Context

Stage 3 is the current project phase: long-term memory. Stages 1 and 2 are closed, Stage 4 emotion state is not started, and Stage 3A–3I are complete.

Relevant prior work:

- Stage 3F added opt-in memory embedding retrieval with a fake provider and an optional lazy `sentence-transformers` provider. Defaults remain deterministic relevance retrieval with embedding disabled.
- Stage 3G added a repeatable Chinese fixture evaluation script for memory embedding retrieval. It passed with the fake provider and clearly reported missing `sentence-transformers` as an optional-provider environment limitation.
- Stage 3H created an isolated `.venv-memory-embed` environment and ran the existing real-provider evaluation with `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. MiniLM passed the smoke thresholds: `top1_accuracy=0.75`, `top3_recall=1.0`, `case_count=8`.
- Stage 3I added opt-in LLM memory-candidate extraction while preserving user confirmation and keeping pending candidates out of chat context.

Stage 3J should continue the embedding path by turning the Stage 3H real-model smoke into a production-selection evaluation. It should produce enough evidence to decide which real embedding model is the recommended production candidate, without yet changing app defaults or weakening memory confirmation boundaries.

## Goals

- Compare multiple real embedding model candidates using the existing Stage 3G/3H evaluation path.
- Record quality metrics, loading time, embedding time, vector dimension, dependency/cache requirements, and Windows-specific operational notes.
- Produce a production selection recommendation: preferred model, fallback model, and conditions required before enabling it in real app usage.
- Keep embedding retrieval opt-in, auditable, and reversible.
- Preserve the separation between active long-term memories, pending candidates, dismissed/archived candidates, chat history, and future session summaries.

## Non-goals

- No default switch to real embeddings.
- No mandatory `sentence-transformers` dependency in the main backend environment.
- No automatic active memory writes.
- No conversation backfill.
- No session summaries.
- No vector index integration such as sqlite-vec, Faiss, Chroma, LanceDB, or Qdrant.
- No automatic conflict resolution.
- No Stage 4 emotion state, relationship scoring, or emotional expression strategy.
- No use of private chat history or production data.

## Recommended approach

Use the current isolated evaluation setup from Stage 3H and extend the evaluation script/documentation just enough to compare candidate models consistently.

This approach keeps the product code path stable while generating better production evidence than a single MiniLM smoke. It avoids the risk of switching app behavior based on one small fixture and keeps all real-model dependency work outside the default backend environment.

### Candidate models

Evaluate these candidates first:

1. `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
   - Already validated in Stage 3H.
   - Small, multilingual, 384-dimensional embeddings.
   - Useful as the lightweight baseline and fallback candidate.

2. `BAAI/bge-m3`
   - Stronger retrieval-oriented multilingual model.
   - Larger and likely slower/heavier than MiniLM.
   - Important candidate for Chinese long-term memory retrieval quality.

Optional later candidates may be added only if the first two produce inconclusive results. They should not block the Stage 3J minimal loop.

### Evaluation dimensions

For each candidate, record:

- provider name;
- model name;
- embedding dimension;
- fixture case count;
- `top1_accuracy`;
- `top3_recall`;
- load time in milliseconds;
- embedding time in milliseconds;
- whether the existing thresholds passed;
- observed disk/cache/download issues;
- observed Windows warnings;
- whether the model can run in `.venv-memory-embed` without touching the main backend environment.

### Initial pass thresholds

Keep the Stage 3G smoke thresholds as the minimum pass/fail gate:

- `top1_accuracy >= 0.5`
- `top3_recall >= 0.75`

For production recommendation, prefer a candidate only if it also satisfies the qualitative operational gate:

- can be installed and loaded in the isolated environment;
- has acceptable first-load and per-query embedding times for local development;
- does not require committing large model files or cache directories;
- has a clear fallback path to deterministic relevance retrieval;
- does not change confirmed-memory-only retrieval boundaries.

If `BAAI/bge-m3` improves quality but is much heavier, the Stage 3J recommendation may choose it as the preferred quality candidate while keeping MiniLM as a lightweight fallback. If both models tie on the current fixture, the recommendation should say the fixture is too small to justify a production switch and require a larger evaluation before default enablement.

## Data and privacy boundaries

Stage 3J uses fixed synthetic Chinese fixture memories and queries only. It must not read local app databases, chat history, personal user data, or production memories.

The evaluation result is evidence about retrieval behavior on controlled fixtures, not proof that real user memory retrieval is correct in all cases.

## Product behavior after 3J

After Stage 3J completes, default product behavior should remain unchanged:

```env
MEMORY_RETRIEVAL_MODE=relevance
MEMORY_EMBEDDING_ENABLED=false
```

Real embeddings remain opt-in and reversible through configuration. Retrieval failures must continue to fall back to deterministic relevance retrieval so chat remains usable.

Stage 3J may recommend a future production configuration, but it must not enable that configuration by default.

## Implementation outline for the later plan

The later implementation plan should keep changes small:

1. Inspect the existing Stage 3G evaluation script and Stage 3H setup helper.
2. Add a way to evaluate and record multiple candidate models without duplicating script logic.
3. Ensure the script reports embedding dimension and per-model timing consistently.
4. Run the fake baseline and real candidates from the isolated `.venv-memory-embed` interpreter.
5. Write an evidence report at `docs/stage3j-real-embedding-production-selection.md`.
6. Update `CLAUDE.md` only after evidence is recorded, marking 3J as completed if validation passes and preserving Stage 4 as unstarted.

## Expected files

Likely modify or create during implementation:

- `scripts/evaluate_memory_embeddings.py` — only if needed to support repeated candidate evaluation or dimension reporting.
- `backend/tests/test_memory_embedding_evaluation.py` — only if script behavior changes.
- `docs/stage3j-real-embedding-production-selection.md` — implementation evidence and recommendation.
- `docs/superpowers/plans/2026-07-10-stage-3j-real-embedding-production-selection.md` — implementation plan.
- `CLAUDE.md` — status update after validation, if 3J is completed.

This design document itself is recorded at:

- `docs/superpowers/specs/2026-07-10-stage-3j-real-embedding-production-selection-design.md`

## Validation plan for implementation

Run at minimum:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q
```

Run fake baseline:

```powershell
python scripts\evaluate_memory_embeddings.py --provider fake --details
```

Run isolated real evaluations:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model BAAI/bge-m3 --details
```

If implementation changes backend Python source beyond the standalone script/tests, run:

```powershell
python -m pytest backend/tests -q
```

Frontend tests are not required unless frontend runtime source changes.

## Risks and mitigations

- Risk: `BAAI/bge-m3` download or load is slow, blocked, or too large.
  - Mitigation: record the exact limitation; keep MiniLM and deterministic relevance as fallback evidence.

- Risk: the current 8-case fixture is too small to distinguish candidates.
  - Mitigation: state that no production default switch is justified; recommend a larger later benchmark rather than overstating results.

- Risk: real-model dependencies pollute the main backend environment.
  - Mitigation: use `.venv-memory-embed` only and do not add mandatory dependencies.

- Risk: model cache or virtual environment files are accidentally committed.
  - Mitigation: keep `.venv-memory-embed/` ignored and document external model cache locations.

- Risk: scope creep into automatic memory writes or session summaries.
  - Mitigation: keep Stage 3J strictly about retrieval model selection; do not change write/confirmation behavior.

## Design decisions for implementation planning

- Stage 3J will use the existing 8-case fixture set for the minimal comparison loop. It will not expand the benchmark unless MiniLM and bge-m3 results are inconclusive or the existing script cannot compare them fairly.
- Stage 3J will record first-load time, per-query embedding time, and embedding dimension as evidence, but it will not set a hard latency cutoff yet. The evidence report must state whether the observed latency feels acceptable for opt-in local development.
- If MiniLM and bge-m3 both pass and produce similar retrieval quality on the current fixture, the recommendation will prefer MiniLM as the lightweight default candidate for a future opt-in production configuration and record bge-m3 as the higher-quality candidate requiring larger-benchmark justification.
- If bge-m3 materially improves retrieval quality without unacceptable setup/runtime cost, the recommendation will list bge-m3 as the preferred quality candidate and MiniLM as the lightweight fallback.
- If either real model fails to install, download, load, or run in the isolated environment, Stage 3J will record the exact failure and will not recommend enabling that model.
