# CaseMind Defense — one-shot setup for a clean Windows machine.
# Run from the repo root:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# Creates both venvs, installs dependencies, checks Tesseract/Ollama,
# and puts a "CaseMind Defense" shortcut on the Desktop.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Step($msg) { Write-Host "`n=== $msg" -ForegroundColor Cyan }

# --- 1. Python ---------------------------------------------------------
Step "Checking Python"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python not found - installing via winget..."
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
python --version

# --- 2. Backend venv ----------------------------------------------------
Step "Backend dependencies (this includes ML models tooling - a few minutes)"
if (-not (Test-Path "$root\backend\.venv")) { python -m venv "$root\backend\.venv" }
& "$root\backend\.venv\Scripts\python.exe" -m pip install --upgrade pip -q
& "$root\backend\.venv\Scripts\python.exe" -m pip install -r "$root\backend\requirements.txt" -q

# --- 3. Desktop venv ----------------------------------------------------
Step "Desktop dependencies"
if (-not (Test-Path "$root\desktop\.venv")) { python -m venv "$root\desktop\.venv" }
& "$root\desktop\.venv\Scripts\python.exe" -m pip install --upgrade pip -q
& "$root\desktop\.venv\Scripts\python.exe" -m pip install -r "$root\desktop\requirements.txt" -q

# --- 4. Tesseract OCR (Hebrew) -----------------------------------------
Step "Checking Tesseract OCR"
$tesseract = @(
    "$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
    "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $tesseract) {
    Write-Host "Tesseract not found - installing (UB Mannheim build)..."
    winget install --id UB-Mannheim.TesseractOCR -e --accept-source-agreements --accept-package-agreements
    Write-Host "NOTE: verify the Hebrew language pack (heb) is installed; rerun the installer and tick 'Hebrew' under additional languages if OCR of Hebrew scans fails." -ForegroundColor Yellow
} else { Write-Host "Found: $tesseract" }

# --- 5. Ollama (optional, for AI answers) -------------------------------
Step "Checking Ollama (local AI)"
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) { $ollama = Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
if (-not $ollama) {
    $answer = Read-Host "Ollama not found. Install it for AI answers? (y/N)"
    if ($answer -eq "y") {
        winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
        & "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen2.5:3b-instruct
    } else {
        Write-Host "Skipped - the AI page will fall back to citations-only mode." -ForegroundColor Yellow
    }
} else { Write-Host "Ollama found." }

# --- 6. Desktop shortcut -------------------------------------------------
Step "Creating Desktop shortcut"
$pythonw = "$root\desktop\.venv\Scripts\pythonw.exe"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\CaseMind Defense.lnk")
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "-m casemind_desktop.main"
$shortcut.WorkingDirectory = "$root\desktop"
$shortcut.Description = "CaseMind Defense - Investigation Intelligence"
$shortcut.Save()

Step "Done"
Write-Host "Double-click 'CaseMind Defense' on the Desktop to start."
Write-Host "The app starts its own backend; data lives in $root\backend\data"
