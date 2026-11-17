# Build the Windows desktop app into dist\WvWAnalyzer\ (run from the repo root in PowerShell).
# Requires: uv (https://docs.astral.sh/uv/) and Node.js 22.17+ (or -SkipFrontend with an existing
# frontend\build, e.g. built in WSL - it's plain static files).
param([switch]$SkipFrontend)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Step($name, [scriptblock]$block) {
    Write-Host "== $name"
    & $block
    if ($LASTEXITCODE -ne 0) { throw "$name failed (exit code $LASTEXITCODE)" }
}

Step "Python deps" { uv sync }

if ($SkipFrontend) {
    if (-not (Test-Path frontend\build\index.html)) { throw "frontend\build missing - build it first" }
    Write-Host "== Frontend: using existing frontend\build"
} else {
    Push-Location frontend
    try {
        Step "npm ci" { npm ci }
        Step "Frontend build" { npm run build }
    } finally { Pop-Location }
}

Step "Elite Insights CLI" { uv run python scripts/setup_tools.py }
Step "PyInstaller" {
    uv run --with pyinstaller pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/wvw_analyzer.spec
}

Write-Host "== Bundle tools"
New-Item -ItemType Directory -Force dist\WvWAnalyzer\bin | Out-Null
Copy-Item -Recurse -Force bin\GW2EI dist\WvWAnalyzer\bin\

Write-Host "Done: dist\WvWAnalyzer\WvWAnalyzer.exe"
Write-Host "User data (config, database, parsed logs, LLM model) goes to %LOCALAPPDATA%\WvWAnalyzer"
