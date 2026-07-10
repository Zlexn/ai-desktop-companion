# Stage 3J Real Embedding Production Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compare real multilingual embedding candidates on the existing Stage 3 Chinese memory retrieval fixture and record a production-selection recommendation without changing product defaults.

**Architecture:** Keep app retrieval behavior unchanged and extend only the standalone evaluation path. The CLI remains backward-compatible for one model, gains a batch comparison mode for multiple `sentence-transformers` models, reports embedding dimensions consistently, and writes evidence in a Stage 3J document after real commands run in `.venv-memory-embed`.

**Tech Stack:** Python 3.12, pytest, PowerShell, `sentence-transformers`, existing FastAPI backend package, existing Stage 3 memory embedding provider abstraction.

---

## Scope and constraints

This plan implements Stage 3J only.

It must not implement:

- a default switch to real embeddings;
- mandatory `sentence-transformers` dependency in the main backend environment;
- automatic memory writes;
- conversation backfill;
- session summaries;
- vector index infrastructure;
- automatic conflict resolution;
- Stage 4 emotion state.

Use only the fixed synthetic Chinese fixture in `scripts/evaluate_memory_embeddings.py`. Do not read app databases, chat history, user memory stores, or production data.

The current project directory is not a git repository according to `git status`; commit steps are therefore replaced with explicit checkpoint/diff review steps. If the project is later initialized as git before execution, make the listed commits at the same checkpoints.

## File structure

Modify:

- `scripts/evaluate_memory_embeddings.py`
  - Add constants for default model names.
  - Add helpers for embedding dimension measurement and comma-separated model lists.
  - Add a reusable per-model evaluation runner.
  - Keep the existing single-model JSON output shape compatible, while adding `embedding_dimension`.
  - Add optional `--compare-models` batch output for Stage 3J.

- `backend/tests/test_memory_embedding_evaluation.py`
  - Add focused tests for dimension reporting, model-list parsing, default model resolution, single-run summaries, and batch output wrapping.
  - Update the existing setup helper test to assert that Stage 3J prints the bge-m3 command.

- `scripts/setup_memory_embedding_env.ps1`
  - Keep the isolated setup unchanged, but print both MiniLM and bge-m3 Stage 3J evaluation commands.

- `CLAUDE.md`
  - After validation and evidence are complete, mark 3J complete, update the Stage 3 status text, and preserve Stage 4 as unstarted.

Create:

- `docs/stage3j-real-embedding-production-selection.md`
  - Record fake baseline, MiniLM, bge-m3 results or exact environment limitations.
  - Include production recommendation, fallback model, and conditions before any future opt-in production enablement.

No frontend runtime files should change.

---

### Task 1: Evaluation helper tests for dimensions and model lists

**Files:**
- Modify: `backend/tests/test_memory_embedding_evaluation.py`
- Modify: `scripts/evaluate_memory_embeddings.py`

- [ ] **Step 1: Add failing tests for dimension and compare-model parsing**

Append these tests to `backend/tests/test_memory_embedding_evaluation.py` after `test_fake_provider_evaluation_summary_is_json_compatible_and_passes`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py::test_measure_embedding_dimension_uses_provider_vector_length backend/tests/test_memory_embedding_evaluation.py::test_split_compare_models_trims_and_drops_empty_items backend/tests/test_memory_embedding_evaluation.py::test_split_compare_models_returns_empty_list_for_blank_value -q
```

Expected: FAIL because `measure_embedding_dimension` and `split_compare_models` do not exist yet.

- [ ] **Step 3: Implement the helper functions**

In `scripts/evaluate_memory_embeddings.py`, add these constants after the imports and before `ROOT = ...`:

```python
DEFAULT_FAKE_MODEL = "fake-memory-embedding-v1"
DEFAULT_SENTENCE_TRANSFORMERS_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIMENSION_PROBE_TEXT = "记忆检索维度测试"
```

Then add these helper functions after `cosine_similarity`:

```python
def measure_embedding_dimension(provider: MemoryEmbeddingProvider) -> int:
    return len(provider.embed_text(DIMENSION_PROBE_TEXT))


