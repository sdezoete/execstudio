@echo off
rem Starts the Executive Presentation Studio. Settings: config.json (or STUDIO_* environment variables).
setlocal
cd /d "%~dp0.."
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" server.py %*
) else (
    py -3.11 server.py %*
)
endlocal
