@echo off
rem Launcher used by the "run TDI main" scheduled task.
rem Runs the scheduler from the project venv; logs go to logs\top_deals.log.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
".venv\Scripts\python.exe" -m app.main %*
exit /b %ERRORLEVEL%
