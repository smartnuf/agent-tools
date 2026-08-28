[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv is required; run bootstrap.ps1 first.' }
& uv pip install --exact --python (Join-Path $Root '.venv\Scripts\python.exe') -r (Join-Path $Root 'requirements.txt') -e $Root
if ($LASTEXITCODE -ne 0) { throw "Python package update failed with exit code $LASTEXITCODE." }
& (Join-Path $Root 'bin\agent-tools.cmd') doctor
if ($LASTEXITCODE -ne 0) { throw "Environment validation failed with exit code $LASTEXITCODE." }
