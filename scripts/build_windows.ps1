# Build the Windows app and its installer (run from the repo root in PowerShell).
#   ./scripts/build_windows.ps1                 # full build -> dist\WvWAnalyzer-Setup-<version>.exe
#   ./scripts/build_windows.ps1 -SkipFrontend   # reuse an existing frontend\build (e.g. built in WSL)
#   ./scripts/build_windows.ps1 -NoInstaller    # only dist\WvWAnalyzer\ (no Inno Setup needed)
# The in-game overlay addon is built in WSL (scripts/build_addon.sh); copy bin\addon\ over first.
# Requires: uv, Node.js 22.17+ (unless -SkipFrontend), Inno Setup 6 for the installer
# (winget install JRSoftware.InnoSetup).
param([switch]$SkipFrontend, [switch]$NoInstaller)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Step($name, [scriptblock]$block) {
    Write-Host "== $name"
    & $block
    if ($LASTEXITCODE -ne 0) { throw "$name failed (exit code $LASTEXITCODE)" }
}

$version = (Select-String -Path backend\wvw_analyzer\__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
Write-Host "WvW Analyzer $version"

Step "Python deps" { uv sync }

if (-not (Test-Path bin\addon\WvWAnalyzer.dll)) {
    throw "bin\addon\WvWAnalyzer.dll missing - build it in WSL with scripts/build_addon.sh and copy bin\addon over"
}

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

Step "Elite Insights + .NET runtime" { uv run python scripts/setup_tools.py --dotnet }
Step "PyInstaller" {
    uv run --with pyinstaller pyinstaller --noconfirm --clean --distpath dist --workpath build packaging/wvw_analyzer.spec
}

Write-Host "== Bundle tools"
New-Item -ItemType Directory -Force dist\WvWAnalyzer\bin | Out-Null
Copy-Item -Recurse -Force bin\GW2EI dist\WvWAnalyzer\bin\
Copy-Item -Recurse -Force bin\dotnet dist\WvWAnalyzer\bin\
Copy-Item -Recurse -Force bin\addon dist\WvWAnalyzer\bin\

if ($NoInstaller) {
    Write-Host "Done: dist\WvWAnalyzer\WvWAnalyzer.exe (no installer)"
    exit 0
}

Write-Host "== WebView2 bootstrapper"
New-Item -ItemType Directory -Force build\redist | Out-Null
$wv2 = "build\redist\MicrosoftEdgeWebview2Setup.exe"
if (-not (Test-Path $wv2)) {
    Invoke-WebRequest -UseBasicParsing "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $wv2
}
$sig = Get-AuthenticodeSignature $wv2
if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "O=Microsoft Corporation") {
    Remove-Item $wv2
    throw "WebView2 bootstrapper signature check failed ($($sig.Status))"
}

Write-Host "== Installer"
$iscc = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source,
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found. Install it with: winget install JRSoftware.InnoSetup" }
Step "Inno Setup" { & $iscc /Q "/DAppVersion=$version" packaging\installer.iss }

Write-Host "Done: dist\WvWAnalyzer-Setup-$version.exe"
Write-Host "User data (config, database, parsed logs, LLM model) goes to %LOCALAPPDATA%\WvWAnalyzer"
