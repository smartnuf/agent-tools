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

    $Candidates = foreach ($Root in $SearchRoot) {
        if (-not $Root -or -not (Test-Path -LiteralPath $Root -PathType Container)) {
            continue
        }
        for ($CommandRank = 0; $CommandRank -lt $Command.Count; $CommandRank++) {
            foreach ($Executable in Get-ChildItem -LiteralPath $Root -Filter $Command[$CommandRank] -File -Recurse -ErrorAction SilentlyContinue) {
                $Version = [version]'0.0'
                $VersionText = $Executable.Directory.Parent.Name -replace '^[^0-9]*', ''
                [version]::TryParse($VersionText, [ref]$Version) | Out-Null
                [pscustomobject]@{
                    Executable = $Executable
                    Version = $Version
                    CommandRank = $CommandRank
                }
            }
        }
    }
    $Selected = $Candidates |
        Sort-Object @{ Expression = 'Version'; Descending = $true }, @{ Expression = 'CommandRank'; Descending = $false }, @{ Expression = { $_.Executable.FullName }; Descending = $true } |
        Select-Object -First 1
    if ($Selected) {
        $Entries = @($env:Path -split ';' | Where-Object { $_ })
        if ($Entries -notcontains $Selected.Executable.DirectoryName) {
            $env:Path = (@($Selected.Executable.DirectoryName) + $Entries) -join ';'
        }
        return $Selected.Executable.FullName
    }
    return $null
}
