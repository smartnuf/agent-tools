function Update-ProcessPath {
    $ProcessEntries = @($env:Path -split ';' | Where-Object { $_ })
    $UserEntries = @([Environment]::GetEnvironmentVariable('Path', 'User') -split ';' | Where-Object { $_ })
    $MachineEntries = @([Environment]::GetEnvironmentVariable('Path', 'Machine') -split ';' | Where-Object { $_ })
    $env:Path = (@($ProcessEntries) + @($UserEntries) + @($MachineEntries) | Select-Object -Unique) -join ';'
}

function Add-DiscoveredCommandDirectory {
    param(
        [Parameter(Mandatory)][string[]]$Command,
        [Parameter(Mandatory)][string[]]$SearchRoot
    )

    foreach ($Root in $SearchRoot) {
        if (-not $Root -or -not (Test-Path -LiteralPath $Root -PathType Container)) {
            continue
        }
        foreach ($Name in $Command) {
            $Executable = Get-ChildItem -LiteralPath $Root -Filter $Name -File -Recurse -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending |
                Select-Object -First 1
            if ($Executable) {
                $Entries = @($env:Path -split ';' | Where-Object { $_ })
                if ($Entries -notcontains $Executable.DirectoryName) {
                    $env:Path = (@($Executable.DirectoryName) + $Entries) -join ';'
                }
                return $Executable.FullName
            }
        }
    }
    return $null
}
