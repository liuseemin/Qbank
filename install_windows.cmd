@echo off
setlocal EnableExtensions

cd /d "%~dp0"
set "PYTHON_CMD="
set "PYTHON_VERSION=3.13.7"

echo [1/5] Checking for Python...
where py >nul 2>&1
if not errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        python --version >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=python"
    )
)

if not defined PYTHON_CMD (
    echo Python was not found. Trying winget...
    where winget >nul 2>&1
    if not errorlevel 1 (
        winget install --id Python.Python.3.13 --exact --scope user --accept-package-agreements --accept-source-agreements
    ) else (
        echo winget was not found. Trying the official Python installer...
        where curl.exe >nul 2>&1
        if errorlevel 1 (
            echo ERROR: Neither winget nor curl.exe is available.
            echo Install Python 3.13 from https://www.python.org/downloads/windows/ and run this script again.
            exit /b 1
        )
        set "PYTHON_INSTALLER=%TEMP%\qbank-python-installer.exe"
        curl.exe -L --fail --output "%PYTHON_INSTALLER%" "https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-amd64.exe"
        if errorlevel 1 (
            echo ERROR: Could not download Python.
            exit /b 1
        )
        "%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
        if errorlevel 1 (
            echo ERROR: Python installation failed.
            exit /b 1
        )
        del /q "%PYTHON_INSTALLER%" >nul 2>&1
    )
    set "PATH=%LocalAppData%\Programs\Python\Python313;%LocalAppData%\Programs\Python\Python313\Scripts;%PATH%"
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3"
    if not defined PYTHON_CMD (
        python --version >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=python"
    )
)

if not defined PYTHON_CMD (
    echo ERROR: Python is still unavailable. Open a new terminal and run this script again.
    exit /b 1
)

echo [2/5] Creating the virtual environment...
%PYTHON_CMD% -m venv .venv
if errorlevel 1 (
    echo ERROR: Could not create .venv.
    exit /b 1
)

echo [3/5] Upgrading pip...
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 (
    echo ERROR: pip upgrade failed.
    exit /b 1
)

echo [4/5] Installing project dependencies...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Dependency installation failed.
    exit /b 1
)

echo [5/5] Configuring Gemini AI (optional)...
if not exist json mkdir json
set "GEMINI_API_KEY="
set /p "GEMINI_API_KEY=Enter Gemini API Key (leave blank to disable AI): "
setx GEMINI_API_KEY "%GEMINI_API_KEY%" >nul

echo.
echo Installation completed.
echo Open a new terminal, then run:
echo   .venv\Scripts\python.exe quiz_web.py "C:\path\to\question_banks" --open
echo.
echo Put question-bank JSON files in the json folder, or pass another folder path.
echo GEMINI_API_KEY is available in new terminals.
pause
exit /b 0
