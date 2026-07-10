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
