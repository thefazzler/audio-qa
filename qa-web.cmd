@echo off
rem Start the Audio QA web interface. Double-click this file.
rem
rem Everything a colleague needs to run a course is on the other side of this
rem one file. Nobody reviewing narration should have to learn what a virtual
rem environment is, and the step that used to be "activate the venv, then type
rem qa-web" was where the instructions lost people.
rem
rem Run qa-setup.cmd first if this says the environment is missing.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo   No environment here yet.
  echo.
  echo   Double-click qa-setup.cmd first. It checks what this machine needs,
  echo   installs what is safe to install, and tells you the exact command for
  echo   anything it will not install for you.
  echo.
  pause
  exit /b 1
)

echo Starting the Audio QA interface. Close this window to stop the server.
echo A run already under way keeps going: it is a separate process.
echo.
".venv\Scripts\python.exe" -m qa.web.launch %*

rem Only pause on failure. A clean exit is somebody closing the window on
rem purpose, and making them press a key for that is noise.
if errorlevel 1 (
  echo.
  echo   The interface stopped with an error. The lines above say why.
  echo.
  pause
)
endlocal
