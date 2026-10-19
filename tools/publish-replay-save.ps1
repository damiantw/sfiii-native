param(
    [Parameter(Mandatory=$true)][string]$Work,
    [Parameter(Mandatory=$true)][string]$Session,
    [Parameter(Mandatory=$true)][uint64]$ResumeFrame
)
$ErrorActionPreference = 'Stop'
foreach ($device in @('internal', 'cartridge')) {
    $suffix = if ($device -eq 'internal') { '' } else { '.cartridge' }
    $markerName = if ($device -eq 'internal') { 'live-save-written.txt' } else { 'live-cartridge-save-written.txt' }
    $marker = Join-Path $Session $markerName
    if (-not (Test-Path -LiteralPath $marker)) { continue }
    [uint64]$frame = 0
    if (-not [uint64]::TryParse([IO.File]::ReadAllText($marker).Trim(), [ref]$frame) -or $frame -lt $ResumeFrame) { continue }
    $source = Join-Path $Session ('replay-backup.bin' + $suffix)
    if (-not (Test-Path -LiteralPath $source)) { throw 'The recorded live save is missing; the ordinary backup was preserved.' }
    $destination = Join-Path $Work ('experimental-backup.bin' + $suffix)
    $temporary = Join-Path $Work ('backup-publish-' + [guid]::NewGuid().ToString('N') + '.tmp')
    Copy-Item -LiteralPath $source -Destination $temporary
    if (Test-Path -LiteralPath $destination) { [IO.File]::Replace($temporary, $destination, (Join-Path $Session ('before-published-backup.bin' + $suffix))) }
    else { [IO.File]::Move($temporary, $destination) }
    Write-Host "Game save available for normal launches ($device): $destination"
}
