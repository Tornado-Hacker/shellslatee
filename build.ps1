#requires -Version 5.1
<#
  Build Shellslatee into a Windows installer.

  Prerequisites:
    - Node.js 20+ and npm
    - Rust (MSVC toolchain) + Visual Studio C++ Build Tools
    - WebView2 runtime (preinstalled on Windows 11, evergreened on 10)
    - The Shellslatee engine on PATH, or SHELLSLATEE_BIN / SHELLSLATEE_REPO set
#>
param(
    [switch]$SkipInstall,
    [switch]$DebugBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Assert-Command($name, $hint) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "Missing '$name'. $hint"
    }
    Write-Host "  ok  $name -> $($cmd.Source)" -ForegroundColor DarkGray
}

Write-Host "`nShellslatee build`n" -ForegroundColor Cyan

Write-Host "Checking toolchain" -ForegroundColor White
Assert-Command node "Install Node.js 20+ from https://nodejs.org"
Assert-Command npm "Install Node.js 20+ from https://nodejs.org"
Assert-Command cargo "Install Rust from https://rustup.rs (choose the MSVC toolchain)"
Assert-Command rustc "Install Rust from https://rustup.rs"

$nodeVersion = (node -p "process.versions.node").Split(".")[0]
if ([int]$nodeVersion -lt 20) { throw "Node 20+ required (found $nodeVersion)." }

$engine = $null
if ($env:SHELLSLATEE_BIN) { $engine = "SHELLSLATEE_BIN=$env:SHELLSLATEE_BIN" }
elseif ($env:SHELLSLATEE_REPO) { $engine = "SHELLSLATEE_REPO=$env:SHELLSLATEE_REPO" }
elseif (Get-Command shellslatee -ErrorAction SilentlyContinue) { $engine = "shellslatee on PATH" }

if (-not $engine) {
    Write-Warning "No Shellslatee engine found. The app will install and run, but the connection screen will ask for one."
    Write-Warning "Install with: python -m pip install shellslatee-engine    (or set SHELLSLATEE_BIN / SHELLSLATEE_REPO)"
} else {
    Write-Host "  ok  engine -> $engine" -ForegroundColor DarkGray
}

if (-not (Test-Path (Join-Path $root "package.json"))) {
    throw "Run this script from the lectren app folder (package.json not found)."
}

if (-not $SkipInstall) {
    Write-Host "`nInstalling frontend dependencies" -ForegroundColor White
    if (Test-Path (Join-Path $root "package-lock.json")) {
        npm ci --no-audit --no-fund
    } else {
        npm install --no-audit --no-fund
    }
}

Write-Host "`nBuilding (this compiles Rust and bundles the installer)" -ForegroundColor White
Write-Host "First run can take 5-15 minutes.`n" -ForegroundColor DarkGray

if ($DebugBuild) {
    npx tauri build --debug
} else {
    npx tauri build
}
if ($LASTEXITCODE -ne 0) { throw "tauri build failed with exit code $LASTEXITCODE" }

# --- optional Authenticode signing -----------------------------------------
# Provide a certificate to sign the app, MSI and NSIS setup. Without one the
# installers stay unsigned and the hashes below are the trust path.
$version = (Get-Content (Join-Path $root "package.json") -Raw | ConvertFrom-Json).version
$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) {
    Write-Host "`nSigning: signtool not found (install the Windows SDK) — installers left unsigned" -ForegroundColor Yellow
} else {
    $certArgs = @()
    if ($env:SHELLSLATEE_CERT_PFX) {
        $certArgs = @("/f", $env:SHELLSLATEE_CERT_PFX)
        if ($env:SHELLSLATEE_CERT_PASSWORD) { $certArgs += @("/p", $env:SHELLSLATEE_CERT_PASSWORD) }
    } elseif ($env:SHELLSLATEE_CERT_THUMBPRINT) {
        $certArgs = @("/sha1", $env:SHELLSLATEE_CERT_THUMBPRINT)
    } else {
        Write-Host "`nSigning: no cert configured (SHELLSLATEE_CERT_PFX or SHELLSLATEE_CERT_THUMBPRINT) — installers left unsigned" -ForegroundColor Yellow
    }
    if ($certArgs.Count -gt 0) {
        $timestamp = "http://timestamp.digicert.com"
        $targets = @(
            (Join-Path $root "src-tauri\target\release\shellslatee-studio.exe"),
            (Join-Path $root "src-tauri\target\release\bundle\msi\Shellslatee_${version}_x64_en-US.msi"),
            (Join-Path $root "src-tauri\target\release\bundle\nsis\Shellslatee_${version}_x64-setup.exe")
        ) | Where-Object { Test-Path $_ }
        foreach ($target in $targets) {
            Write-Host "  sign  $target" -ForegroundColor DarkGray
            & $signtool.Source sign /fd SHA256 /tr $timestamp /td SHA256 @certArgs $target
            if ($LASTEXITCODE -ne 0) { throw "signtool failed on $target" }
        }
    }
}

Write-Host "`nDone. Installers:" -ForegroundColor Green
$bundle = Join-Path $root "src-tauri\target\release\bundle"
if ($DebugBuild) { $bundle = Join-Path $root "src-tauri\target\debug\bundle" }
if (Test-Path $bundle) {
    Get-ChildItem -Path $bundle -Recurse -Include *.msi, *.exe |
        Where-Object { $_.Name -match $version } |
        ForEach-Object {
            Write-Host "  $($_.FullName)" -ForegroundColor Cyan
            Write-Host ("  sha256 {0}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash) -ForegroundColor DarkGray
        }
} else {
    Write-Host "  Look in $bundle" -ForegroundColor Yellow
}

Write-Host "`nReminder: the app spawns the Python engine. Ship it alongside" -ForegroundColor DarkGray
Write-Host "Shellslatee engine (pip install shellslatee-engine) or set SHELLSLATEE_BIN for packaged builds.`n" -ForegroundColor DarkGray
