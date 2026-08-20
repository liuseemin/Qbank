[CmdletBinding()]
param(
    [string]$InstallPath,
    [string]$RepositoryUrl = "https://github.com/liuseemin/Qbank.git"
)

$ErrorActionPreference = "Stop"

function Refresh-Path {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $env:Path = "$machinePath;$userPath"
}

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & $script:gitCommand @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed with exit code $LASTEXITCODE."
    }
}

function Invoke-Uv {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & $script:uvCommand @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "uv command failed with exit code $LASTEXITCODE."
    }
}

function Find-Uv {
    $uv = Get-Command uv.exe -ErrorAction SilentlyContinue
    if ($null -ne $uv) {
        $script:uvCommand = $uv.Source
        return $true
    }

    $candidate = Join-Path $HOME ".local\bin\uv.exe"
    if (Test-Path -LiteralPath $candidate) {
        $script:uvCommand = $candidate
        return $true
    }

    return $false
}

function Install-Uv {
    if (Find-Uv) {
        return
    }

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($null -ne $winget) {
        Write-Host "Installing uv with winget..."
        & $winget.Source install --id astral-sh.uv --exact --scope user --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) {
            Refresh-Path
            if (Find-Uv) { return }
        }
    }

    Write-Host "Installing uv with the official installer..."
    $uvInstaller = Join-Path $env:TEMP "qbank-uv-install.ps1"
    Invoke-WebRequest -Uri "https://astral.sh/uv/install.ps1" -OutFile $uvInstaller -UseBasicParsing
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $uvInstaller
    $installerExitCode = $LASTEXITCODE
    Remove-Item -LiteralPath $uvInstaller -Force -ErrorAction SilentlyContinue
    if ($installerExitCode -ne 0) {
        throw "uv installation failed with exit code $installerExitCode."
    }

    Refresh-Path
    if (-not (Find-Uv)) {
        throw "uv was installed but could not be found. Open a new PowerShell window and run this script again."
    }
}

function New-LauncherScript {
    param(
        [string]$ProjectPath,
        [string]$GitPath,
        [string]$UvPath,
        [string]$QuizScriptPath,
        [string]$QuestionBankPath
    )

    $launcherPath = Join-Path $ProjectPath "qbank_start.ps1"
    $launcherContent = @"
`$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $(ConvertTo-Json $ProjectPath -Compress)
& $(ConvertTo-Json $GitPath -Compress) pull --ff-only
if (`$LASTEXITCODE -ne 0) {
    Write-Warning "Git pull failed with exit code `$LASTEXITCODE. Starting with the current version."
}
& $(ConvertTo-Json $UvPath -Compress) sync
if (`$LASTEXITCODE -ne 0) {
    Write-Warning "uv sync failed with exit code `$LASTEXITCODE. Starting with the current environment."
}
& $(ConvertTo-Json $UvPath -Compress) run --project $(ConvertTo-Json $ProjectPath -Compress) python $(ConvertTo-Json $QuizScriptPath -Compress) $(ConvertTo-Json $QuestionBankPath -Compress) --open
exit `$LASTEXITCODE
"@
    Set-Content -LiteralPath $launcherPath -Value $launcherContent -Encoding UTF8
    return $launcherPath
}

function New-DesktopShortcut {
    param(
        [string]$ProjectPath,
        [string]$GitPath,
        [string]$UvPath,
        [string]$QuizScriptPath,
        [string]$QuestionBankPath
    )

    $launcherPath = New-LauncherScript `
        -ProjectPath $ProjectPath `
        -GitPath $GitPath `
        -UvPath $UvPath `
        -QuizScriptPath $QuizScriptPath `
        -QuestionBankPath $QuestionBankPath
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktopPath "Qbank.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = (Get-Command powershell.exe).Source
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$launcherPath`""
    $shortcut.WorkingDirectory = $ProjectPath
    $shortcut.Description = "Qbank online quiz"
    $shortcut.IconLocation = "${UvPath},0"
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

Write-Host "[1/8] Checking for Git..."
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

Write-Host "[2/8] Cloning project into $InstallPath..."
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
$pyproject = Join-Path $InstallPath "pyproject.toml"
if (-not (Test-Path -LiteralPath $quizScript)) {
    throw "The project was downloaded, but quiz_web.py was not found."
}
if (-not (Test-Path -LiteralPath $pyproject)) {
    throw "The project was downloaded, but pyproject.toml was not found."
}
Set-Location -Path $InstallPath

Write-Host "[3/8] Checking for uv..."
Install-Uv

Write-Host "[4/8] Synchronizing the uv environment..."
Invoke-Uv -Arguments @("sync")

$jsonDirectory = Join-Path $InstallPath "json"
Write-Host "[5/8] Creating the question-bank folder..."
New-Item -ItemType Directory -Path $jsonDirectory -Force | Out-Null

Write-Host "[6/8] Importing a question-bank PDF (optional)..."
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
        Invoke-Uv -Arguments @("run", "python", $pdfToJsonScript, $pdfInputPath, "-o", $jsonDirectory, "--autoitem")
        $pdfFiles = @(Get-ChildItem -LiteralPath $pdfInputPath -Filter "*.pdf" -File)
    } else {
        $outputJson = Join-Path $jsonDirectory ($inputItem.BaseName + ".json")
        Invoke-Uv -Arguments @("run", "python", $pdfToJsonScript, $pdfInputPath, "-o", $outputJson, "--autoitem")
        $pdfFiles = @($inputItem)
    }

    $fixedDirectory = Join-Path $InstallPath ".fixed_json"
    if (Test-Path -LiteralPath $fixedDirectory) {
        Remove-Item -LiteralPath $fixedDirectory -Recurse -Force
    }
    Invoke-Uv -Arguments @("run", "python", $fixOptionsScript, $jsonDirectory, "-o", $fixedDirectory)
    Get-ChildItem -LiteralPath $fixedDirectory -Filter "*.json" -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $jsonDirectory $_.Name) -Force
    }
    Remove-Item -LiteralPath $fixedDirectory -Recurse -Force

    Invoke-Uv -Arguments @("run", "python", $pdfGetImagesScript, $pdfInputPath)
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
}

Write-Host "[7/8] Configuring Gemini AI (optional)..."
$apiKey = Read-Host "Enter Gemini API Key (leave blank to disable AI)"
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", $apiKey, "User")

Write-Host "[8/8] Creating desktop shortcut..."
$shortcutPath = New-DesktopShortcut `
    -ProjectPath $InstallPath `
    -GitPath $script:gitCommand `
    -UvPath $script:uvCommand `
    -QuizScriptPath $quizScript `
    -QuestionBankPath $jsonDirectory

Write-Host ""
Write-Host "Installation completed: $InstallPath"
Write-Host "Put JSON question banks in: $jsonDirectory"
Write-Host "Desktop shortcut created: $shortcutPath"
Write-Host "Shortcut runs git pull before starting Qbank."
