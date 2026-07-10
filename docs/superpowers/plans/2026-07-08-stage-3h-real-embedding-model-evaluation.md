# Stage 3H Isolated Real Embedding Model Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create an isolated real-embedding evaluation environment and run the existing Chinese memory retrieval smoke against a lightweight `sentence-transformers` model.

**Architecture:** Keep production code and default dependencies unchanged. Add only an ignored local environment path, a PowerShell setup helper, and evidence documentation; run the existing `scripts/evaluate_memory_embeddings.py` with the isolated interpreter.

**Tech Stack:** Python 3.12, PowerShell, venv, pip, sentence-transformers, existing Stage 3G evaluation script.

---

## Scope and constraints

This plan implements Stage 3H only.

It must not implement:

- Stage 4 emotion state or expression strategy;
- LLM-based memory candidate extraction;
- automatic memory writes from chat history;
- session summaries;
- sqlite-vec/Faiss/vector-index integration;
- mandatory backend dependency changes.

Do not commit unless the user explicitly asks for a commit.

## File structure

Modify:

- `.gitignore`
  - Add `.venv-memory-embed/` so local embedding dependencies are never committed.

- `README.md`
  - Add optional isolated real embedding evaluation instructions after the Stage 3G note.

- `CLAUDE.md`
  - Update Stage 3 status after validation/evidence is complete.

Create:

- `scripts/setup_memory_embedding_env.ps1`
  - Creates `.venv-memory-embed` and installs `sentence-transformers` plus editable backend.

- `docs/stage3h-real-embedding-model-evaluation.md`
  - Records setup command, fake baseline, real model outcome, limitations, and confirmation that Stage 4 remains unstarted.

No product source files should change unless the existing evaluation script fails due a real defect.

---

### Task 1: Ignore and setup helper

**Files:**
- Modify: `.gitignore`
- Create: `scripts/setup_memory_embedding_env.ps1`

- [ ] **Step 1: Add isolated env to gitignore**

Add this block after the TTS isolated environment block in `.gitignore`:

```gitignore
# Memory embedding isolated evaluation environment
.venv-memory-embed/
```

- [ ] **Step 2: Create setup helper**

Create `scripts/setup_memory_embedding_env.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPath = Join-Path $Root ".venv-memory-embed"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    python -m venv $VenvPath
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -e (Join-Path $Root "backend")
& $PythonExe -m pip install sentence-transformers

Write-Host "Memory embedding evaluation environment is ready: $PythonExe"
Write-Host "Run:"
Write-Host ".\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details"
```

- [ ] **Step 3: Verify helper syntax enough to execute**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_memory_embedding_env.ps1
```

Expected if network/package install works: venv is created, pip upgrades, backend editable install succeeds, `sentence-transformers` installs, and command is printed.

Expected if network/package install fails: command exits non-zero with exact pip/network error. Record the failure in the evidence doc and do not claim real-provider PASS.

---

### Task 2: Real evaluation run

**Files:**
- No source edits unless the existing evaluation script has a real defect.

- [ ] **Step 1: Run fake baseline**

Run:

```powershell
python scripts\evaluate_memory_embeddings.py --provider fake --details
```

Expected: exit code 0 and JSON containing:

```json
"provider": "fake"
"passed": true
```

Record `top1_accuracy`, `top3_recall`, `load_ms`, and `embed_ms`.

- [ ] **Step 2: Verify isolated dependency import**

Run:

```powershell
.\.venv-memory-embed\Scripts\python.exe -c "import sentence_transformers; print(sentence_transformers.__version__)"
```

Expected after successful setup: prints a version number.

If this fails, record it as an environment limitation.

- [ ] **Step 3: Run real MiniLM evaluation**

Run:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

Expected after successful dependency install/model download: JSON containing:

```json
"provider": "sentence-transformers"
"model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
"case_count": 8
```

Record `top1_accuracy`, `top3_recall`, `passed`, `load_ms`, and `embed_ms`.

If model download/load fails, record exact stderr/stdout as an environment limitation and do not claim real-provider PASS.

---

### Task 3: Regression tests

**Files:**
- No source edits unless a test failure identifies a real defect.

- [ ] **Step 1: Run focused backend tests**

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

- [ ] **Step 3: Frontend regression decision**

If only `.gitignore`, script, and docs changed, frontend tests are not required. If README-only frontend docs changed, frontend runtime remains unchanged. State explicitly that frontend tests were skipped because no frontend runtime code changed.

---

### Task 4: Evidence and status docs

**Files:**
- Create: `docs/stage3h-real-embedding-model-evaluation.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Create evidence doc with observed results**

