@echo off
cd /d "%~dp0"
set "TORQUE_BUNDLED_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%TORQUE_BUNDLED_PY%" (
  "%TORQUE_BUNDLED_PY%" setup_environment.py
  pause
  exit /b
)
py -3.12 setup_environment.py
if errorlevel 1 echo Setup failed. See README.txt for Python and Tkinter requirements.
pause
