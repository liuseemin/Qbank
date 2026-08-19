[CmdletBinding()]
param(
    [string]$InstallPath,
    [string]$RepositoryUrl = "https://github.com/liuseemin/Qbank.git"
)

$ErrorActionPreference = "Stop"
$pythonVersion = "3.13.7"

function Refresh-Path {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $env:Path = "$machinePath;$userPath"
}

function Find-Python {
    $script:pythonCommand = $null
    $script:pythonPrefix = @()

    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        & $py.Source -3 --version *> $null
        if ($LASTEXITCODE -eq 0) {
            $script:pythonCommand = $py.Source
            $script:pythonPrefix = @("-3")
            return
        }
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        & $python.Source --version *> $null
        if ($LASTEXITCODE -eq 0) {
            $script:pythonCommand = $python.Source
            return
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

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & $script:gitCommand @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed with exit code $LASTEXITCODE."
    }
}

function Invoke-VenvPython {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & $script:venvPython @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Virtual-environment Python command failed with exit code $LASTEXITCODE."
    }
}

function New-DesktopShortcut {
    param(
        [string]$ProjectPath,
        [string]$PythonPath,
        [string]$QuizScriptPath,
        [string]$QuestionBankPath
    )

    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktopPath "Qbank.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $PythonPath
    $shortcut.Arguments = "`"$QuizScriptPath`" `"$QuestionBankPath`" --open"
    $shortcut.WorkingDirectory = $ProjectPath
    $shortcut.Description = "Qbank online quiz"
    $shortcut.IconLocation = "${PythonPath},0"
    $shortcut.Save()
    return $shortcutPath
}

if ([string]::IsNullOrWhiteSpace($InstallPath)) {
    $defaultPath = Join-Path $HOME "Qbank"
    $InstallPath = Read-Host "Installation folder [$defaultPath]"
    if ([string]::IsNullOrWhiteSpace($InstallPath)) {
        $InstallPath = $defaultPath
    }
}

$InstallPath = [Environment]::ExpandEnvironmentVariables($InstallPath.Trim().Trim('"'))
$InstallPath = [System.IO.Path]::GetFullPath($InstallPath)

Write-Host "[1/6] Checking for Git..."
$git = Get-Command git.exe -ErrorAction SilentlyContinue
if ($null -eq $git) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        throw "Git was not found. Install Git for Windows and run this script again."
    }

    Write-Host "Installing Git for Windows..."
    & $winget.Source install --id Git.Git --exact --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "Git installation failed."
    }
    Refresh-Path
    $git = Get-Command git.exe -ErrorAction SilentlyContinue
}

if ($null -eq $git) {
    throw "Git is still unavailable. Open a new PowerShell window and run this script again."
}
$script:gitCommand = $git.Source

Write-Host "[2/6] Cloning project into $InstallPath..."
if (Test-Path -LiteralPath $InstallPath) {
    $items = @(Get-ChildItem -Force -LiteralPath $InstallPath)
    $gitFolder = Join-Path $InstallPath ".git"
    if ($items.Count -eq 0) {
        Invoke-Git -Arguments @("clone", $RepositoryUrl, $InstallPath)
    } elseif (Test-Path -LiteralPath $gitFolder) {
        Push-Location $InstallPath
        try {
            Invoke-Git -Arguments @("pull", "--ff-only")
        } finally {
            Pop-Location
        }
    } else {
        throw "Installation folder exists and is not empty: $InstallPath"
    }
} else {
    $parent = Split-Path -Parent $InstallPath
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Invoke-Git -Arguments @("clone", $RepositoryUrl, $InstallPath)
}

$quizScript = Join-Path $InstallPath "quiz_web.py"
if (-not (Test-Path -LiteralPath $quizScript)) {
    throw "The project was downloaded, but quiz_web.py was not found."
}
Set-Location -Path $InstallPath

Write-Host "[3/6] Checking for Python..."
Find-Python
if ($null -eq $pythonCommand) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($null -ne $winget) {
        Write-Host "Installing Python 3.13..."
        & $winget.Source install --id Python.Python.3.13 --exact --scope user --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            throw "Python installation failed."
        }
    } else {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($null -eq $curl) {
            throw "Python was not found and curl.exe is unavailable. Install Python 3.13 and run this script again."
        }

        $pythonInstaller = Join-Path $env:TEMP "qbank-python-installer.exe"
        $pythonUrl = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe"
        Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonInstaller -UseBasicParsing
        $process = Start-Process -FilePath $pythonInstaller -ArgumentList @(
            "/quiet",
            "InstallAllUsers=0",
            "PrependPath=1",
            "Include_launcher=1",
            "Include_test=0"
        ) -Wait -PassThru
        Remove-Item -LiteralPath $pythonInstaller -Force -ErrorAction SilentlyContinue
        if ($process.ExitCode -ne 0) {
            throw "Python installation failed with exit code $($process.ExitCode)."
        }
    }
    Refresh-Path
    Find-Python
}

