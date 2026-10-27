param(
    [string]$Work = $PSScriptRoot,
    [string]$Cue = '',
    [switch]$Headless,
    [int]$VBlanks = 0,
    [switch]$ReplayLatest,
    [string]$ReplayCheckpoint = '',
    [string]$NativeState = '',
    [switch]$LoadNativeLatest,
    [switch]$Diagnostics,
    # Default: one backup memory shared by all scenarios, so each game's new-game import finds the
    # previous scenario's COMPLETE record. -SeparateSaves keeps this folder's own file (old behaviour).
    [switch]$SeparateSaves,
    [string]$SharedSaveDir = '',
    [string]$LauncherSettings = ''
)
$ErrorActionPreference = 'Stop'
$Work = [System.IO.Path]::GetFullPath($Work)
if (-not $Cue) {
    $config = Join-Path $Work 'game.json'
    if (-not (Test-Path -LiteralPath $config)) { throw 'Pass -Cue or prepare this work folder with tools/prepare-game.ps1 first.' }
    $Cue = [string](Get-Content -LiteralPath $config -Raw | ConvertFrom-Json).cue
}
for ($ancestor = [System.IO.DirectoryInfo]$Work; $null -ne $ancestor; $ancestor = $ancestor.Parent) {
    if (Test-Path -LiteralPath (Join-Path $ancestor.FullName '.git')) { throw 'Game data, output and saves must stay outside a source repository.' }
}
$buildDirectory = 'build-window'
$selector = Join-Path $Work 'native-build.txt'
if (Test-Path -LiteralPath $selector) {
    $buildDirectory = [IO.File]::ReadAllText($selector).Trim()
    if ($buildDirectory -notmatch '^build-[A-Za-z0-9_-]+$') { throw 'Invalid native build directory selector' }
}
$exe = Join-Path (Join-Path $Work $buildDirectory) 'saturn.exe'
$helper = Join-Path (Join-Path $Work $buildDirectory) 'replay_checkpoint.exe'
if (-not (Test-Path -LiteralPath $exe) -or -not (Test-Path -LiteralPath $helper)) { throw 'Build the native executable and replay_checkpoint helper first' }
if (-not (Test-Path -LiteralPath $Cue)) { throw 'Local CUE is missing' }
$buildId = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
# Hash the supplied disc, not just its pathname. Once per launcher process.
$cuePath = (Resolve-Path -LiteralPath $Cue).Path
$discParts = @((Get-FileHash -LiteralPath $cuePath -Algorithm SHA256).Hash)
$trackInfo = @()
foreach ($line in [System.IO.File]::ReadAllLines($cuePath)) {
    if ($line -match '^\s*FILE\s+"([^"]+)"') {
        $trackPath = Join-Path (Split-Path $cuePath -Parent) $Matches[1]
        $trackHash = (Get-FileHash -LiteralPath $trackPath -Algorithm SHA256).Hash
        $discParts += $trackHash
        $trackInfo += [ordered]@{ file = $Matches[1]; sha256 = $trackHash.ToLowerInvariant() }
    }
}
if (-not $trackInfo.Count) { throw 'No quoted FILE entries were found in the CUE' }
$hasher = [System.Security.Cryptography.SHA256]::Create()
try { $discId = ([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes(($discParts -join "`n"))))).Replace('-', '').ToLowerInvariant() }
finally { $hasher.Dispose() }
$nativeStateRoot = Join-Path (Join-Path $Work 'native-states') ($buildId.Substring(0,16) + '-' + $discId.Substring(0,16))
if ($LoadNativeLatest) {
    $NativeState = Join-Path $nativeStateRoot 'latest.satstate'
    if (-not (Test-Path -LiteralPath $NativeState)) { throw 'No native state has been saved for this executable and disc yet.' }
}
$replayRoot = Join-Path $Work 'replay-checkpoints'
if ($ReplayLatest) {
    $name = [System.IO.File]::ReadAllText((Join-Path $replayRoot 'latest.txt'))
    if ($name -notmatch '^\d+-\d+$') { throw 'No valid latest replay checkpoint' }
    $ReplayCheckpoint = Join-Path $replayRoot $name
}
$previousEnvironment = @{}
$artworkEnvironment = @{}
if (Test-Path -LiteralPath (Join-Path $Work 'ai-packs.json')) {
    $artworkHelper = Join-Path $Work 'ai-packs-helper.py'
    $artworkProfiles = Join-Path $Work 'ai-profiles'
    $pythonFile = Join-Path $Work 'save-import-python.txt'
    if (-not (Test-Path -LiteralPath $artworkHelper) -or -not (Test-Path -LiteralPath $pythonFile)) { throw 'Prepare this game with the updated application before attaching optional graphics.' }
    $artworkPython = [IO.File]::ReadAllText($pythonFile).Trim()
    $resolvedArtwork = & $artworkPython -X utf8 -B $artworkHelper env --game-dir $Work --profiles $artworkProfiles
    if ($LASTEXITCODE -ne 0) { throw 'Optional graphics could not be validated. Choose Use original graphics in the launcher, or reattach a matching builder report.' }
    $artworkEnvironment = $resolvedArtwork | ConvertFrom-Json
}
function Write-SavesStatus([string]$Message) {
    Write-Host ('SF3_STATUS ' + (ConvertTo-Json -Compress @{ phase = 'saves'; message = $Message; done = 0; total = 0 }))
    Write-Host "SF3 saves: $Message"
}
$sharedDir = ''
$sharedLock = $null
$sharedPython = ''
$sharedHelper = Join-Path $Work 'shared-saves.py'
if (-not $SeparateSaves -and (-not (Test-Path -LiteralPath $sharedHelper) -or -not (Test-Path -LiteralPath (Join-Path $Work 'save-import-python.txt')))) {
    # Folders made by older or manual builds lack the helper; keep them playable with their own file.
    Write-SavesStatus 'WARNING: the shared backup memory needs this game prepared again with the updated application; using this folder''s own saves for now.'
    $SeparateSaves = $true
}
if (-not $SeparateSaves) {
    $sharedDir = if ($SharedSaveDir) { [IO.Path]::GetFullPath($SharedSaveDir) } else { Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'SFIII Native\Shared Backup Memory' }
    if (($sharedDir + '\').StartsWith($Work + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'The shared backup memory folder must be outside the game-data folder.' }
    $pythonFile = Join-Path $Work 'save-import-python.txt'
    $sharedPython = [IO.File]::ReadAllText($pythonFile).Trim()
    New-Item -ItemType Directory -Force $sharedDir | Out-Null
    # Held for the whole session: a second scenario (or a save import) cannot use the same files.
    try { $sharedLock = [IO.File]::Open((Join-Path $sharedDir 'backup.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { throw "Another Shining Force III game, save import or merge is using the shared backup memory ($sharedDir). Close it first, or choose separate saves per scenario." }
    try {
        $prepareArguments = @('-X', 'utf8', '-B', $sharedHelper, 'prepare', '--work', $Work, '--shared', $sharedDir)
        if ($LauncherSettings) { $prepareArguments += @('--settings', $LauncherSettings) }
        $prepared = & $sharedPython @prepareArguments
        if ($LASTEXITCODE -ne 0) { throw 'The shared backup memory could not be prepared; nothing was changed. See the message above, or choose separate saves per scenario.' }
        $sharedReport = ($prepared -join "`n") | ConvertFrom-Json
    }
    catch { $sharedLock.Dispose(); throw }
    foreach ($message in $sharedReport.messages) { Write-SavesStatus $message }
    [IO.File]::WriteAllText((Join-Path $Work 'shared-backup-memory.txt'), "This game uses the backup memory shared by all scenarios:`r`n" + (Join-Path $sharedDir 'backup.bin') + "`r`nAny experimental-backup.bin in this folder was merged into it once and is kept unchanged;`r`nit is used again only when you choose separate saves per scenario.`r`n")
}
foreach ($name in @('SF3_CONTROLLER_DIR', 'SF3_RAM_DUMP', 'SF3_CRASH_DIR', 'SF3_REPLAY_ROOT', 'SF3_REPLAY_SEED', 'SF3_STATE_ROOT', 'SF3_STATE_ID', 'SF3_AI_VIDEO_DIR', 'SF3_AI_ASSET_DIR', 'SF3_AI_NATURAL_DIR')) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$result = 1
Push-Location $Work
try {
    do {
        $run = Join-Path $Work ('sessions\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N').Substring(0,6))
        $seed = Join-Path $run 'replay-seed'
        New-Item -ItemType Directory -Force $seed | Out-Null
        $run | Set-Content -LiteralPath (Join-Path $Work 'last-session.txt') -Encoding utf8
        [IO.File]::WriteAllText((Join-Path $seed 'build-id.txt'), $buildId)
        [IO.File]::WriteAllText((Join-Path $seed 'disc-id.txt'), $discId)
        $context = [ordered]@{ format = 'SF3REPLAY1'; clock = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'); executableSha256 = $buildId; discSha256 = $discId; tracks = $trackInfo }
        $resumeFrame = 0L
        $save = if ($sharedDir) { Join-Path $sharedDir 'backup.bin' } else { Join-Path $Work 'experimental-backup.bin' }
        $settings = Join-Path $Work 'settings.ini'
        if ($ReplayCheckpoint) {
            $ReplayCheckpoint = [IO.Path]::GetFullPath($ReplayCheckpoint)
            if (-not $ReplayCheckpoint.StartsWith($replayRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Replay checkpoint must be under this work folder''s replay-checkpoints directory' }
            $verified = & $helper verify $ReplayCheckpoint $seed
            if ($LASTEXITCODE -ne 0) { throw 'Checkpoint validation failed; it was not loaded' }
            $resumeFrame = [long]($verified | Select-Object -Last 1)
            foreach ($name in @('context.json', 'build-id.txt', 'disc-id.txt', 'backup.bin', 'settings.ini', 'backup.bin.cartridge')) {
                $source = Join-Path $ReplayCheckpoint ('seed\' + $name)
                if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination (Join-Path $seed $name) }
            }
            $context = Get-Content -LiteralPath (Join-Path $seed 'context.json') -Raw | ConvertFrom-Json
            # Later saves stay local to this replay session; loading cannot roll back the ordinary backup.
            $save = Join-Path $run 'replay-backup.bin'
            Copy-Item -LiteralPath (Join-Path $seed 'backup.bin') -Destination $save
            $cartSeed = Join-Path $seed 'backup.bin.cartridge'
            if (Test-Path -LiteralPath $cartSeed) { Copy-Item -LiteralPath $cartSeed -Destination ($save + '.cartridge') }
            else { [IO.File]::WriteAllBytes(($save + '.cartridge'), [byte[]]@()) }
            $settings = Join-Path $run 'replay-settings.ini'
            if (Test-Path -LiteralPath (Join-Path $seed 'settings.ini')) { Copy-Item -LiteralPath (Join-Path $seed 'settings.ini') -Destination $settings }
        } else {
            if (Test-Path -LiteralPath $save) { Copy-Item -LiteralPath $save -Destination (Join-Path $seed 'backup.bin') }
            else { [IO.File]::WriteAllBytes((Join-Path $seed 'backup.bin'), [byte[]]@()) }
            $cartSeed = Join-Path $seed 'backup.bin.cartridge'
            if (Test-Path -LiteralPath ($save + '.cartridge')) { Copy-Item -LiteralPath ($save + '.cartridge') -Destination $cartSeed }
            else { [IO.File]::WriteAllBytes($cartSeed, [byte[]]@()) }
            if (Test-Path -LiteralPath $settings) { Copy-Item -LiteralPath $settings -Destination (Join-Path $seed 'settings.ini') }
            $context | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $seed 'context.json') -Encoding utf8
        }
        foreach ($name in @('settings.ini', 'controller-mappings.txt', 'experimental-backup.bin', 'experimental-backup.bin.cartridge')) {
            $source = Join-Path $Work $name
            if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination (Join-Path $run ('before-' + $name)) }
        }
        if ($sharedDir) {
            foreach ($suffix in @('', '.cartridge')) {
                $source = Join-Path $sharedDir ('backup.bin' + $suffix)
                if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination (Join-Path $run ('before-shared-backup.bin' + $suffix)) }
            }
        }
        New-Item -ItemType File -Path (Join-Path $run 'input.txt') | Out-Null
        $clockText = if ($context.clock -is [DateTime]) { $context.clock.ToString('yyyy-MM-ddTHH:mm:ss') } else { [string]$context.clock }
        $options = @('--cue', $cuePath, '--save', $save, '--settings', $settings, '--clock', $clockText, '--out', $run,
            '--log', (Join-Path $run 'run.log'), '--record-input', (Join-Path $run 'input.txt'))
        if ($NativeState) {
            if ($ReplayCheckpoint) { throw 'Choose a native state or a replay, not both.' }
            $NativeState = [IO.Path]::GetFullPath($NativeState)
            $stateRoot = [IO.Path]::GetFullPath((Join-Path $Work 'native-states')) + '\'
            if (-not $NativeState.StartsWith($stateRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Native state must be in this game-data folder''s native-states directory.' }
            # Keep the exact pre-load progress and source state before restoring.
            Copy-Item -LiteralPath $NativeState -Destination (Join-Path $run 'loaded.satstate')
            $presence = [ordered]@{}
            $liveName = Split-Path $save -Leaf
            foreach ($name in @($liveName, ($liveName + '.cartridge'))) {
                $source = Join-Path (Split-Path $save -Parent) $name
                $presence[$name] = Test-Path -LiteralPath $source
                if ($presence[$name]) { Copy-Item -LiteralPath $source -Destination (Join-Path $run ('before-native-state-load-' + $name)) }
            }
            $presence | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'before-native-state-load.json') -Encoding utf8
            $options += @('--state-in', (Join-Path $run 'loaded.satstate'))
        }
        if ($Diagnostics) { $options += @('--coverage', (Join-Path $run 'coverage.tsv'), '--checkpoint', '10', '--trace') }
        if ($ReplayCheckpoint) { $options += @('--input', ('@' + (Join-Path $ReplayCheckpoint 'input.txt')), '--resume', "$resumeFrame", '--resume-label', 'Loading replay checkpoint') }
        if ($Headless) { $options += '--headless' }
        if ($VBlanks -gt 0) { $options += @('--vblanks', "$VBlanks") }
        $manifest = [ordered]@{ startedUtc = [DateTime]::UtcNow.ToString('o'); finishedUtc = $null; executable = $exe;
            executableSha256 = $buildId; arguments = $options; replayCheckpoint = $ReplayCheckpoint; exitCode = $null; launcherError = $null }
        $manifestPath = Join-Path $run 'session.json'
        $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8
        Write-Host "Native SFIII session: $run"
        Write-Host 'Native-state builds: F5 saves a machine snapshot; F9 loads it directly, without replay.'
        Write-Host 'Earlier builds retain replay checkpoints. Console and input are logged.'
        $env:SF3_CONTROLLER_DIR = $Work
        $env:SF3_RAM_DUMP = Join-Path $run 'crash-wram-high.bin'
        $env:SF3_CRASH_DIR = $run
        $env:SF3_REPLAY_ROOT = $replayRoot
        $env:SF3_REPLAY_SEED = $seed
        $env:SF3_STATE_ROOT = $nativeStateRoot
        $env:SF3_STATE_ID = $buildId + ':' + $discId
        foreach ($name in @('SF3_AI_VIDEO_DIR','SF3_AI_ASSET_DIR','SF3_AI_NATURAL_DIR')) {
            $value = if ($artworkEnvironment -is [Collections.IDictionary]) { $artworkEnvironment[$name] } else { $artworkEnvironment.$name }
            [Environment]::SetEnvironmentVariable($name, [string]$value, 'Process')
        }
        try {
            & $exe @options
            $result = $LASTEXITCODE
            $manifest.exitCode = $result
        } catch { $manifest.launcherError = $_.Exception.Message; throw }
        finally {
            if ($ReplayCheckpoint) {
                try {
                    if ($sharedDir) { & (Join-Path $PSScriptRoot 'publish-replay-save.ps1') -Work $Work -Session $run -ResumeFrame $resumeFrame -SharedSaveDir $sharedDir -Python $sharedPython }
                    else { & (Join-Path $PSScriptRoot 'publish-replay-save.ps1') -Work $Work -Session $run -ResumeFrame $resumeFrame }
                }
                catch { Write-Warning "Could not publish the replay save: $_. It remains in $save" }
            } elseif ($sharedDir -and $NativeState) {
                # A native state brings back the whole backup memory of its moment; keep the other
                # scenarios' saves as they were before this session.
                $guard = & $sharedPython -X utf8 -B $sharedHelper guard --work $Work --shared $sharedDir --before (Join-Path $run 'before-native-state-load-backup.bin')
                if ($LASTEXITCODE -ne 0) { Write-Warning 'Could not check the other scenarios'' saves after the native state load.' }
                else {
                    $guard | Set-Content -LiteralPath (Join-Path $run 'shared-saves-guard.json') -Encoding utf8
                    $guardReport = ($guard -join "`n") | ConvertFrom-Json
                    $changed = @($guardReport.restored).Count + @($guardReport.removed).Count
                    if ($changed) { Write-SavesStatus "Kept the other scenarios' saves as they were before the native state load ($changed record(s)); copies in $($guardReport.backup)" }
                    if (@($guardReport.not_restored).Count) { Write-SavesStatus "WARNING: no room to restore some saves; kept in $($guardReport.backup)" }
                }
            }
            $manifest.finishedUtc = [DateTime]::UtcNow.ToString('o')
            $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8
            Write-Host "Session saved: $run"
        }
        $ReplayCheckpoint = ''
        $NativeState = ''
        $request = Join-Path $run 'reload-request.txt'
        if ($result -eq 0 -and (Test-Path -LiteralPath $request)) { $ReplayCheckpoint = [IO.File]::ReadAllText($request) }
        $stateRequest = Join-Path $run 'native-state-request.txt'
        if ($result -eq 0 -and (Test-Path -LiteralPath $stateRequest)) { $NativeState = [IO.File]::ReadAllText($stateRequest) }
    } while ($ReplayCheckpoint -or $NativeState)
} finally {
    foreach ($name in $previousEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process') }
    Pop-Location
    if ($sharedLock) { $sharedLock.Dispose() }
}
if ($result -ne 0) {
    Write-Host "Native runtime stopped with exit code $result"
    if (Test-Path -LiteralPath (Join-Path $run 'run.log')) { Get-Content -LiteralPath (Join-Path $run 'run.log') -Tail 25 }
}
exit $result
