@echo off
rem Double-click this file to start Campaign Studio.
rem It runs start.py in this folder: the first time it sets up what it needs
rem (about 30 seconds), then it opens the app in your browser.
rem Keep this window open while you use the app. Closing it stops the app.

cd /d "%~dp0"

rem Prefer the "py" launcher that python.org installs; fall back to "python".
rem Windows has a "python" placeholder that only opens the Microsoft Store, so
rem check that it really runs before using it.
set "PYTHON="
py -3 --version >nul 2>&1 && set "PYTHON=py -3"
if not defined PYTHON python --version >nul 2>&1 && set "PYTHON=python"

if not defined PYTHON (
  echo.
  echo Campaign Studio needs Python 3, and this computer doesn't have it.
  echo Opening the download page. Install it, tick "Add python.exe to PATH",
  echo then double-click this file again.
  echo.
  if /i not "%~1"=="--check" (
    start "" https://www.python.org/downloads/
    pause
  )
  exit /b 1
)

%PYTHON% start.py %*
set "STATUS=%ERRORLEVEL%"
if /i not "%~1"=="--check" if not "%STATUS%"=="0" (
  echo.
  pause
)
exit /b %STATUS%
