param(
    [string]$Work = $PSScriptRoot,
    [string]$Cue = '',
    [switch]$Headless,
    [int]$VBlanks = 0,
    [switch]$ReplayLatest,
    [string]$ReplayCheckpoint = '',
    [string]$NativeState = '',
    [switch]$LoadNativeLatest,
    [switch]$Diagnostics
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
foreach ($name in @('SF3_CONTROLLER_DIR', 'SF3_RAM_DUMP', 'SF3_CRASH_DIR', 'SF3_REPLAY_ROOT', 'SF3_REPLAY_SEED', 'SF3_STATE_ROOT', 'SF3_STATE_ID')) {
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
        $save = Join-Path $Work 'experimental-backup.bin'
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
            foreach ($name in @('experimental-backup.bin', 'experimental-backup.bin.cartridge')) {
                $source = Join-Path $Work $name
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
        try {
            & $exe @options
            $result = $LASTEXITCODE
            $manifest.exitCode = $result
        } catch { $manifest.launcherError = $_.Exception.Message; throw }
        finally {
            if ($ReplayCheckpoint) {
                try { & (Join-Path $PSScriptRoot 'publish-replay-save.ps1') -Work $Work -Session $run -ResumeFrame $resumeFrame }
                catch { Write-Warning "Could not publish the replay save: $_. It remains in $save" }
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
}
if ($result -ne 0) {
    Write-Host "Native runtime stopped with exit code $result"
    if (Test-Path -LiteralPath (Join-Path $run 'run.log')) { Get-Content -LiteralPath (Join-Path $run 'run.log') -Tail 25 }
}
exit $result
