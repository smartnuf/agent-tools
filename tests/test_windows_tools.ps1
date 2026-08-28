[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $Root 'scripts\windows-tools.ps1')

$TestRoot = Join-Path ([IO.Path]::GetTempPath()) "agent-tools-windows-tools-$([Guid]::NewGuid())"
$ExecutableDirectory = Join-Path $TestRoot 'gs\10.06.0\bin'
$Executable = Join-Path $ExecutableDirectory 'gswin64c.exe'
$OldExecutableDirectory = Join-Path $TestRoot 'gs\9.56.1\bin'
$OldExecutable = Join-Path $OldExecutableDirectory 'gswin64c.exe'
$OriginalProcessPath = $env:Path

try {
    [IO.Directory]::CreateDirectory($ExecutableDirectory) | Out-Null
    [IO.Directory]::CreateDirectory($OldExecutableDirectory) | Out-Null
    New-Item -ItemType File -Path $Executable | Out-Null
    New-Item -ItemType File -Path $OldExecutable | Out-Null
    $env:Path = 'C:\existing-entry'

    $Found = Add-DiscoveredCommandDirectory -Command @('gswin64c.exe', 'gswin32c.exe') -SearchRoot @($TestRoot)
    if ($Found -ne $Executable) { throw "Unexpected discovered executable: $Found" }
    if (($env:Path -split ';')[0] -ne $ExecutableDirectory) { throw 'Discovered Ghostscript directory was not prepended to process PATH.' }

    Add-DiscoveredCommandDirectory -Command @('gswin64c.exe') -SearchRoot @($TestRoot) | Out-Null
    if (@($env:Path -split ';' | Where-Object { $_ -eq $ExecutableDirectory }).Count -ne 1) {
        throw 'Repeated discovery duplicated the Ghostscript directory.'
    }
}
finally {
    $env:Path = $OriginalProcessPath
    if (Test-Path -LiteralPath $TestRoot) {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force
    }
}
