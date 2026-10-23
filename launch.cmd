@echo off
rem One command to start the whole system. Usage:  launch.cmd [--status] [--prod] [--no-open] [--skip-lm] [--stop-docker]
cd /d "%~dp0"
".venv\Scripts\python.exe" -m scripts.start %*
