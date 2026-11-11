@echo off
rem Builds dist\WTFTD-<version>-windows.exe: a single-file Windows app (Python and UI; game data comes on first launch).
rem Built from a branch other than main, the branch is added to the name: dist\WTFTD-<version>-<branch>-windows.exe.
title WTFTD - build exe
cd /d "%~dp0"
rem The exe carries the Python it is built with: 3.14+ to read the installed game, with tkinter for the overlay
rem (a light Python, like the NuGet package, has no tkinter). Never build with less: the app would lose them silently
set "NEEDS=import compression.zstd, tkinter"
set "PY="
python -c "%NEEDS%" >nul 2>nul && set "PY=python"
if not defined PY py -3.14 -c "%NEEDS%" >nul 2>nul && set "PY=py -3.14"
if not defined PY (echo A full Python 3.14 or newer, with tkinter, is required to build the app: https://www.python.org/downloads/ & pause & exit /b 1)
set "VER="
for /f "delims=" %%v in ('%PY% -c "import wtftd; print(wtftd.__version__)"') do set "VER=%%v"
if not defined VER (echo Could not read the version from wtftd\__init__.py & exit /b 1)
set "BRANCH="
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BRANCH=%%b"
set "NAME=WTFTD-%VER%-windows"
if defined BRANCH if not "%BRANCH%"=="main" if not "%BRANCH%"=="HEAD" set "NAME=WTFTD-%VER%-%BRANCH:/=-%-windows"
if exist ".cache\build-venv\Scripts\python.exe" (
  .cache\build-venv\Scripts\python -c "%NEEDS%" >nul 2>nul || rmdir /s /q .cache\build-venv
)
if not exist ".cache\build-venv\Scripts\python.exe" %PY% -m venv .cache\build-venv
.cache\build-venv\Scripts\python --version
.cache\build-venv\Scripts\python -m pip install -q --upgrade pyinstaller || exit /b 1
.cache\build-venv\Scripts\pyinstaller --noconfirm --clean --onefile --windowed --name "%NAME%" ^
  --icon "%~dp0web\favicon.ico" --add-data "%~dp0web;web" ^
  --distpath dist --workpath .cache\build --specpath .cache\build "%~dp0wtftd_app.py" || exit /b 1
echo.
echo Built dist\%NAME%.exe
