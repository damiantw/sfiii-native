param(
    [Parameter(Mandatory=$true)][string]$Work,
    [Parameter(Mandatory=$true)][string]$Session,
    [Parameter(Mandatory=$true)][uint64]$ResumeFrame,
    # Shared backup memory: only this scenario's records are published; other scenarios' saves stay.
    [string]$SharedSaveDir = '',
    [string]$Python = ''
)
$ErrorActionPreference = 'Stop'
if ($SharedSaveDir) {
    $written = $false
    foreach ($markerName in @('live-save-written.txt', 'live-cartridge-save-written.txt')) {
        $marker = Join-Path $Session $markerName
        [uint64]$frame = 0
        if ((Test-Path -LiteralPath $marker) -and [uint64]::TryParse([IO.File]::ReadAllText($marker).Trim(), [ref]$frame) -and $frame -ge $ResumeFrame) { $written = $true }
    }
    if (-not $written) { return }
    foreach ($suffix in @('', '.cartridge')) {
        $current = Join-Path $SharedSaveDir ('backup.bin' + $suffix)
        if (Test-Path -LiteralPath $current) { Copy-Item -LiteralPath $current -Destination (Join-Path $Session ('before-published-shared-backup.bin' + $suffix)) }
    }
    & $Python -X utf8 -B (Join-Path $Work 'shared-saves.py') publish --work $Work --shared $SharedSaveDir --source (Join-Path $Session 'replay-backup.bin') | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'The replay save could not be published; the shared backup memory was preserved.' }
    Write-Host "Game save available for normal launches (shared backup memory): $SharedSaveDir"
    return
}
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
