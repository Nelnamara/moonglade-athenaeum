@echo off
rem ---------------------------------------------------------------------------------------
rem  Install Moonglade.cmd -- the first-time setup for a Windows PC that may have no Python.
rem
rem  Double-click it once. It finds Python 3.10 or newer (and installs one for your account
rem  only, no administrator needed, if there is none), installs the packages Moonglade needs,
rem  then starts Moonglade. After that, just double-click "Moonglade Launcher".
rem
rem  "Install Moonglade.cmd --check" only reports what it found and what it would do; it
rem  installs and starts nothing (the tests use it).
rem
rem  This is plain Windows batch, so it runs with no Python at all. Keep it ASCII-only: a
rem  batch file reads in the console's code page. Keep its CRLF line endings too
rem  (.gitattributes pins them): labels and goto misbehave with bare LF.
rem ---------------------------------------------------------------------------------------
setlocal EnableExtensions
title Install Moonglade
cd /d "%~dp0"

set "CHECK=0"
if /i "%~1"=="--check" set "CHECK=1"

set "PYEXE="
set "PYVER="
set "OLDVER="
set "INSTALLED="
set "PROBE=%TEMP%\moonglade_python_probe.txt"

echo.
echo  Moonglade - first-time setup
echo  ----------------------------
if "%CHECK%"=="1" echo  [check] Only reporting what I found and what I would do. Nothing is installed or started.
echo  Folder: "%~dp0"
echo.

if not exist "Moonglade Launcher.pyw" goto :wrong_folder
if not exist "requirements.txt" goto :wrong_folder

rem ---- Step 1: find a Python 3.10 or newer ------------------------------------------------
echo  Step 1 of 4: Looking for Python 3.10 or newer...
call :find_python
if defined PYEXE goto :python_ready

if defined OLDVER echo  Found Python %OLDVER%, but Moonglade needs 3.10 or newer.
echo  No usable Python 3.10 or newer was found on this PC.
echo  The "python" that opens the Microsoft Store does not count: it is not Python.
where winget >nul 2>&1
if errorlevel 1 goto :no_winget

if "%CHECK%"=="1" goto :check_would_install_python

rem ---- Step 2: install Python for this user only (no administrator needed) -----------------
echo.
echo  Step 2 of 4: Installing Python 3.13 for your account only (no administrator needed)...
echo  Windows may show its own progress or ask you to agree to terms. This can take a few minutes.
echo.
winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
echo.
echo  Looking for the Python that was just installed...
call :find_python
if not defined PYEXE goto :python_install_failed
set "INSTALLED=1"

:python_ready
echo  Found Python %PYVER%:
echo    "%PYEXE%"
if "%CHECK%"=="1" goto :check_report
echo.
if defined INSTALLED echo  Step 2 of 4: Python is installed.
if not defined INSTALLED echo  Step 2 of 4: Python is ready, nothing to install.

rem ---- Step 3: install the packages ---------------------------------------------------------
echo.
echo  Step 3 of 4: Installing the packages Moonglade needs (this can take a minute or two)...
echo  Running: "%PYEXE%" -m pip install -r requirements.txt
echo.
"%PYEXE%" -m pip install -r requirements.txt
if errorlevel 1 goto :pip_failed
echo.
echo  The packages are installed.

rem ---- Step 4: start Moonglade ---------------------------------------------------------------
echo.
echo  Step 4 of 4: Starting Moonglade...
for %%I in ("%PYEXE%") do set "PYDIR=%%~dpI"
set "PYW=%PYDIR%pythonw.exe"
if not exist "%PYW%" set "PYW=%PYEXE%"
start "" "%PYW%" "%~dp0Moonglade Launcher.pyw"
echo.
echo  Moonglade is opening in your browser.
echo  Next time, just double-click Moonglade Launcher.
echo.
echo  This window closes in a few seconds.
timeout /t 8 >nul 2>&1
exit /b 0

rem ---- --check: report only ------------------------------------------------------------------
:check_report
echo  [check] Would install the packages with: "%PYEXE%" -m pip install -r requirements.txt
for %%I in ("%PYEXE%") do set "PYDIR=%%~dpI"
set "PYW=%PYDIR%pythonw.exe"
if not exist "%PYW%" set "PYW=%PYEXE%"
echo  [check] Would start Moonglade with: "%PYW%" "%~dp0Moonglade Launcher.pyw"
echo  [check] Done. Nothing was installed or started.
exit /b 0

