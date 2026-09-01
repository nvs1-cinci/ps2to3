@echo off
rem windows: double-click this file.
cd /d "%~dp0"
if exist .venv\Scripts\pythonw.exe (start "" .venv\Scripts\pythonw.exe -m ps2to3.gui & exit /b)
set PYTHONPATH=src
where pythonw >nul 2>&1 && (start "" pythonw -m ps2to3.gui & exit /b)
where python  >nul 2>&1 && (python -m ps2to3.gui & exit /b)
where py      >nul 2>&1 && (py -3 -m ps2to3.gui & exit /b)
echo Python 3 is not installed. Get it from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH" in the installer), then double-click again.
pause
