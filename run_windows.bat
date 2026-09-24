@echo off
title FG Testing Tracker
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Download it from https://www.python.org/downloads/
  echo During setup, tick "Add python.exe to PATH", then run this file again.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo First run: setting things up. This takes a minute...
  python -m venv .venv
)
call ".venv\Scripts\activate.bat"
python -m pip install --quiet --disable-pip-version-check -r requirements.txt

python app.py
pause