Create `docs/stage3h-real-embedding-model-evaluation.md` with exact results. Use this structure and replace the sample metric values with observed values:

```markdown
# Stage 3H Isolated Real Embedding Model Evaluation

Date: 2026-07-08
Status: VERIFIED PASS or ENVIRONMENT-LIMITED

## Scope

Stage 3H creates/uses `.venv-memory-embed` to run the Stage 3G Chinese embedding retrieval evaluation with a real `sentence-transformers` model. It does not change product defaults or add mandatory dependencies.

## Non-goals

- No LLM-based memory extraction.
- No automatic memory writes from chat history.
- No session summaries.
- No Stage 4 emotion system.
- No vector index integration.

## Environment

- Environment path: `.venv-memory-embed`
- Isolated Python command: `.\.venv-memory-embed\Scripts\python.exe`
- Python version: record observed value
- `sentence-transformers` import: record observed value

## Fake baseline

Record observed JSON summary.

## Real MiniLM evaluation

Command:

```powershell
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

Record observed JSON summary or exact failure.

## Validation

Record exact test commands and pass counts.

## Limitations

Record install/download/network/model limitations. State that this is not production model selection.
```

- [ ] **Step 2: Update README**

Add after the Stage 3G section:

```markdown
### Stage 3H isolated real embedding evaluation

Real embedding evaluation is isolated from the main backend environment:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_memory_embedding_env.ps1
.\.venv-memory-embed\Scripts\python.exe scripts\evaluate_memory_embeddings.py --provider sentence-transformers --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 --details
```

This remains an evaluation path only. It does not change default retrieval, does not create memories, and does not implement emotional state.
```

- [ ] **Step 3: Update CLAUDE.md after validation**

Add under Stage 3 current entry:

```markdown
- 3H Isolated Real Embedding Model Evaluation 已完成（2026-07-08；新增 `.venv-memory-embed` 隔离评估路径和 `scripts/setup_memory_embedding_env.ps1`；运行 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 真实中文 fixture 检索评估并记录结果/环境限制；不改产品默认行为、不新增强制依赖、不写入聊天历史或长期记忆；证据记录于 `docs/stage3h-real-embedding-model-evaluation.md`）。验证：按实际结果填写。
```

Also update the Stage 3 table row to include 3H completion.

---

### Task 5: Scope/privacy check

**Files:**
- No source edits unless a real problem is found.

- [ ] **Step 1: Inspect focused diff**

Run:

```powershell
git diff -- .gitignore scripts/setup_memory_embedding_env.ps1 docs/stage3h-real-embedding-model-evaluation.md README.md CLAUDE.md
```

Expected: diff contains only ignore rule, setup helper, and docs/status updates.

- [ ] **Step 2: Confirm no secrets or scope crossing**

Search changed files for secrets and Stage 4 implementation terms:

```powershell
python - <<'PY'
from pathlib import Path
paths = [
    Path('.gitignore'),
    Path('scripts/setup_memory_embedding_env.ps1'),
    Path('docs/stage3h-real-embedding-model-evaluation.md'),
    Path('README.md'),
    Path('CLAUDE.md'),
]
needles = ['sk-', 'api_key=', 'secret=', 'token=', 'mood', 'trust', 'concern', 'distance', 'irritation', 'formality']
for path in paths:
    text = path.read_text(encoding='utf-8', errors='ignore')
    for needle in needles:
        if needle.lower() in text.lower():
            print(f'{path}: {needle}')
PY
```

Expected: only existing CLAUDE.md Stage 4 rule text may match emotion terms. No API keys or private data should appear.

---

## Self-review checklist

- Spec coverage: The plan covers isolated env creation, real dependency install, fake baseline, real MiniLM evaluation, docs, status update, and scope/privacy check.
- Placeholder scan: No placeholders are intentionally left for implementation; evidence doc steps explicitly require replacing sample values with observed results.
- Type consistency: Paths and commands consistently use `.venv-memory-embed` and `scripts\evaluate_memory_embeddings.py`.
- Scope check: The plan does not modify product defaults, memory writing, session summaries, vector indexes, or Stage 4 emotion state.
