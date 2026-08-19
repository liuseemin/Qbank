[CmdletBinding()]
param(
    [string]$InstallPath,
    [string]$RepositoryUrl = "https://github.com/liuseemin/Qbank.git"
)

$ErrorActionPreference = "Stop"
$pythonVersion = "3.13.7"

function Find-Python {
    $script:pythonCommand = $null
    $script:pythonPrefix = @()
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        try {
            & $py.Source -3 --version *> $null
            if ($LASTEXITCODE -eq 0) { $script:pythonCommand = $py.Source; $script:pythonPrefix = @("-3"); return }
        } catch { }
    }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        try {
            & $python.Source --version *> $null
            if ($LASTEXITCODE -eq 0) { $script:pythonCommand = $python.Source; return }
        } catch { }
    }
}

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $script:pythonCommand @script:pythonPrefix @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python command failed with exit code $LASTEXITCODE." }
}

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $script:gitCommand @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Git command failed with exit code $LASTEXITCODE." }
}

function Invoke-VenvPython {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $script:venvPython @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Virtual-environment Python command failed with exit code $LASTEXITCODE." }
}

function Refresh-UserPath {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $env:Path = "$machinePath;$userPath"
}

function New-DesktopShortcut {
    param([string]$ProjectPath, [string]$PythonPath, [string]$QuizScriptPath, [string]$QuestionBankPath)
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktopPath "Qbank.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $PythonPath
    $shortcut.Arguments = "`"$QuizScriptPath`" `"$QuestionBankPath`" --open"
    $shortcut.WorkingDirectory = $ProjectPath
    $shortcut.Description = "啟動 Qbank 線上出題機"
    $shortcut.IconLocation = "$PythonPath,0"
    $shortcut.Save()
    return $shortcutPath
}

if ([string]::IsNullOrWhiteSpace($InstallPath)) {
    $defaultInstallPath = Join-Path $HOME "Qbank"
    $InstallPath = Read-Host "Installation folder [$defaultInstallPath]"
    if ([string]::IsNullOrWhiteSpace($InstallPath)) { $InstallPath = $defaultInstallPath }
}
$InstallPath = [Environment]::ExpandEnvironmentVariables($InstallPath)
$InstallPath = [System.IO.Path]::GetFullPath($InstallPath)

Write-Host "[1/9] Checking for Git..."
$git = Get-Command git.exe -ErrorAction SilentlyContinue
if ($null -eq $git) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($null -eq $winget) { throw "Git and winget were not found. Install Git for Windows, then run this script again." }
    & $winget.Source install --id Git.Git --exact --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Git installation through winget failed." }
    Refresh-UserPath
    $git = Get-Command git.exe -ErrorAction SilentlyContinue
}
if ($null -eq $git) { throw "Git is still unavailable. Open a new PowerShell window and run this script again." }
$script:gitCommand = $git.Source

Write-Host "[2/9] Cloning Qbank into $InstallPath..."
if (Test-Path -LiteralPath $InstallPath) {
    $entries = @(Get-ChildItem -Force -LiteralPath $InstallPath)
    $gitDirectory = Join-Path $InstallPath ".git"
    if ($entries.Count -eq 0) {
        Invoke-Git -Arguments @("clone", $RepositoryUrl, $InstallPath)
    } elseif (Test-Path -LiteralPath $gitDirectory) {
        Push-Location $InstallPath
        try { Invoke-Git -Arguments @("pull", "--ff-only") } finally { Pop-Location }
    } else {
        throw "Installation folder exists and is not empty: $InstallPath"
    }
} else {
    $parent = Split-Path -Parent $InstallPath
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    Invoke-Git -Arguments @("clone", $RepositoryUrl, $InstallPath)
}
if (-not (Test-Path (Join-Path $InstallPath "quiz_web.py"))) { throw "The cloned repository does not contain quiz_web.py." }
Set-Location -Path $InstallPath

