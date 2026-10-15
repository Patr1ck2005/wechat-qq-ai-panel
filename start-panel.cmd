@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Please run scripts\install.ps1 first.
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m wq_panel
