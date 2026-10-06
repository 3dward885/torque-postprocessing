@echo off
setlocal
cd /d "%~dp0" || exit /b 1
set "TORQUE_LOG=%~dp0launch.log"
if not exist ".venv\Scripts\pythonw.exe" goto missing_environment
echo Starting Torque Data Postprocessing. Startup errors will appear here.
start "" /b /wait ".venv\Scripts\pythonw.exe" -u "%~dp0app.py" %* > "%TORQUE_LOG%" 2>&1
set "TORQUE_EXIT=%errorlevel%"
if "%TORQUE_EXIT%"=="0" exit /b 0
type "%TORQUE_LOG%"
echo Application failed to start or exited with an error. Details: "%TORQUE_LOG%"
pause
exit /b %TORQUE_EXIT%

:missing_environment
echo This folder has not been set up. Run Setup_Windows.cmd in this same folder.
echo This folder has not been set up. Run Setup_Windows.cmd in this same folder. > "%TORQUE_LOG%"
pause
exit /b 1
