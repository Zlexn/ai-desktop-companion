# Stage 3G Real Embedding Smoke and Chinese Retrieval Evaluation Design

Date: 2026-07-08
Status: Recommended design selected by user default; ready for implementation planning

## Context

The project is in Stage 3: long-term memory. Stage 3F added opt-in local embedding retrieval for confirmed active long-term memories. The first 3F implementation deliberately uses a deterministic fake embedding provider for automated tests and leaves real `sentence-transformers` usage optional and lazy-loaded.

The next smallest useful loop is not another product feature. It is a real-provider smoke and a small Chinese retrieval evaluation that answers whether the 3F embedding boundary can work with a local multilingual embedding model on this Windows development machine.

A quick environment check on 2026-07-08 found that the current Python environment does not have `sentence_transformers` installed. Therefore 3G must keep real-model smoke optional and must not make normal backend tests depend on a large model download.

Web checks found two practical candidates:

- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`: multilingual, about 0.1B parameters, 384-dimensional embeddings, and documented `SentenceTransformer(...)` usage. This is the recommended first smoke model because it is comparatively small.
- `BAAI/bge-m3`: retrieval-oriented, supports dense/sparse/multi-vector retrieval, more than 100 languages, 1024-dimensional dense embeddings, long inputs up to 8192 tokens, and documented sentence-transformers usage. This is a stronger future candidate but heavier for a first smoke.

Sources:

- https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
- https://huggingface.co/BAAI/bge-m3

This design stays within Stage 3. It does not implement LLM-based memory extraction, session summaries, automatic memory writing, sqlite-vec, or Stage 4 emotion state.

## Goals

- Add a repeatable local script to evaluate memory embedding retrieval on Chinese fixture data.
- Exercise the existing 3F provider boundary with both fake and optional real sentence-transformers providers.
- Report retrieval quality metrics and basic latency/load timing.
- Keep default tests dependency-free and deterministic.
- Document the exact command and outcome so a future real model can be selected using evidence.

## Non-goals

- No production embedding model selection.
- No automatic model download during normal tests.
- No new mandatory backend dependency.
- No vector index or sqlite-vec integration.
- No LLM-based memory candidate extraction.
- No session-summary storage.
- No Stage 4 mood, trust, concern, distance, irritation, formality, relationship score, or emotional expression strategy.
- No use of private chat history or production data.

## Recommended approach

Create a small standalone evaluation module and script:

- `scripts/evaluate_memory_embeddings.py`
- optional test helper functions inside the same script or a small importable module if needed;
- `backend/tests/test_memory_embedding_evaluation.py` for deterministic fake-provider tests.

The script should not require a running FastAPI server or a real application database. It should use in-memory fixture records that resemble long-term memory content. This keeps privacy risk low and makes the smoke repeatable.

## Evaluation dataset

Use a small fixed Chinese fixture set. Each memory has:

- `id`
- `content`
- `memory_type`

Suggested memories:

1. `pref_tea`: `用户喜欢红茶。`
2. `pref_coffee`: `用户不喜欢咖啡。`
3. `pref_language`: `用户偏好简洁中文回复。`
4. `fact_city`: `用户住在上海。`
5. `fact_job`: `用户的职业是后端工程师。`
6. `goal_pet`: `用户的目标是完成本地 AI 桌宠项目。`
7. `goal_exam`: `用户正在准备日语考试。`
8. `event_trip`: `用户去年冬天去过北海道。`
9. `relationship_help`: `用户希望角色在项目推进时多提醒风险。`

Suggested queries:

1. `我平时爱喝什么？` expects `pref_tea`.
2. `我不爱喝哪种饮料？` expects `pref_coffee`.
3. `你回复我时语言上有什么偏好？` expects `pref_language`.
4. `我现在住在哪个城市？` expects `fact_city`.
5. `我的工作是什么？` expects `fact_job`.
6. `我的长期项目目标是什么？` expects `goal_pet`.
7. `我最近在准备什么考试？` expects `goal_exam`.
8. `我希望你在推进项目时怎么帮助我？` expects `relationship_help`.

This is not a benchmark. It is a smoke-quality fixture that catches obvious failures before integrating real embeddings into app-level retrieval tests.

## Metrics

The script should output JSON by default:

```json
{
  "provider": "sentence-transformers",
  "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
  "case_count": 8,
  "top1_accuracy": 0.875,
  "top3_recall": 1.0,
  "load_ms": 1234.5,
  "embed_ms": 56.7,
  "passed": true,
  "thresholds": {"min_top1_accuracy": 0.5, "min_top3_recall": 0.75}
}
```

Also include per-case details when `--details` is passed:

```json
{
  "query": "我平时爱喝什么？",
  "expected_id": "pref_tea",
  "top_ids": ["pref_tea", "pref_language", "goal_pet"],
  "hit_top1": true,
  "hit_top3": true
}
```

Recommended pass thresholds for first smoke:

- fake provider: exact deterministic expectations in tests;
- real provider: `top1_accuracy >= 0.5` and `top3_recall >= 0.75`.

The real thresholds are intentionally modest. Passing them does not mean production readiness; failing them means the model or prompt fixtures need investigation before use.

## CLI behavior

Supported commands:

```powershell
python scripts/evaluate_memory_embeddings.py --provider fake --details
python scripts/evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
python scripts/evaluate_memory_embeddings.py --provider sentence-transformers --model BAAI/bge-m3 --details
```

Default provider should be `fake` so the script can run without optional dependencies.

If `--provider sentence-transformers` is requested and the dependency is missing, the script should exit non-zero with a clear message:

```text
sentence-transformers is not installed. Install optional embedding dependencies before running real embedding smoke.
```

Normal backend tests should not invoke the real provider.

## Implementation boundaries

The script may import the existing providers from `app.services.memory_embedding_service` to avoid duplicating provider logic. Because the script lives outside `backend/`, it should add `backend` to `sys.path` at runtime in the same style as existing standalone scripts if needed.

The script should implement evaluation math locally:

- embed all memory contents;
- embed all query texts;
- compute cosine similarity;
- rank memories per query;
- compute top1 accuracy and top3 recall;
- measure model/provider load time and embedding/evaluation time with `time.perf_counter()`.

Do not persist embeddings to the app database in this smoke. 3F database integration is already verified separately.

## Testing plan

Add deterministic tests for:

- fixture case count and unique IDs;
- cosine/ranking logic;
- fake provider evaluation returns JSON-compatible summary;
- fake provider passes deterministic thresholds;
- missing real dependency path is handled clearly when `sentence_transformers` is unavailable.

The missing dependency test must not require uninstalling packages. It can monkeypatch `sys.modules` or monkeypatch provider creation in the script-level function.

## Documentation updates

After implementation and verification:

- Create `docs/stage3g-real-embedding-smoke.md` with commands and results.
- Update `CLAUDE.md` only after validation passes.
- Update `README.md` with a short optional smoke command if useful.

## Risks and mitigations

- Risk: model download is slow or blocked.
  - Mitigation: keep real provider smoke optional and record missing dependency/network as a limitation rather than failing the feature.

- Risk: fake provider gives a false sense of quality.
  - Mitigation: clearly separate fake-provider plumbing tests from real-provider smoke results.

- Risk: small fixture overfits.
  - Mitigation: document that this is a smoke, not production evaluation.

- Risk: accidentally crossing into memory write automation.
  - Mitigation: this slice uses fixed fixture records and does not read chat history or write app memories.

## Future work after 3G

If real smoke passes, the next Stage 3 tasks can be:

1. Choose and document a default local embedding model for manual opt-in.
2. Add optional app-level real embedding smoke against a temporary SQLite database.
3. Implement LLM-based user-confirmed memory candidate extraction.
4. Design independent session-summary storage.
