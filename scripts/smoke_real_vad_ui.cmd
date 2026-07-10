@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0smoke_real_vad_ui.ps1"
exit /b %ERRORLEVEL%
