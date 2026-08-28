[CmdletBinding()]
param([switch]$Apply)

$ErrorActionPreference = 'Stop'
$Bin = Join-Path (Split-Path -Parent $PSScriptRoot) 'bin'
$UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$Entries = @($UserPath -split ';' | Where-Object { $_ })
if ($Entries -contains $Bin) {
    Write-Host "$Bin is already on the user PATH."
    exit 0
}
if (-not $Apply) {
    Write-Host "Would add $Bin to the user PATH. Re-run with -Apply."
    exit 0
}
$NewPath = (@($Entries) + $Bin) -join ';'
[Environment]::SetEnvironmentVariable('Path', $NewPath, 'User')
Write-Host "Added $Bin to the user PATH. Open a new terminal to use it."
