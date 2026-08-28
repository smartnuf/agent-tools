[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv is required; run bootstrap.ps1 first.' }
& uv pip install --upgrade --python (Join-Path $Root '.venv\Scripts\python.exe') -r (Join-Path $Root 'requirements.txt') -e $Root
& (Join-Path $Root 'bin\agent-tools.cmd') doctor
