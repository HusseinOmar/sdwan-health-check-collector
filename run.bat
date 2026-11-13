@echo off
REM SD-WAN Collector launcher (Windows).
REM   run.bat                -> web page (http://127.0.0.1:5050)
REM   run.bat cli --url https://vmanage.example.com -u USER --customer "ACME"   -> command line
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3.9+ is required. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^).
  pause & exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" || (echo Python 3.9 or newer is required. & pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" (
  echo First run: creating a private Python environment ^(.venv^)...
  %PY% -m venv .venv || (echo Could not create the environment. & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || (echo Package install failed - check proxy/internet access. & pause & exit /b 1)
)
if /i "%~1"=="cli" (
  shift
  ".venv\Scripts\python.exe" collect.py %1 %2 %3 %4 %5 %6 %7 %8 %9
) else (
  ".venv\Scripts\python.exe" webapp.py %*
)
endlocal
