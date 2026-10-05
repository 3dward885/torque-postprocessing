@echo off
setlocal
cd /d "%~dp0" || exit /b 1
set "TORQUE_LOG=%~dp0setup.log"
echo Preparing this folder's Python environment. This may take a few minutes.
echo Progress and errors are recorded in "%TORQUE_LOG%".
set "TORQUE_BUNDLED_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%TORQUE_BUNDLED_PY%" goto bundled
py -3.12 -u "%~dp0setup_environment.py" > "%TORQUE_LOG%" 2>&1
set "TORQUE_EXIT=%errorlevel%"
goto finished

:bundled
"%TORQUE_BUNDLED_PY%" -u "%~dp0setup_environment.py" > "%TORQUE_LOG%" 2>&1
set "TORQUE_EXIT=%errorlevel%"

:finished
type "%TORQUE_LOG%"
if not "%TORQUE_EXIT%"=="0" echo Setup failed. Keep setup.log and check README.txt.
if /i not "%~1"=="--no-pause" pause
exit /b %TORQUE_EXIT%
