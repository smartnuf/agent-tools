[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$BackupDirectory,
    [Parameter(DontShow)]
    [scriptblock]$ReadUserPath = { [Environment]::GetEnvironmentVariable('Path', 'User') },
    [Parameter(DontShow)]
    [scriptblock]$WriteUserPath = { param([string]$Value) [Environment]::SetEnvironmentVariable('Path', $Value, 'User') }
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Bin = Join-Path $Root 'bin'
$UserPath = & $ReadUserPath
$Entries = @($UserPath -split ';' | Where-Object { $_ })
if ($Entries -contains $Bin) {
    Write-Host "$Bin is already on the user PATH."
    return
}
if (-not $Apply) {
    Write-Host "Would add $Bin to the user PATH. Re-run with -Apply."
    return
}
$CurrentUserPath = & $ReadUserPath
if ($CurrentUserPath -ne $UserPath) {
    throw 'The user PATH changed while this script was running. No changes were made; rerun the command.'
}
if (-not $BackupDirectory) {
    $BackupDirectory = Join-Path $Root '.backups\path'
}
[IO.Directory]::CreateDirectory($BackupDirectory) | Out-Null
$Timestamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')
$BackupPath = Join-Path $BackupDirectory "user-path-$Timestamp.txt"
[IO.File]::WriteAllText($BackupPath, [string]$CurrentUserPath, [Text.UTF8Encoding]::new($false))
$LatestUserPath = & $ReadUserPath
if ($LatestUserPath -ne $CurrentUserPath) {
    throw 'The user PATH changed while its backup was being created. No changes were made; rerun the command.'
}
$LatestEntries = @($LatestUserPath -split ';' | Where-Object { $_ })
$NewPath = (@($LatestEntries) + $Bin) -join ';'
& $WriteUserPath $NewPath
Write-Host "Backed up the previous user PATH to $BackupPath"
Write-Host "Added $Bin to the user PATH. Open a new terminal to use it."
