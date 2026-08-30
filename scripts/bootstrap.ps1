[CmdletBinding()]
param(
    [switch]$InstallUv,
    [switch]$AllowEmulatedPython,
    [string]$PythonPath,
    [switch]$InstallNativeTools,
    [switch]$AddToPath
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$RequiredPopplerCommands = @('pdfinfo', 'pdftotext', 'pdftoppm')
. (Join-Path $PSScriptRoot 'windows-tools.ps1')

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
    Update-ProcessPath
}

if ($InstallNativeTools) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'WinGet is required for automatic native-tool installation.'
    }
    $MissingPopplerCommands = @($RequiredPopplerCommands | Where-Object { -not (Get-Command $_ -ErrorAction SilentlyContinue) })
    if ($MissingPopplerCommands.Count -gt 0) {
        winget install --id oschwartz10612.Poppler -e --accept-package-agreements --accept-source-agreements
        Assert-NativeSuccess 'Poppler installation'
    }
    if (-not (Get-Command gswin64c,gswin32c -ErrorAction SilentlyContinue)) {
        winget install --id ArtifexSoftware.GhostScript -e --accept-package-agreements --accept-source-agreements
        Assert-NativeSuccess 'Ghostscript installation'
    }
    Update-ProcessPath
    if (-not (Get-Command gswin64c,gswin32c -ErrorAction SilentlyContinue)) {
        $GhostscriptSearchRoots = @(
            if ($env:ProgramFiles) { Join-Path $env:ProgramFiles 'gs' }
            if (${env:ProgramFiles(x86)}) { Join-Path ${env:ProgramFiles(x86)} 'gs' }
        )
        Add-DiscoveredCommandDirectory -Command @('gswin64c.exe', 'gswin32c.exe') -SearchRoot $GhostscriptSearchRoots | Out-Null
    }

    $MissingPopplerCommands = @($RequiredPopplerCommands | Where-Object { -not (Get-Command $_ -ErrorAction SilentlyContinue) })
    if ($MissingPopplerCommands.Count -gt 0) {
        throw "Poppler installation completed but required command(s) are not on PATH: $($MissingPopplerCommands -join ', ')."
    }
    if (-not (Get-Command gswin64c,gswin32c -ErrorAction SilentlyContinue)) {
        throw 'Ghostscript installation completed but no supported console executable is on PATH.'
    }
}

$Selector = Join-Path $PSScriptRoot 'select-python.py'
$SelectorArgs = @($Selector)
if ($AllowEmulatedPython) { $SelectorArgs += '--allow-translated' }
if ($PythonPath) {
    $BootstrapPython = $PythonPath
    $SelectorArgs += @('--prefer', $PythonPath)
} else {
    $BootstrapPython = & uv python find 3.11 --system --no-project --no-python-downloads --no-config
    if ($LASTEXITCODE -ne 0) {
        $BootstrapPython = & uv python find 3.11 --managed-python --no-project --no-python-downloads --no-config
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'No installed Python 3.11 can run selection. Install a compatible Python with a trusted provider, then rerun bootstrap.'
    }
}
$SelectedPython = & $BootstrapPython @SelectorArgs
Assert-NativeSuccess 'final Python selection'
$SelectedPython = $SelectedPython | Select-Object -Last 1

$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    & uv venv (Join-Path $Root '.venv') --python $SelectedPython --no-python-downloads
    Assert-NativeSuccess 'virtual environment creation'
}
& $BootstrapPython @SelectorArgs --verify-final $Python | Out-Null
Assert-NativeSuccess 'final Python verification'
& uv pip install --exact --python $Python -r (Join-Path $Root 'requirements.txt') -e $Root
Assert-NativeSuccess 'Python package installation'

if ($AddToPath) {
    & (Join-Path $PSScriptRoot 'path.ps1') -Apply
}

Write-Host "Ready. Run $(Join-Path $Root 'bin\agent-tools.cmd') doctor"
