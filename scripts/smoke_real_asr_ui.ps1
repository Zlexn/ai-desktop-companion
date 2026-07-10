$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir
Push-Location ..

$backendPort = 18002
$frontendPort = 16002
$modelPath = "$env:USERPROFILE\.cache\huggingface\hub\models--Systran--faster-whisper-medium\snapshots\08e178d48790749d25932bbc082711ddcfdfbc4f"

# Clean up
foreach ($p in @($backendPort, $frontendPort, 8000, 15173)) {
    $conn = Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue }
}
Start-Sleep 2

# Env
$env:APP_ENV = "test"
$env:LLM_PROVIDER = "fake"
$env:TTS_PROVIDER = "fake"
$env:ASR_PROVIDER = "faster-whisper"
$env:ASR_FASTER_WHISPER_MODEL_PATH = $modelPath
$env:ASR_FASTER_WHISPER_MODEL_NAME = "medium"
$env:ASR_FASTER_WHISPER_MODEL_REVISION = "08e178d48790749d25932bbc082711ddcfdfbc4f"
$env:ASR_FASTER_WHISPER_DEVICE = "cuda"
$env:ASR_FASTER_WHISPER_COMPUTE_TYPE = "float16"
$env:ASR_FASTER_WHISPER_BEAM_SIZE = "1"
$env:ASR_FASTER_WHISPER_TIMEOUT_SECONDS = "30"
$env:DATABASE_URL = "sqlite:///./test-results/smoke-ui.db"

# Start backend
$beJob = Start-Job -Name "be-smoke" -ScriptBlock {
    Set-Location $using:PWD
    & ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $using:backendPort
}
Write-Output "Backend job: $($beJob.Id)"

for ($i = 1; $i -le 20; $i++) {
    Start-Sleep 1
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:$backendPort/health" -TimeoutSec 2 -UseBasicParsing
        if ($r.StatusCode -eq 200) { Write-Output "BE ready after ${i}s"; break }
    } catch {}
}
if ($i -gt 20) { throw "BE failed" }

# Start frontend
$env:BACKEND_PROXY_TARGET = "http://127.0.0.1:$backendPort"
Push-Location frontend
$feJob = Start-Job -Name "fe-smoke" -ScriptBlock {
    Set-Location $using:PWD
    & node .\node_modules\vite\bin\vite.js --port $using:frontendPort --host 127.0.0.1
}
Pop-Location
Write-Output "Frontend job: $($feJob.Id)"

for ($i = 1; $i -le 20; $i++) {
    Start-Sleep 1
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:$frontendPort/" -TimeoutSec 2 -UseBasicParsing
        if ($r.StatusCode -eq 200) { Write-Output "FE ready after ${i}s"; break }
    } catch {}
}
if ($i -gt 20) { throw "FE failed" }

# Run smoke
Push-Location frontend
$env:E2E_FRONTEND_PORT = "$frontendPort"
$result = node .claude-real-asr-ui-smoke.mjs 2>&1
$exitCode = $LASTEXITCODE
Write-Output $result
Pop-Location

# Cleanup
Get-Job | Where-Object { $_.Name -like "*smoke*" } | Stop-Job -ErrorAction SilentlyContinue
Get-Job | Where-Object { $_.Name -like "*smoke*" } | Remove-Job -Force -ErrorAction SilentlyContinue

exit $exitCode