:check_would_install_python
echo  [check] winget is available, so I would install Python for your account only (no administrator):
echo  [check]   winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
echo  [check] Then I would install the packages with that Python and start Moonglade.
echo  [check] Done. Nothing was installed or started.
exit /b 0

:check_no_winget
echo  [check] winget was not found, so I would open https://www.python.org/downloads/ and stop.
echo  [check] Done. Nothing was installed or started.
exit /b 0

rem ---- things that go wrong ---------------------------------------------------------------------
:wrong_folder
echo  This setup file has to stay in the Moonglade folder, next to
echo  "Moonglade Launcher.pyw" and requirements.txt. It cannot see them here.
echo  Move it back into the Moonglade folder and double-click it again.
echo  If you opened it from inside the downloaded .zip, extract the whole zip first
echo  (right-click the zip, Extract All), then double-click it from the extracted folder.
goto :fail

:no_winget
if "%CHECK%"=="1" goto :check_no_winget
echo.
echo  This PC does not have winget, which is what installs Python for you.
call :python_org_steps
echo  Opening the Python download page now...
start "" "https://www.python.org/downloads/"
goto :fail

:python_install_failed
echo.
echo  The Python install did not finish, so Moonglade cannot be set up yet.
call :python_org_steps
echo  Opening the Python download page now...
start "" "https://www.python.org/downloads/"
goto :fail

:pip_failed
echo.
echo  Installing the packages did not work. The messages above say why.
echo  To try it by hand, open Command Prompt in this folder and run:
echo.
echo    "%PYEXE%" -m pip install -r requirements.txt
echo.
echo  If the messages say there is no pip, run this first:
echo.
echo    "%PYEXE%" -m ensurepip
echo.
echo  A network problem is the usual cause: check your connection and double-click this file again.
goto :fail

:fail
echo.
if "%CHECK%"=="1" exit /b 1
pause
exit /b 1

rem ---- subroutines -------------------------------------------------------------------------------
:python_org_steps
echo  To install Python yourself:
echo    1. Download the newest Python 3 installer from https://www.python.org/downloads/
echo    2. Run it and tick "Add python.exe to PATH" on its first screen.
echo    3. Close this window, then double-click Install Moonglade again.
exit /b 0

:find_python
rem Sets PYEXE (the real python.exe, from sys.executable) and PYVER for the first usable
rem Python 3.10 or newer: the py launcher, python on PATH, then the places a per-user install
rem puts it (this window's PATH is stale right after an install, so PATH is not relied on).
set "PYEXE="
call :try py -3
if not defined PYEXE call :try python
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" call :try "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" call :try "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" -3
if not defined PYEXE if exist "%SystemRoot%\py.exe" call :try "%SystemRoot%\py.exe" -3
exit /b 0

:try
rem Runs the command given (%*) and counts it only if it prints sys.executable and exits 0
rem for a Python 3.10 or newer. The Microsoft Store "python" stub only opens the Store: it
rem prints no interpreter path and exits nonzero, so it never counts. The path is written in
rem the console's OEM code page, which is what "for /f" reads the file back in, so a user name
rem with an accent in it still gives a path that exists.
set "TRYEXE="
set "TRYVER="
del "%PROBE%" >nul 2>&1
%* -c "import sys; sys.stdout.reconfigure(encoding='oem'); print(sys.executable); print(sys.version.split()[0]); sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >"%PROBE%" 2>nul
set "RC=%errorlevel%"
if not exist "%PROBE%" exit /b 0
for /f "usebackq delims=" %%L in ("%PROBE%") do if not defined TRYEXE (set "TRYEXE=%%L") else set "TRYVER=%%L"
del "%PROBE%" >nul 2>&1
if not defined TRYEXE exit /b 0
if not exist "%TRYEXE%" exit /b 0
if not "%RC%"=="0" set "OLDVER=%TRYVER%"
if not "%RC%"=="0" exit /b 0
set "PYEXE=%TRYEXE%"
set "PYVER=%TRYVER%"
exit /b 0
