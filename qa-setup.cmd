@echo off
rem Check this machine and set it up. Double-click this file first.
rem
rem It reports every prerequisite, installs the ones that are safe to install
rem into a local environment, prints the exact command for anything system wide
rem that it will not install for you, and finishes by running the whole
rem pipeline on a generated fixture to prove the result actually works.
rem
rem Safe to run again at any time. It is also the troubleshooting tool when
rem something breaks after a Python or driver upgrade.

setlocal
cd /d "%~dp0"

rem The project's own environment when it exists, otherwise whatever Python is
rem on the path, because the first job of setup is to create that environment.
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=py -3.12"
if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>&1 || set "PY=python"
)

echo.
"%PY%" -m qa.setup %*
set "CODE=%ERRORLEVEL%"

echo.
if "%CODE%"=="0" (
  echo   Ready. Double-click qa-web.cmd to open the interface.
) else (
  echo   Not ready yet. The table above says what is missing and how to fix it.
  echo   Run this again after fixing it.
)
echo.
pause
endlocal
exit /b %CODE%
