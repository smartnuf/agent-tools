[CmdletBinding()]
param(
    [switch]$InstallUv,
    [switch]$InstallNativeTools,
    [switch]$AddToPath
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

function Assert-NativeSuccess {
    param([Parameter(Mandatory)][string]$Operation)
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed with exit code $LASTEXITCODE."
    }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    if (-not $InstallUv) {
        throw 'uv is not installed. Re-run with -InstallUv, or install uv yourself.'
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'WinGet is required for automatic uv installation.'
    }
    winget install --id astral-sh.uv -e --accept-package-agreements --accept-source-agreements
    Assert-NativeSuccess 'uv installation'
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
}

if ($InstallNativeTools) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'WinGet is required for automatic native-tool installation.'
    }
    if (-not (Get-Command pdfinfo -ErrorAction SilentlyContinue)) {
        winget install --id oschwartz10612.Poppler -e --accept-package-agreements --accept-source-agreements
        Assert-NativeSuccess 'Poppler installation'
    }
    if (-not (Get-Command gswin64c,gswin32c -ErrorAction SilentlyContinue)) {
        winget install --id ArtifexSoftware.GhostScript -e --accept-package-agreements --accept-source-agreements
        Assert-NativeSuccess 'Ghostscript installation'
    }
}

$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    & uv venv (Join-Path $Root '.venv') --python 3.11
    Assert-NativeSuccess 'virtual environment creation'
}
& uv pip install --python $Python -r (Join-Path $Root 'requirements.txt') -e $Root
Assert-NativeSuccess 'Python package installation'

if ($AddToPath) {
    & (Join-Path $PSScriptRoot 'path.ps1') -Apply
}

Write-Host "Ready. Run $(Join-Path $Root 'bin\agent-tools.cmd') doctor"
