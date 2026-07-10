$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir
Push-Location ..

$backendPort = 18004
$frontendPort = 16004

function Assert-PortFree([int]$port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        throw "Port $port is already in use by listening process $($conn.OwningProcess). Stop that process or choose a different smoke port."
    }
}

function Wait-HttpOk([string]$url, [string]$name, [int]$maxSeconds) {
    for ($i = 1; $i -le $maxSeconds; $i++) {
        Start-Sleep 1
        try {
            $r = Invoke-WebRequest $url -TimeoutSec 2 -UseBasicParsing
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) {
                Write-Output "$name ready after ${i}s"
                return
            }
        } catch {}
    }
    throw "$name failed to become ready at $url"
}

try {
    Push-Location frontend
    npm run prepare:vad-assets
    Pop-Location

    foreach ($p in @($backendPort, $frontendPort)) {
        Assert-PortFree $p
    }
    Start-Sleep 2

    $repoRoot = (Get-Location).Path
    $beJob = Start-Job -Name "be-real-vad-smoke" -ArgumentList $repoRoot, $backendPort -ScriptBlock {
        param([string]$RepoRoot, [int]$BackendPort)
        Set-Location $RepoRoot
        $env:APP_ENV = "test"
        $env:LLM_PROVIDER = "fake"
        $env:ASR_PROVIDER = "fake"
        $env:FAKE_ASR_TEXT = "VAD auto stop smoke transcript."
        $env:TTS_PROVIDER = "fake"
        $env:DATABASE_URL = "sqlite:///./test-results/smoke-real-vad.db"
        & ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $BackendPort
    }
    Write-Output "Backend job: $($beJob.Id)"
    Wait-HttpOk "http://127.0.0.1:$backendPort/health" "Backend" 60

    Push-Location frontend
    $frontendRoot = (Get-Location).Path
    $feJob = Start-Job -Name "fe-real-vad-smoke" -ArgumentList $frontendRoot, $backendPort, $frontendPort -ScriptBlock {
        param([string]$FrontendRoot, [int]$BackendPort, [int]$FrontendPort)
        Set-Location $FrontendRoot
        $backendTarget = "http://127.0.0.1:{0}" -f $BackendPort
        $env:BACKEND_PROXY_TARGET = $backendTarget
        $env:VITE_VAD_ONNX_WASM_BASE_PATH = "/vendor/onnxruntime/"
        $env:VITE_VAD_BASE_ASSET_PATH = "/vendor/vad/"
        & node .\node_modules\vite\bin\vite.js --port $FrontendPort --host 127.0.0.1
    }
    Pop-Location
    Write-Output "Frontend job: $($feJob.Id)"
    Wait-HttpOk "http://127.0.0.1:$frontendPort/" "Frontend" 60

    Push-Location frontend
    $env:E2E_FRONTEND_PORT = "$frontendPort"
    if (-not $env:REAL_VAD_HEADLESS) { $env:REAL_VAD_HEADLESS = "0" }
    if (-not $env:REAL_VAD_REQUIRE_AUTO_STOP) { $env:REAL_VAD_REQUIRE_AUTO_STOP = "1" }
    node .claude-real-vad-ui-smoke.mjs
    $exitCode = $LASTEXITCODE
    Pop-Location

    if ($exitCode -ne 0) {
        throw "Real VAD smoke failed with exit code $exitCode"
    }

    Write-Output "2D real VAD UI smoke PASS. Evidence: frontend/test-results/real-vad-ui-smoke.json"
    exit 0
} finally {
    Get-Job | Where-Object { $_.Name -like "*real-vad-smoke*" } | Stop-Job -ErrorAction SilentlyContinue
    Get-Job | Where-Object { $_.Name -like "*real-vad-smoke*" } | Remove-Job -Force -ErrorAction SilentlyContinue
    Pop-Location
    Pop-Location
}
