@echo off
setlocal
set APP_ENV=test
set LLM_PROVIDER=fake
set TTS_PROVIDER=fake
set ASR_PROVIDER=faster-whisper
set ASR_FASTER_WHISPER_MODEL_PATH=%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-medium\snapshots\08e178d48790749d25932bbc082711ddcfdfbc4f
set ASR_FASTER_WHISPER_MODEL_NAME=medium
set ASR_FASTER_WHISPER_MODEL_REVISION=08e178d48790749d25932bbc082711ddcfdfbc4f
set ASR_FASTER_WHISPER_DEVICE=cuda
set ASR_FASTER_WHISPER_COMPUTE_TYPE=float16
set ASR_FASTER_WHISPER_BEAM_SIZE=1
set ASR_FASTER_WHISPER_TIMEOUT_SECONDS=30
set DATABASE_URL=sqlite:///./test-results/smoke-ui.db
set BACKEND_PROXY_TARGET=http://127.0.0.1:18002

echo Starting backend...
start "" "..\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir ..\backend --host 127.0.0.1 --port 18002

ping -n 10 127.0.0.1 >nul
echo Backend started

echo Starting frontend...
start "" node .\node_modules\vite\bin\vite.js --port 16002 --host 127.0.0.1

ping -n 8 127.0.0.1 >nul
echo Frontend started

echo Running smoke...
node .claude-real-asr-ui-smoke.mjs

echo Smoke exit code: %ERRORLEVEL%

taskkill /f /im python.exe /fi "WINDOWTITLE eq *uvicorn*" 2>nul
taskkill /f /im node.exe /fi "WINDOWTITLE eq *vite*" 2>nul

exit /b %ERRORLEVEL%
