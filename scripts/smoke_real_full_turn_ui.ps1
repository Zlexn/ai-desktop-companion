$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir
Push-Location ..

function Import-LocalEnvKeys([string]$Path, [string[]]$Names) {
    if (-not (Test-Path $Path)) { return }
    $allowed = @{}
    foreach ($name in $Names) { $allowed[$name] = $true }

    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $match = [regex]::Match($trimmed, '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$')
        if (-not $match.Success) { continue }

        $key = $match.Groups[1].Value
        if (-not $allowed.ContainsKey($key)) { continue }
        if (Test-Path "Env:$key") { continue }

        $value = $match.Groups[2].Value.Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
}

Import-LocalEnvKeys ".env" @("LLM_PROVIDER", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY")

$backendPort = 18003
$frontendPort = 16003
$cosyVoiceBaseUrl = if ($env:TTS_COSYVOICE_BASE_URL) { $env:TTS_COSYVOICE_BASE_URL } else { "http://127.0.0.1:8001" }
$modelPath = if ($env:ASR_FASTER_WHISPER_MODEL_PATH) { $env:ASR_FASTER_WHISPER_MODEL_PATH } else { "$env:USERPROFILE\.cache\huggingface\hub\models--Systran--faster-whisper-medium\snapshots\08e178d48790749d25932bbc082711ddcfdfbc4f" }
$llmProvider = if ($env:LLM_PROVIDER) { $env:LLM_PROVIDER } else { "deepseek" }

function Stop-PortOwner([int]$port) {
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
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
    if (-not (Test-Path $modelPath)) {
        throw "FasterWhisper model path not found: $modelPath"
    }

    if ($llmProvider -eq "deepseek" -and -not (Test-Path Env:DEEPSEEK_API_KEY)) {
        throw "LLM_PROVIDER=deepseek requires DEEPSEEK_API_KEY in the local environment. The key value was not printed."
    }
    if ($llmProvider -eq "anthropic" -and -not (Test-Path Env:ANTHROPIC_API_KEY)) {
        throw "LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY in the local environment. The key value was not printed."
    }
    if ($llmProvider -eq "fake") {
        throw "2C-2 requires a real LLM provider. Set LLM_PROVIDER=deepseek or another real configured provider."
    }

    Write-Output "Checking CosyVoice health at $cosyVoiceBaseUrl/health"
    $cosyHealth = Invoke-WebRequest "$cosyVoiceBaseUrl/health" -TimeoutSec 5 -UseBasicParsing
    if ($cosyHealth.StatusCode -lt 200 -or $cosyHealth.StatusCode -ge 300) {
        throw "CosyVoice health returned HTTP $($cosyHealth.StatusCode)"
    }

    foreach ($p in @($backendPort, $frontendPort)) {
        Stop-PortOwner $p
    }
    Start-Sleep 2

    $env:APP_ENV = "test"
    $env:LLM_PROVIDER = $llmProvider
    $env:ASR_PROVIDER = "faster-whisper"
    $env:ASR_FASTER_WHISPER_MODEL_PATH = $modelPath
    $env:ASR_FASTER_WHISPER_MODEL_NAME = if ($env:ASR_FASTER_WHISPER_MODEL_NAME) { $env:ASR_FASTER_WHISPER_MODEL_NAME } else { "medium" }
    $env:ASR_FASTER_WHISPER_MODEL_REVISION = if ($env:ASR_FASTER_WHISPER_MODEL_REVISION) { $env:ASR_FASTER_WHISPER_MODEL_REVISION } else { "08e178d48790749d25932bbc082711ddcfdfbc4f" }
    $env:ASR_FASTER_WHISPER_DEVICE = if ($env:ASR_FASTER_WHISPER_DEVICE) { $env:ASR_FASTER_WHISPER_DEVICE } else { "cuda" }
    $env:ASR_FASTER_WHISPER_COMPUTE_TYPE = if ($env:ASR_FASTER_WHISPER_COMPUTE_TYPE) { $env:ASR_FASTER_WHISPER_COMPUTE_TYPE } else { "float16" }
    $env:ASR_FASTER_WHISPER_BEAM_SIZE = if ($env:ASR_FASTER_WHISPER_BEAM_SIZE) { $env:ASR_FASTER_WHISPER_BEAM_SIZE } else { "1" }
    $env:ASR_FASTER_WHISPER_TIMEOUT_SECONDS = if ($env:ASR_FASTER_WHISPER_TIMEOUT_SECONDS) { $env:ASR_FASTER_WHISPER_TIMEOUT_SECONDS } else { "30" }
    $env:TTS_PROVIDER = "cosyvoice-http"
    $env:TTS_DEFAULT_VOICE = if ($env:TTS_DEFAULT_VOICE) { $env:TTS_DEFAULT_VOICE } else { "default-zh-female" }
    $env:TTS_COSYVOICE_BASE_URL = $cosyVoiceBaseUrl
    $env:TTS_COSYVOICE_MODEL = if ($env:TTS_COSYVOICE_MODEL) { $env:TTS_COSYVOICE_MODEL } else { "Fun-CosyVoice3-0.5B-2512" }
    $env:TTS_COSYVOICE_TIMEOUT_SECONDS = if ($env:TTS_COSYVOICE_TIMEOUT_SECONDS) { $env:TTS_COSYVOICE_TIMEOUT_SECONDS } else { "240" }
    if ($llmProvider -eq "deepseek" -and -not $env:DEEPSEEK_MAX_TOKENS) { $env:DEEPSEEK_MAX_TOKENS = "24" }
    $env:DATABASE_URL = "sqlite:///./test-results/smoke-real-full-turn.db"

    $backendEnv = @{
        APP_ENV = $env:APP_ENV
        LLM_PROVIDER = $env:LLM_PROVIDER
        DEEPSEEK_API_KEY = $env:DEEPSEEK_API_KEY
        DEEPSEEK_MAX_TOKENS = $env:DEEPSEEK_MAX_TOKENS
        ANTHROPIC_API_KEY = $env:ANTHROPIC_API_KEY
        ASR_PROVIDER = $env:ASR_PROVIDER
        ASR_FASTER_WHISPER_MODEL_PATH = $env:ASR_FASTER_WHISPER_MODEL_PATH
        ASR_FASTER_WHISPER_MODEL_NAME = $env:ASR_FASTER_WHISPER_MODEL_NAME
        ASR_FASTER_WHISPER_MODEL_REVISION = $env:ASR_FASTER_WHISPER_MODEL_REVISION
        ASR_FASTER_WHISPER_DEVICE = $env:ASR_FASTER_WHISPER_DEVICE
        ASR_FASTER_WHISPER_COMPUTE_TYPE = $env:ASR_FASTER_WHISPER_COMPUTE_TYPE
        ASR_FASTER_WHISPER_BEAM_SIZE = $env:ASR_FASTER_WHISPER_BEAM_SIZE
        ASR_FASTER_WHISPER_TIMEOUT_SECONDS = $env:ASR_FASTER_WHISPER_TIMEOUT_SECONDS
        TTS_PROVIDER = $env:TTS_PROVIDER
        TTS_DEFAULT_VOICE = $env:TTS_DEFAULT_VOICE
        TTS_COSYVOICE_BASE_URL = $env:TTS_COSYVOICE_BASE_URL
        TTS_COSYVOICE_MODEL = $env:TTS_COSYVOICE_MODEL
        TTS_COSYVOICE_TIMEOUT_SECONDS = $env:TTS_COSYVOICE_TIMEOUT_SECONDS
        DATABASE_URL = $env:DATABASE_URL
    }

    $beJob = Start-Job -Name "be-real-full-turn-smoke" -ScriptBlock {
        Set-Location $using:PWD
        $envMap = $using:backendEnv
        foreach ($item in $envMap.GetEnumerator()) {
            if ($null -ne $item.Value -and $item.Value -ne "") {
                [Environment]::SetEnvironmentVariable($item.Key, [string]$item.Value, "Process")
            }
        }
        & ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $using:backendPort
    }
    Write-Output "Backend job: $($beJob.Id)"
    Wait-HttpOk "http://127.0.0.1:$backendPort/health" "Backend" 60

    $env:BACKEND_PROXY_TARGET = "http://127.0.0.1:$backendPort"
    Push-Location frontend
    $feJob = Start-Job -Name "fe-real-full-turn-smoke" -ScriptBlock {
        Set-Location $using:PWD
        & node .\node_modules\vite\bin\vite.js --port $using:frontendPort --host 127.0.0.1
    }
    Pop-Location
    Write-Output "Frontend job: $($feJob.Id)"
    Wait-HttpOk "http://127.0.0.1:$frontendPort/" "Frontend" 60

    Push-Location frontend
    $env:E2E_FRONTEND_PORT = "$frontendPort"
    if (-not $env:REAL_FULL_TURN_HEADLESS) { $env:REAL_FULL_TURN_HEADLESS = "0" }
    if (-not $env:REAL_FULL_TURN_REQUIRE_AUDIO_CONFIRM) { $env:REAL_FULL_TURN_REQUIRE_AUDIO_CONFIRM = "1" }
    if ($env:REAL_FULL_TURN_TTS_TEXT_OVERRIDE) {
        Write-Output "REAL_FULL_TURN_TTS_TEXT_OVERRIDE is set; this run is a short-text wiring diagnostic and must not be used to mark natural 2C-2 full-reply TTS complete."
    }
    node .claude-real-full-turn-ui-smoke.mjs
    $exitCode = $LASTEXITCODE
    Pop-Location

    if ($exitCode -ne 0) {
        throw "Real full-turn smoke failed with exit code $exitCode"
    }

    Write-Output "2C-2 real full-turn smoke PASS. Evidence: frontend/test-results/real-full-turn-ui-smoke.json"
    exit 0
} finally {
    Get-Job | Where-Object { $_.Name -like "*real-full-turn-smoke*" } | Stop-Job -ErrorAction SilentlyContinue
    Get-Job | Where-Object { $_.Name -like "*real-full-turn-smoke*" } | Remove-Job -Force -ErrorAction SilentlyContinue
    Pop-Location
    Pop-Location
}
