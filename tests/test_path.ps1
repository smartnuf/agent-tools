[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$PathScript = Join-Path $Root 'scripts\path.ps1'
$Bin = Join-Path $Root 'bin'
$BackupDirectory = Join-Path ([IO.Path]::GetTempPath()) "agent-tools-path-$([Guid]::NewGuid())"
$OriginalUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$TestUserPath = 'C:\agent-tools-existing-test-entry'

try {
    [Environment]::SetEnvironmentVariable('Path', $TestUserPath, 'User')
    & $PathScript -Apply -BackupDirectory $BackupDirectory

    $Updated = [Environment]::GetEnvironmentVariable('Path', 'User')
    $Expected = "$TestUserPath;$Bin"
    if ($Updated -ne $Expected) { throw "Unexpected user PATH: $Updated" }

    $Backups = @(Get-ChildItem -LiteralPath $BackupDirectory -Filter 'user-path-*.txt')
    if ($Backups.Count -ne 1) { throw "Expected one PATH backup, found $($Backups.Count)." }
    if ([IO.File]::ReadAllText($Backups[0].FullName) -ne $TestUserPath) {
        throw 'PATH backup did not preserve the previous value.'
    }

    & $PathScript -Apply -BackupDirectory $BackupDirectory
    $BackupsAfterRepeat = @(Get-ChildItem -LiteralPath $BackupDirectory -Filter 'user-path-*.txt')
    if ($BackupsAfterRepeat.Count -ne 1) { throw 'Idempotent rerun created an unnecessary backup.' }
}
finally {
    [Environment]::SetEnvironmentVariable('Path', $OriginalUserPath, 'User')
    if (Test-Path -LiteralPath $BackupDirectory) {
        Remove-Item -LiteralPath $BackupDirectory -Recurse -Force
    }
}
