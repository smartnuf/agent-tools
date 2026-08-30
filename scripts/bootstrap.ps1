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

function Test-BootstrapPython {
    param([Parameter(Mandatory)][string]$Path)
    $StartInfo = [System.Diagnostics.ProcessStartInfo]::new($Path)
    $StartInfo.UseShellExecute = $false
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    foreach ($Argument in @('-I', '-c', 'import sys; print(sys.version_info[:2] == (3, 11))')) {
        $StartInfo.ArgumentList.Add($Argument)
    }
    $Process = [System.Diagnostics.Process]::new()
    $Process.StartInfo = $StartInfo
    try {
        if (-not $Process.Start()) { return $false }
        if (-not $Process.WaitForExit(10000)) {
            $Process.Kill($true)
            $Process.WaitForExit()
            return $false
        }
        return $Process.ExitCode -eq 0 -and $Process.StandardOutput.ReadToEnd().Trim() -eq 'True'
    } catch {
        return $false
    } finally {
        $Process.Dispose()
    }
}

function Find-BootstrapPython {
    $FilterNames = @('UV_MANAGED_PYTHON', 'UV_NO_MANAGED_PYTHON', 'UV_PYTHON_PREFERENCE', 'UV_SYSTEM_PYTHON')
    $SavedFilters = @{}
    foreach ($Name in $FilterNames) {
        $SavedFilters[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
        Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
    }
    try {
        $Found = & uv python find 3.11 --system --no-project --no-python-downloads --no-config
        if ($LASTEXITCODE -ne 0) {
            $Found = & uv python find 3.11 --managed-python --no-project --no-python-downloads --no-config
        }
        if ($LASTEXITCODE -ne 0) {
            $ManagerRoots = @(
                if ($env:PYENV_ROOT) { Join-Path $env:PYENV_ROOT 'versions' } else { Join-Path $HOME '.pyenv\versions' }
                if ($env:ASDF_DATA_DIR) { Join-Path $env:ASDF_DATA_DIR 'installs\python' } else { Join-Path $HOME '.asdf\installs\python' }
                if ($env:MISE_DATA_DIR) { Join-Path $env:MISE_DATA_DIR 'installs\python' } else { Join-Path $HOME '.local\share\mise\installs\python' }
                if ($env:CONDA_ENVS_PATH) { $env:CONDA_ENVS_PATH -split [IO.Path]::PathSeparator }
                Join-Path $HOME '.conda\envs'
                Join-Path $HOME 'miniconda3\envs'
                Join-Path $HOME 'anaconda3\envs'
                Join-Path $HOME 'miniforge3\envs'
                Join-Path $HOME 'mambaforge\envs'
                if ($env:ProgramData) { Join-Path $env:ProgramData 'conda\envs' }
            )
            $CondaBaseRoots = @(
                Join-Path $HOME 'miniconda3'
                Join-Path $HOME 'anaconda3'
                Join-Path $HOME 'miniforge3'
                Join-Path $HOME 'mambaforge'
                if ($env:ProgramData) {
                    Join-Path $env:ProgramData 'miniconda3'
                    Join-Path $env:ProgramData 'anaconda3'
                }
            )
            foreach ($ManagerRoot in $ManagerRoots) {
                $Candidates = @(
                    Get-ChildItem -Path (Join-Path $ManagerRoot '*\python.exe') -File -ErrorAction SilentlyContinue
                    Get-ChildItem -Path (Join-Path $ManagerRoot '*\bin\python.exe') -File -ErrorAction SilentlyContinue
                )
                foreach ($Candidate in $Candidates | Sort-Object -Property FullName) {
                    if (Test-BootstrapPython -Path $Candidate.FullName) {
                        return $Candidate.FullName
                    }
                }
            }
            foreach ($CondaBaseRoot in $CondaBaseRoots) {
                foreach ($CandidatePath in @(
                    (Join-Path $CondaBaseRoot 'python.exe'),
                    (Join-Path $CondaBaseRoot 'bin\python.exe')
                )) {
                    if ((Test-Path -LiteralPath $CandidatePath -PathType Leaf) -and
                        (Test-BootstrapPython -Path $CandidatePath)) {
                        return $CandidatePath
                    }
                }
            }
            throw 'No installed Python 3.11 can run selection. Install a compatible Python with a trusted provider, then rerun bootstrap.'
        }
        return $Found
    } finally {
        foreach ($Name in $FilterNames) {
            if ($null -eq $SavedFilters[$Name]) {
                Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
            } else {
                [Environment]::SetEnvironmentVariable($Name, $SavedFilters[$Name], 'Process')
            }
        }
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

$Selector = Join-Path $PSScriptRoot 'select-python.py'
$SelectorArgs = @($Selector)
if ($AllowEmulatedPython) { $SelectorArgs += '--allow-translated' }
if ($PythonPath) {
    $BootstrapPython = $PythonPath
    $SelectorArgs += @('--prefer', $PythonPath)
} else {
    $BootstrapPython = Find-BootstrapPython
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
& uv pip install --exact --python $Python -r (Join-Path $Root 'requirements.txt') -e $Root
Assert-NativeSuccess 'Python package installation'

if ($AddToPath) {
    & (Join-Path $PSScriptRoot 'path.ps1') -Apply
}

Write-Host "Ready. Run $(Join-Path $Root 'bin\agent-tools.cmd') doctor"
