[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$PathScript = Join-Path $Root 'scripts\path.ps1'
$Bin = Join-Path $Root 'bin'
$BackupDirectory = Join-Path ([IO.Path]::GetTempPath()) "agent-tools-path-$([Guid]::NewGuid())"
$TestUserPath = 'C:\agent-tools-existing-test-entry'
$State = [pscustomobject]@{ Path = $TestUserPath; Writes = 0 }
$ReadUserPath = { $State.Path }.GetNewClosure()
$WriteUserPath = {
    param([string]$Value)
    $State.Path = $Value
    $State.Writes++
}.GetNewClosure()

try {
    & $PathScript -Apply -BackupDirectory $BackupDirectory -ReadUserPath $ReadUserPath -WriteUserPath $WriteUserPath

    $Expected = "$TestUserPath;$Bin"
    if ($State.Path -ne $Expected) { throw "Unexpected user PATH: $($State.Path)" }
    if ($State.Writes -ne 1) { throw "Expected one PATH write, found $($State.Writes)." }

    $Backups = @(Get-ChildItem -LiteralPath $BackupDirectory -Filter 'user-path-*.txt')
    if ($Backups.Count -ne 1) { throw "Expected one PATH backup, found $($Backups.Count)." }
    if ([IO.File]::ReadAllText($Backups[0].FullName) -ne $TestUserPath) {
        throw 'PATH backup did not preserve the previous value.'
    }

    & $PathScript -Apply -BackupDirectory $BackupDirectory -ReadUserPath $ReadUserPath -WriteUserPath $WriteUserPath
    $BackupsAfterRepeat = @(Get-ChildItem -LiteralPath $BackupDirectory -Filter 'user-path-*.txt')
    if ($BackupsAfterRepeat.Count -ne 1) { throw 'Idempotent rerun created an unnecessary backup.' }
    if ($State.Writes -ne 1) { throw 'Idempotent rerun performed an unnecessary PATH write.' }

    $ConcurrentState = [pscustomobject]@{ Reads = 0; Writes = 0 }
    $ConcurrentReader = {
        $ConcurrentState.Reads++
        if ($ConcurrentState.Reads -lt 3) { $TestUserPath } else { "$TestUserPath;C:\concurrent-entry" }
    }.GetNewClosure()
    $ConcurrentWriter = { param([string]$Value) $ConcurrentState.Writes++ }.GetNewClosure()
    $ConcurrencyBackup = Join-Path $BackupDirectory 'concurrent'
    try {
        & $PathScript -Apply -BackupDirectory $ConcurrencyBackup -ReadUserPath $ConcurrentReader -WriteUserPath $ConcurrentWriter
        throw 'Expected a concurrent PATH change to abort the update.'
    }
    catch {
        if ($_.Exception.Message -notlike '*changed while its backup was being created*') { throw }
    }
    if ($ConcurrentState.Writes -ne 0) { throw 'Concurrent PATH change reached the persistence boundary.' }

    $CollisionState = [pscustomobject]@{ Path = $TestUserPath }
    $CollisionReader = { $CollisionState.Path }.GetNewClosure()
    $CollisionWriter = { param([string]$Value) $CollisionState.Path = $Value }.GetNewClosure()
    $CollisionTimestamp = { '20000101T0000000000000Z' }
    $CollisionDirectory = Join-Path $BackupDirectory 'collision'
    [IO.Directory]::CreateDirectory($CollisionDirectory) | Out-Null
    $ExistingBackup = Join-Path $CollisionDirectory 'user-path-20000101T0000000000000Z.txt'
    [IO.File]::WriteAllText($ExistingBackup, 'prior evidence')
    & $PathScript -Apply -BackupDirectory $CollisionDirectory -ReadUserPath $CollisionReader -WriteUserPath $CollisionWriter -GetBackupTimestamp $CollisionTimestamp
    if ([IO.File]::ReadAllText($ExistingBackup) -ne 'prior evidence') { throw 'Existing PATH backup was overwritten.' }
    $CollisionBackup = Join-Path $CollisionDirectory 'user-path-20000101T0000000000000Z-1.txt'
    if ([IO.File]::ReadAllText($CollisionBackup) -ne $TestUserPath) { throw 'Collision-safe PATH backup has unexpected content.' }
}
finally {
    if (Test-Path -LiteralPath $BackupDirectory) {
        Remove-Item -LiteralPath $BackupDirectory -Recurse -Force
    }
}