Write-Host "[3/9] Checking for Python..."
Find-Python
if ($null -eq $pythonCommand) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($null -ne $winget) {
        & $winget.Source install --id Python.Python.3.13 --exact --scope user --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "Python installation through winget failed." }
    } else {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($null -eq $curl) { throw "Neither Python nor winget/curl.exe is available. Install Python 3.13 and run this script again." }
        $installer = Join-Path $env:TEMP "qbank-python-installer.exe"
        $installerUrl = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe"
        Invoke-WebRequest -Uri $installerUrl -OutFile $installer -UseBasicParsing
        $process = Start-Process -FilePath $installer -ArgumentList @("/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1", "Include_test=0") -Wait -PassThru
        Remove-Item -Path $installer -Force -ErrorAction SilentlyContinue
        if ($process.ExitCode -ne 0) { throw "The official Python installer failed with exit code $($process.ExitCode)." }
    }
    Refresh-UserPath
    Find-Python
}
if ($null -eq $pythonCommand) { throw "Python is still unavailable. Open a new PowerShell window and run this script again." }

Write-Host "[4/9] Creating the virtual environment..."
Invoke-Python -Arguments @("-m", "venv", ".venv")
$script:venvPython = Join-Path $InstallPath ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "The virtual environment was not created successfully." }

Write-Host "[5/9] Installing project dependencies..."
Invoke-VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
Invoke-VenvPython -Arguments @("-m", "pip", "install", "-r", (Join-Path $InstallPath "requirements.txt"))

Write-Host "[6/9] Creating the question-bank folder..."
$jsonDirectory = Join-Path $InstallPath "json"
New-Item -ItemType Directory -Path $jsonDirectory -Force | Out-Null

Write-Host "[7/9] Importing a question-bank PDF (optional)..."
$pdfInput = Read-Host "Enter a PDF file or folder path (leave blank to skip)"
if (-not [string]::IsNullOrWhiteSpace($pdfInput)) {
    $pdfInput = [Environment]::ExpandEnvironmentVariables($pdfInput.Trim().Trim('"'))
    if (-not (Test-Path -LiteralPath $pdfInput)) { throw "PDF file or folder not found: $pdfInput" }
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
    if (Test-Path $fixedDirectory) { Remove-Item $fixedDirectory -Recurse -Force }
    Invoke-VenvPython -Arguments @($fixOptionsScript, $jsonDirectory, "-o", $fixedDirectory)
    Get-ChildItem -LiteralPath $fixedDirectory -Filter "*.json" -File | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $jsonDirectory $_.Name) -Force
    }
    Remove-Item $fixedDirectory -Recurse -Force
    Invoke-VenvPython -Arguments @($pdfGetImagesScript, $pdfInputPath)
    foreach ($pdfFile in $pdfFiles) {
        $sourceImages = Join-Path $pdfFile.DirectoryName ($pdfFile.BaseName + "_images")
        $destinationImages = Join-Path $jsonDirectory ($pdfFile.BaseName + "_images")
        if (Test-Path $sourceImages) {
            if (Test-Path $destinationImages) {
                Copy-Item (Join-Path $sourceImages "*") $destinationImages -Recurse -Force
                Remove-Item $sourceImages -Recurse -Force
            } else {
                Move-Item $sourceImages $destinationImages
            }
        }
    }
}

Write-Host "[8/9] Configuring Gemini AI (optional)..."
$geminiApiKey = Read-Host "Enter Gemini API Key (leave blank to disable AI)"
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", $geminiApiKey, "User")
$env:GEMINI_API_KEY = $geminiApiKey

Write-Host "[9/9] Creating a desktop shortcut..."
$shortcutPath = New-DesktopShortcut -ProjectPath $InstallPath -PythonPath $venvPython -QuizScriptPath (Join-Path $InstallPath "quiz_web.py") -QuestionBankPath $jsonDirectory
Write-Host ""
Write-Host "Installation completed at: $InstallPath"
Write-Host "Put question-bank JSON files in: $jsonDirectory"
Write-Host "Desktop shortcut created at: $shortcutPath"
Write-Host "Open a new PowerShell window, then run:"
Write-Host "  cd `"$InstallPath`""
Write-Host '  .venv\Scripts\python.exe quiz_web.py .\json --open'