def split_compare_models(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py::test_measure_embedding_dimension_uses_provider_vector_length backend/tests/test_memory_embedding_evaluation.py::test_split_compare_models_trims_and_drops_empty_items backend/tests/test_memory_embedding_evaluation.py::test_split_compare_models_returns_empty_list_for_blank_value -q
```

Expected: `3 passed`.

- [ ] **Step 5: Checkpoint review**

Run:

```powershell
git diff -- scripts/evaluate_memory_embeddings.py backend/tests/test_memory_embedding_evaluation.py
```

Expected if git is unavailable in this project: command reports that this is not a git repository. In that case, manually inspect the two changed files before continuing.

---

### Task 2: Single-model summary reports embedding dimension

**Files:**
- Modify: `backend/tests/test_memory_embedding_evaluation.py`
- Modify: `scripts/evaluate_memory_embeddings.py`

- [ ] **Step 1: Add failing tests for per-model summary helpers**

Append these tests to `backend/tests/test_memory_embedding_evaluation.py` after the tests from Task 1:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py::test_default_model_for_provider_keeps_fake_default backend/tests/test_memory_embedding_evaluation.py::test_default_model_for_provider_replaces_fake_default_for_sentence_transformers backend/tests/test_memory_embedding_evaluation.py::test_evaluate_model_adds_load_time_and_embedding_dimension -q
```

Expected: FAIL because `default_model_for_provider` and `evaluate_model` do not exist yet.

- [ ] **Step 3: Implement default-model and per-model runner helpers**

In `scripts/evaluate_memory_embeddings.py`, replace the default model literal in `parse_args` later with `DEFAULT_FAKE_MODEL`, but first add these functions after `create_provider`:

```python
def default_model_for_provider(provider_name: str, model: str) -> str:
    if provider_name == "sentence-transformers" and model == DEFAULT_FAKE_MODEL:
        return DEFAULT_SENTENCE_TRANSFORMERS_MODEL
    return model


def evaluate_model(
    *,
    provider_name: str,
    model: str,
    min_top1_accuracy: float,
    min_top3_recall: float,
    include_details: bool,
) -> dict[str, Any]:
    resolved_model = default_model_for_provider(provider_name, model)
    load_started = time.perf_counter()
    provider = create_provider(provider_name, resolved_model)
    if provider_name == "sentence-transformers":
        provider.embed_text("加载测试")
    load_ms = (time.perf_counter() - load_started) * 1000.0
    summary = evaluate_provider(
        provider=provider,
        min_top1_accuracy=min_top1_accuracy,
        min_top3_recall=min_top3_recall,
        include_details=include_details,
    )
    summary["embedding_dimension"] = measure_embedding_dimension(provider)
    summary["load_ms"] = round(load_ms, 2)
    return summary
```

Then update `parse_args` so the `--model` line uses the constant:

```python
parser.add_argument("--model", default=DEFAULT_FAKE_MODEL)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py::test_default_model_for_provider_keeps_fake_default backend/tests/test_memory_embedding_evaluation.py::test_default_model_for_provider_replaces_fake_default_for_sentence_transformers backend/tests/test_memory_embedding_evaluation.py::test_evaluate_model_adds_load_time_and_embedding_dimension -q
```

Expected: `3 passed`.

- [ ] **Step 5: Run existing fake summary test**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py::test_fake_provider_evaluation_summary_is_json_compatible_and_passes -q
```

Expected: PASS. This test calls `evaluate_provider` directly, so it should remain compatible and should not require `embedding_dimension`.

---

### Task 3: Batch comparison CLI for Stage 3J candidates

**Files:**
- Modify: `backend/tests/test_memory_embedding_evaluation.py`
- Modify: `scripts/evaluate_memory_embeddings.py`

- [ ] **Step 1: Add failing tests for compare-model resolution and result wrapping**

Append these tests to `backend/tests/test_memory_embedding_evaluation.py` after the Task 2 tests:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py::test_models_for_args_uses_single_resolved_model_when_compare_models_is_empty backend/tests/test_memory_embedding_evaluation.py::test_models_for_args_uses_compare_models_when_provided backend/tests/test_memory_embedding_evaluation.py::test_build_cli_result_returns_single_summary_without_compare_wrapper backend/tests/test_memory_embedding_evaluation.py::test_build_cli_result_wraps_multiple_model_summaries -q
```

Expected: FAIL because `models_for_args` and `build_cli_result` do not exist yet.

- [ ] **Step 3: Implement model resolution and CLI result wrapping**

In `scripts/evaluate_memory_embeddings.py`, add these helpers after `evaluate_model`:

```python
def models_for_args(args: argparse.Namespace) -> list[str]:
    compare_models = split_compare_models(args.compare_models)
    if compare_models:
        return compare_models
    return [default_model_for_provider(args.provider, args.model)]


def build_cli_result(*, provider_name: str, summaries: list[dict[str, Any]], compare_mode: bool) -> dict[str, Any]:
    if not compare_mode and len(summaries) == 1:
        return summaries[0]
    return {
        "provider": provider_name,
        "case_count": len(EVALUATION_CASES),
        "model_count": len(summaries),
        "passed": all(summary["passed"] for summary in summaries),
        "models": summaries,
    }
```

Update `parse_args` to add the new optional flag after the `--model` argument:

```python
parser.add_argument(
    "--compare-models",
    default="",
    help="Comma-separated model names to evaluate in one run. Overrides --model when provided.",
)
```

- [ ] **Step 4: Replace `main` with batch-aware logic**

Replace the entire current `main` function in `scripts/evaluate_memory_embeddings.py` with:

```python
def main() -> int:
    args = parse_args()
    summaries: list[dict[str, Any]] = []
    try:
        for model in models_for_args(args):
            summaries.append(
                evaluate_model(
                    provider_name=args.provider,
                    model=model,
                    min_top1_accuracy=args.min_top1_accuracy,
                    min_top3_recall=args.min_top3_recall,
                    include_details=args.details,
                )
            )
    except MemoryEmbeddingUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result = build_cli_result(
        provider_name=args.provider,
        summaries=summaries,
        compare_mode=bool(split_compare_models(args.compare_models)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1
```

This keeps existing commands compatible:

```powershell
python scripts\evaluate_memory_embeddings.py --provider fake --details
```

It also adds Stage 3J batch comparison:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --compare-models sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2,BAAI/bge-m3 --details
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py::test_models_for_args_uses_single_resolved_model_when_compare_models_is_empty backend/tests/test_memory_embedding_evaluation.py::test_models_for_args_uses_compare_models_when_provided backend/tests/test_memory_embedding_evaluation.py::test_build_cli_result_returns_single_summary_without_compare_wrapper backend/tests/test_memory_embedding_evaluation.py::test_build_cli_result_wraps_multiple_model_summaries -q
```

Expected: `4 passed`.

- [ ] **Step 6: Run fake CLI smoke and check JSON shape**

Run:

```powershell
python scripts\evaluate_memory_embeddings.py --provider fake --details
```

Expected: exit code 0 and JSON with a single-model shape including these top-level fields:

```json
{
  "provider": "fake",
  "model": "fake-memory-embedding-v1",
  "case_count": 8,
  "top1_accuracy": 0.75,
  "top3_recall": 1.0,
  "embed_ms": 0.0,
  "passed": true,
  "thresholds": {
    "min_top1_accuracy": 0.5,
    "min_top3_recall": 0.75
  },
  "details": [],
  "embedding_dimension": 6,
  "load_ms": 0.0
}
```

`embed_ms` and `load_ms` may be different non-negative numbers; `details` should contain the existing per-query detail entries when `--details` is used.

---

### Task 4: Setup helper prints both Stage 3J candidate commands

**Files:**
- Modify: `backend/tests/test_memory_embedding_evaluation.py`
- Modify: `scripts/setup_memory_embedding_env.ps1`

- [ ] **Step 1: Update helper test to require bge-m3 command**

In `backend/tests/test_memory_embedding_evaluation.py`, update `test_stage3h_setup_helper_uses_isolated_memory_embedding_env` by adding these assertions after the existing MiniLM command assertion:

```python
    assert "BAAI/bge-m3" in setup_script
    assert "--compare-models" in setup_script
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py::test_stage3h_setup_helper_uses_isolated_memory_embedding_env -q
```

Expected: FAIL because `scripts/setup_memory_embedding_env.ps1` does not print bge-m3 or `--compare-models` yet.

- [ ] **Step 3: Update setup helper output**

Replace the final two `Write-Host` lines in `scripts/setup_memory_embedding_env.ps1` with:

```powershell
Write-Host "Memory embedding evaluation environment is ready: $PythonExe"
Write-Host "Run single-model MiniLM evaluation:"
Write-Host ".\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details"
Write-Host "Run Stage 3J candidate comparison:"
Write-Host ".\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --compare-models sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2,BAAI/bge-m3 --details"
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py::test_stage3h_setup_helper_uses_isolated_memory_embedding_env -q
```

Expected: PASS.

---

### Task 5: Focused regression tests

**Files:**
- Test only: `backend/tests/test_memory_embedding_evaluation.py`, `backend/tests/test_memory_embeddings.py`, `backend/tests/test_config.py`

- [ ] **Step 1: Run evaluation-script tests**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Stage 3J focused backend tests**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 3: Run fake baseline command**

Run:

```powershell
python scripts\evaluate_memory_embeddings.py --provider fake --details
```

Expected: exit code 0; JSON includes `provider=fake`, `model=fake-memory-embedding-v1`, `embedding_dimension=6`, `passed=true`, `top1_accuracy >= 0.5`, and `top3_recall >= 0.75`.

---

### Task 6: Isolated real candidate evaluations

**Files:**
- No source edits unless a real defect is found.

- [ ] **Step 1: Verify isolated interpreter exists**

Run:

```powershell
.\.venv-memory-embed\Scripts\python.exe --version
```

Expected if Stage 3H environment is present: prints a Python version.

If the command fails because the environment is missing, run the setup helper commands without changing product dependencies:

```powershell
$VenvPython = ".\.venv-memory-embed\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) { python -m venv ".venv-memory-embed" }
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e "backend"
& $VenvPython -m pip install sentence-transformers
& $VenvPython -c "import sentence_transformers; print(sentence_transformers.__version__)"
```

Expected after setup: import prints a `sentence-transformers` version.

- [ ] **Step 2: Run MiniLM evaluation**

Run:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

Expected if model download/load succeeds: exit code 0 and JSON includes `provider=sentence-transformers`, `model=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, `embedding_dimension=384`, `case_count=8`, and `passed=true`.

If it fails, save the exact stderr/stdout for the evidence doc and do not claim MiniLM is production-ready.

- [ ] **Step 3: Run bge-m3 evaluation**

Run:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model BAAI/bge-m3 --details
```

Expected if model download/load succeeds: JSON includes `provider=sentence-transformers`, `model=BAAI/bge-m3`, `embedding_dimension` as emitted by the provider, `case_count=8`, `top1_accuracy`, `top3_recall`, `embed_ms`, `load_ms`, and `passed`.

If it fails because download/load is blocked, too slow, out of disk, or out of memory, save the exact failure as an environment limitation and do not recommend bge-m3 for enablement.

- [ ] **Step 4: Run batch comparison for final comparable output**

Run:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --compare-models sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2,BAAI/bge-m3 --details
```

Expected if both models run: JSON has a wrapper shape with `model_count=2`, `models=[...]`, and one summary per model.

If the batch command fails only because one model fails to load, rely on the individual command outputs from Steps 2 and 3 for evidence.

---

### Task 7: Evidence document and recommendation

**Files:**
- Create: `docs/stage3j-real-embedding-production-selection.md`

- [ ] **Step 1: Create evidence document after commands have run**

Create `docs/stage3j-real-embedding-production-selection.md` with this structure and the actual observed command outputs from Tasks 5 and 6:

```markdown
# Stage 3J Real Embedding Production Selection

Date: 2026-07-10
Status: VERIFIED PASS or ENVIRONMENT-LIMITED

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

Record the exact observed environment values:

- Main Python command: `python`
- Isolated Python command: `.\.venv-memory-embed\Scripts\python.exe`
- Isolated Python version: value printed by `.\.venv-memory-embed\Scripts\python.exe --version`
- `sentence-transformers` version: value printed by the import check
- Model cache/download notes: describe observed Hugging Face cache, symlink, auth, network, disk, or Windows warnings

## Thresholds

- `min_top1_accuracy = 0.5`
- `min_top3_recall = 0.75`

These are smoke thresholds, not sufficient by themselves to justify changing product defaults.

## Fake baseline

Command:

```powershell
python scripts\evaluate_memory_embeddings.py --provider fake --details
```

Paste the emitted JSON summary from Task 5 Step 3.

## MiniLM candidate

Command:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

Paste the emitted JSON summary or exact failure from Task 6 Step 2.

## bge-m3 candidate

Command:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model BAAI/bge-m3 --details
```

Paste the emitted JSON summary or exact failure from Task 6 Step 3.

## Batch comparison

Command:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --compare-models sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2,BAAI/bge-m3 --details
```

Paste the emitted wrapper JSON or explain why individual results were used instead.

## Recommendation

Choose one of these outcomes based on the observed evidence:

1. If MiniLM and bge-m3 both pass and have similar retrieval quality on the 8-case fixture: recommend MiniLM as the lightweight future opt-in candidate, keep bge-m3 as a stronger/heavier candidate that requires a larger benchmark before production use, and keep deterministic relevance as fallback.
2. If bge-m3 materially improves top-1/top-3 quality without unacceptable setup/runtime cost: recommend bge-m3 as the preferred quality candidate, MiniLM as the lightweight fallback, and deterministic relevance as the always-available fallback.
3. If bge-m3 fails to install/download/load/run, or is operationally too heavy for local development: do not recommend bge-m3 for enablement; recommend MiniLM only if MiniLM passed, with deterministic relevance as fallback.
4. If both real models fail or the fixture cannot distinguish them reliably: do not recommend a real embedding production candidate yet; require a larger benchmark or environment fix before enablement.

State explicitly that no default product configuration changes in Stage 3J.

## Conditions before future enablement

Before any later opt-in production configuration uses the recommended model, require:

- an explicit environment/config opt-in;
- fallback to deterministic relevance on provider failure;
- no mandatory dependency added to the default backend install;
- no committed model cache or `.venv-memory-embed` files;
- retrieval limited to confirmed active long-term memories;
- pending/dismissed/archived candidates kept out of chat context;
- a larger evaluation set if the 8-case fixture is insufficient to distinguish candidates.

## Validation

Record exact command results from Tasks 5, 6, and 8.

## Stage boundary check

Stage 3J did not implement session summaries, automatic active memory writes, vector indexes, automatic conflict resolution, or Stage 4 emotion state.
```

- [ ] **Step 2: Self-check evidence document for overclaiming**

Read `docs/stage3j-real-embedding-production-selection.md` and confirm:

- it never says real embeddings are enabled by default;
- it does not claim production correctness from only eight fixture cases;
- it records failures as failures rather than hiding them;
- it names deterministic relevance as fallback;
- it says no private data was used.

---

### Task 8: Full validation and status update

**Files:**
- Modify: `CLAUDE.md`
- Test: backend pytest suite

- [ ] **Step 1: Run focused tests again**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full backend tests**

Run:

```powershell
python -m pytest backend/tests -q
```

Expected: PASS.

- [ ] **Step 3: Update `CLAUDE.md` only after evidence and tests are complete**

Update the header from:

```markdown
> 当前阶段：**阶段 3——长期记忆（IMPLEMENTING；3A–3I COMPLETED；NEXT: Session Summary Storage Design or Real Embedding Production Selection Evaluation）**
> 更新日期：2026-07-09
```

to:

```markdown
> 当前阶段：**阶段 3——长期记忆（IMPLEMENTING；3A–3J COMPLETED；NEXT: Session Summary Storage Design or Semantic Conflict Detection Expansion）**
> 更新日期：2026-07-10
```

Update the Stage 3 table row from:

```markdown
| 阶段 3：长期记忆 | **IMPLEMENTING** | 当前阶段；3A–3I 已完成；下一步可在会话摘要独立存储设计或真实 embedding 模型生产选型评估中选择一个最小闭环 |
```

to:

```markdown
| 阶段 3：长期记忆 | **IMPLEMENTING** | 当前阶段；3A–3J 已完成；下一步可在会话摘要独立存储设计或通用语义矛盾检测扩展中选择一个最小闭环 |
```

Update the completed Stage 3 summary paragraph from:

```markdown
已完成子任务：3A–3I。已建立手动记忆 CRUD、候选确认、相关性检索、冲突审计、保守语义冲突检测、opt-in embedding retrieval、中文检索评估、隔离真实 embedding 模型评估路径，以及用户确认式 opt-in LLM 记忆候选抽取。具体证据见 `docs/stage3*.md`。
```

to:

```markdown
已完成子任务：3A–3J。已建立手动记忆 CRUD、候选确认、相关性检索、冲突审计、保守语义冲突检测、opt-in embedding retrieval、中文检索评估、隔离真实 embedding 模型评估路径、用户确认式 opt-in LLM 记忆候选抽取，以及真实 embedding 模型生产选型评估。具体证据见 `docs/stage3*.md`。
```

Update the current unimplemented line from:

```markdown
当前尚未实现：通用语义矛盾检测、真实 embedding 模型生产选型、会话摘要、自动冲突合并/解决工作流、阶段 4 情感系统。
```

to:

```markdown
当前尚未实现：通用语义矛盾检测扩展、会话摘要、自动冲突合并/解决工作流、阶段 4 情感系统。
```

Update the next-task bullet list from:

```markdown
- 会话摘要的独立存储设计：必须保持聊天历史、会话摘要和长期记忆分离；不得把摘要包装成长期记忆。
- 更深入的真实 embedding 模型生产选型评估：必须保持 opt-in、可回退、可审计，不得改变长期记忆确认边界。
```

to:

```markdown
- 会话摘要的独立存储设计：必须保持聊天历史、会话摘要和长期记忆分离；不得把摘要包装成长期记忆。
- 通用语义矛盾检测扩展：必须保持保守策略、保留审计痕迹，不得自动覆盖或静默合并冲突记忆。
```

- [ ] **Step 4: Confirm Stage 4 remains unstarted**

Run:

```powershell
python - <<'PY'
from pathlib import Path
text = Path('CLAUDE.md').read_text(encoding='utf-8')
assert '阶段 4：情感系统 | 未开始' in text
assert '阶段 3——长期记忆（IMPLEMENTING；3A–3J COMPLETED' in text
assert '真实 embedding 模型生产选型评估' in text
print('CLAUDE.md stage status check PASS')
PY
```

Expected: prints `CLAUDE.md stage status check PASS`.

---

### Task 9: Scope, privacy, and final report

**Files:**
- Review only: changed files from this plan

- [ ] **Step 1: Check changed files list**

Run:

```powershell
git status --short
```

Expected if git is unavailable in this project: command reports that this is not a git repository. In that case, list changed files manually from the task record:

- `scripts/evaluate_memory_embeddings.py`
- `backend/tests/test_memory_embedding_evaluation.py`
- `scripts/setup_memory_embedding_env.ps1`
- `docs/stage3j-real-embedding-production-selection.md`
- `CLAUDE.md`

No frontend runtime files should be changed.

- [ ] **Step 2: Search changed files for secrets and Stage 4 implementation drift**

Run:

```powershell
python - <<'PY'
from pathlib import Path
paths = [
    Path('scripts/evaluate_memory_embeddings.py'),
    Path('backend/tests/test_memory_embedding_evaluation.py'),
    Path('scripts/setup_memory_embedding_env.ps1'),
    Path('docs/stage3j-real-embedding-production-selection.md'),
    Path('CLAUDE.md'),
]
needles = ['sk-', 'api_key=', 'secret=', 'token=', 'ANTHROPIC_API_KEY=', 'DEEPSEEK_API_KEY=']
for path in paths:
    text = path.read_text(encoding='utf-8', errors='ignore')
    for needle in needles:
        if needle.lower() in text.lower():
            print(f'{path}: {needle}')
PY
```

Expected: no output.

- [ ] **Step 3: Run final backend validation command**

Run:

```powershell
python -m pytest backend/tests/test_memory_embedding_evaluation.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 4: Prepare final report**

Use this exact report structure:

```text
完成内容：
- Stage 3J embedding production-selection evaluation path completed.
- Evaluation script now reports embedding dimensions and supports batch candidate comparison.
- Evidence recorded in docs/stage3j-real-embedding-production-selection.md.
- CLAUDE.md updated only after validation.

修改文件：
- scripts/evaluate_memory_embeddings.py
- backend/tests/test_memory_embedding_evaluation.py
- scripts/setup_memory_embedding_env.ps1
- docs/stage3j-real-embedding-production-selection.md
- CLAUDE.md

验证命令与结果：
- python -m pytest backend/tests/test_memory_embedding_evaluation.py backend/tests/test_memory_embeddings.py backend/tests/test_config.py -q → actual result
- python -m pytest backend/tests -q → actual result
- python scripts\evaluate_memory_embeddings.py --provider fake --details → actual result
- .\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details → actual result or limitation
- .\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model BAAI/bge-m3 --details → actual result or limitation

未完成或受限部分：
- No default real embedding enablement.
- No mandatory dependency added.
- No session summaries or Stage 4 emotion system.
- Any observed model download/runtime limitations.

是否改变当前阶段：
- Yes, only Stage 3 subtask status changes from 3A–3I completed to 3A–3J completed after evidence passes or is accurately recorded as environment-limited.

下一项建议任务：
- Session summary independent storage design, or conservative semantic conflict detection expansion.
```

---

## Self-review checklist

- Spec coverage: This plan covers multi-model comparison, quality metrics, embedding dimension, load/embedding timing, isolated environment use, Windows/cache notes, production recommendation, fallback conditions, opt-in/default boundaries, and no private data usage.
- Placeholder scan: The plan contains no `TBD` or `TODO`; observed metrics are explicitly produced by named commands before the evidence document is written.
- Type consistency: Helper names are consistent across tests and implementation: `measure_embedding_dimension`, `split_compare_models`, `default_model_for_provider`, `evaluate_model`, `models_for_args`, and `build_cli_result`.
- Scope check: The plan does not modify retrieval defaults, memory write behavior, session summary storage, vector indexing, automatic conflict resolution, or Stage 4 emotion state.
- Backward compatibility: Existing single-model CLI commands continue to emit a single summary object and only add `embedding_dimension`.