if ($null -eq $pythonCommand) {
    throw "Python is still unavailable. Open a new PowerShell window and run this script again."
}

Write-Host "[4/6] Creating virtual environment..."
Invoke-Python -Arguments @("-m", "venv", ".venv")
$venvPython = Join-Path $InstallPath ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "The virtual environment was not created."
}

Write-Host "[5/6] Installing Python packages..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed."
}
& $venvPython -m pip install -r (Join-Path $InstallPath "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

Write-Host "[6/9] Creating the question-bank folder..."
$jsonDirectory = Join-Path $InstallPath "json"
New-Item -ItemType Directory -Path $jsonDirectory -Force | Out-Null

Write-Host "[7/9] Importing a question-bank PDF (optional)..."
$pdfInput = Read-Host "Enter a PDF file or folder path (leave blank to skip)"
if (-not [string]::IsNullOrWhiteSpace($pdfInput)) {
    $pdfInput = [Environment]::ExpandEnvironmentVariables($pdfInput.Trim().Trim('"'))
    if (-not (Test-Path -LiteralPath $pdfInput)) {
        throw "PDF file or folder not found: $pdfInput"
    }

    $pdfInputPath = (Resolve-Path -LiteralPath $pdfInput).Path
    $pdfToJsonScript = Join-Path $InstallPath "pdftojson.py"
    $fixOptionsScript = Join-Path $InstallPath "check_and_fix_json_options.py"
    $pdfGetImagesScript = Join-Path $InstallPath "pdfgetimg.py"
    $inputItem = Get-Item -LiteralPath $pdfInputPath

    if ($inputItem.PSIsContainer) {
        Invoke-VenvPython -Arguments @($pdfToJsonScript, $pdfInputPath, "-o", $jsonDirectory, "--autoitem")
        $pdfFiles = @(Get-ChildItem -LiteralPath $pdfInputPath -Filter "*.pdf" -File)
    } else {
        $outputJson = Join-Path $jsonDirectory ($inputItem.BaseName + ".json")
        Invoke-VenvPython -Arguments @($pdfToJsonScript, $pdfInputPath, "-o", $outputJson, "--autoitem")
        $pdfFiles = @($inputItem)
    }

    $fixedDirectory = Join-Path $InstallPath ".fixed_json"
    if (Test-Path -LiteralPath $fixedDirectory) {
        Remove-Item -LiteralPath $fixedDirectory -Recurse -Force
    }
    Invoke-VenvPython -Arguments @($fixOptionsScript, $jsonDirectory, "-o", $fixedDirectory)
    Get-ChildItem -LiteralPath $fixedDirectory -Filter "*.json" -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $jsonDirectory $_.Name) -Force
    }
    Remove-Item -LiteralPath $fixedDirectory -Recurse -Force

    Invoke-VenvPython -Arguments @($pdfGetImagesScript, $pdfInputPath)
    foreach ($pdfFile in $pdfFiles) {
        $sourceImages = Join-Path $pdfFile.DirectoryName ($pdfFile.BaseName + "_images")
        $destinationImages = Join-Path $jsonDirectory ($pdfFile.BaseName + "_images")
        if (Test-Path -LiteralPath $sourceImages) {
            if (Test-Path -LiteralPath $destinationImages) {
                Copy-Item -Path (Join-Path $sourceImages "*") -Destination $destinationImages -Recurse -Force
                Remove-Item -LiteralPath $sourceImages -Recurse -Force
            } else {
                Move-Item -LiteralPath $sourceImages -Destination $destinationImages
            }
        }
    }

    Write-Host "PDF question bank imported into $jsonDirectory"
}

Write-Host "[8/9] Configuring Gemini AI (optional)..."
$apiKey = Read-Host "Enter Gemini API Key (leave blank to disable AI)"
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", $apiKey, "User")

Write-Host "[9/9] Creating desktop shortcut..."
$shortcutPath = New-DesktopShortcut `
    -ProjectPath $InstallPath `
    -PythonPath $venvPython `
    -QuizScriptPath $quizScript `
    -QuestionBankPath $jsonDirectory

Write-Host ""
Write-Host "Installation completed: $InstallPath"
Write-Host "Put JSON question banks in: $jsonDirectory"
Write-Host "Desktop shortcut created: $shortcutPath"
Write-Host "Start Qbank with:"
Write-Host "  cd `"$InstallPath`""
Write-Host '  .venv\Scripts\python.exe quiz_web.py .\json --open'
