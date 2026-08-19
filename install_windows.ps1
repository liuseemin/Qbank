[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$pythonCommand = $null
$pythonPrefix = @()
$pythonVersion = "3.13.7"

function Find-Python {
    $script:pythonCommand = $null
    $script:pythonPrefix = @()

    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        try {
            & $py.Source -3 --version *> $null
            if ($LASTEXITCODE -eq 0) {
                $script:pythonCommand = $py.Source
                $script:pythonPrefix = @("-3")
                return
            }
        } catch {
        }
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        try {
            & $python.Source --version *> $null
            if ($LASTEXITCODE -eq 0) {
                $script:pythonCommand = $python.Source
                $script:pythonPrefix = @()
                return
            }
        } catch {
        }
    }
}

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & $script:pythonCommand @script:pythonPrefix @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

Write-Host "[1/5] Checking for Python..."
Find-Python

if ($null -eq $pythonCommand) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($null -ne $winget) {
        Write-Host "Python was not found. Installing with winget..."
        & $winget.Source install --id Python.Python.3.13 --exact --scope user --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            throw "Python installation through winget failed."
        }
    } else {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($null -eq $curl) {
            throw "Neither winget nor curl.exe is available. Install Python 3.13 and run this script again."
        }

        Write-Host "winget was not found. Downloading the official Python installer..."
        $installer = Join-Path $env:TEMP "qbank-python-installer.exe"
        $installerUrl = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe"
        Invoke-WebRequest -Uri $installerUrl -OutFile $installer -UseBasicParsing
        $process = Start-Process -FilePath $installer -ArgumentList @(
            "/quiet",
            "InstallAllUsers=0",
            "PrependPath=1",
            "Include_launcher=1",
            "Include_test=0"
        ) -Wait -PassThru
        Remove-Item -Path $installer -Force -ErrorAction SilentlyContinue
        if ($process.ExitCode -ne 0) {
            throw "The official Python installer failed with exit code $($process.ExitCode)."
        }
    }

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $env:Path = "$machinePath;$userPath"
    Find-Python
}

if ($null -eq $pythonCommand) {
    throw "Python is still unavailable. Open a new PowerShell window and run this script again."
}

Write-Host "[2/5] Creating the virtual environment..."
Invoke-Python -Arguments @("-m", "venv", ".venv")

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "The virtual environment was not created successfully."
}

Write-Host "[3/5] Upgrading pip..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed."
}

Write-Host "[4/5] Installing project dependencies..."
& $venvPython -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

Write-Host "[5/5] Configuring Gemini AI (optional)..."
$jsonDirectory = Join-Path $PSScriptRoot "json"
New-Item -ItemType Directory -Path $jsonDirectory -Force | Out-Null
$geminiApiKey = Read-Host "Enter Gemini API Key (leave blank to disable AI)"
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", $geminiApiKey, "User")
$env:GEMINI_API_KEY = $geminiApiKey

Write-Host ""
Write-Host "Installation completed."
Write-Host "Open a new PowerShell window, then run:"
Write-Host '  .venv\Scripts\python.exe quiz_web.py "C:\path\to\question_banks" --open'
Write-Host ""
Write-Host "Put question-bank JSON files in the json folder, or pass another folder path."
Write-Host "GEMINI_API_KEY is available in new PowerShell windows."
Read-Host "Press Enter to close"
