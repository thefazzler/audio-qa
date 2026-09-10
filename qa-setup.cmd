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

rem The project's own environment when it exists, otherwise a Python that can
rem run the setup module, because the first job of setup is to create that
rem environment. Each candidate is actually run: on Windows 11 a bare "python"
rem with nothing installed is a Microsoft Store stub that only looks present.
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
if not defined PY py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY goto nopython

echo.
%PY% -m qa.setup %*
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

:nopython
rem Setup is written in Python, so this is the one prerequisite it cannot
rem report on its own. Say exactly what to do, the same way it would have.
echo.
echo   PREREQUISITE  STATUS   FOUND
echo   ------------------------------------------------------------
echo   Python        MISSING  no Python on this machine
echo.
echo   What to do:
echo.
echo   Python: MISSING
echo     required: 3.11 or newer, below 3.14
echo     fix:      open a terminal ^(Start, type "terminal"^) and run
echo.
echo                 winget install --id Python.Python.3.12 -e
echo.
echo     then close that terminal, and double-click this file again.
echo     Without winget, use the installer at https://python.org/downloads
echo     and tick "Add python.exe to PATH".
echo.
pause
endlocal
exit /b 1
