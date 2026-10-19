param(
    [Parameter(Mandatory=$true)][string]$Generated,
    [Parameter(Mandatory=$true)][string]$Build,
    [Parameter(Mandatory=$true)][string]$Runtime,
    [switch]$WithWindow,
    [string]$Sdl,
    [switch]$NoActivate
)
$ErrorActionPreference = 'Stop'
# Run in a Visual Studio developer shell with LLVM, CMake and Ninja on PATH.
foreach ($tool in @('cmake', 'ninja', 'clang', 'clang++')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing tool: $tool" }
}
$repo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
foreach ($path in @($Generated, $Build)) {
    $absolute = [System.IO.Path]::GetFullPath($path)
    if ($absolute -eq $repo -or $absolute.StartsWith($repo+'\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Generated code and build outputs must be outside the source repository.'
    }
}
$runtimeCmake = [System.IO.Path]::GetFullPath($Runtime).Replace('\', '/')
$extra = (Join-Path $PSScriptRoot 'windows.cmake').Replace('\', '/')
$mode = if ($WithWindow) { 'OFF' } else { 'ON' }
$options = @()
if ($WithWindow) {
    if (-not $Sdl) { $Sdl = Join-Path $repo '.local\sdl3\SDL3-3.4.18' }
    if (-not (Test-Path -LiteralPath $Sdl)) { throw 'SDL3 development directory missing' }
    $options += '-DCMAKE_PREFIX_PATH=' + [System.IO.Path]::GetFullPath($Sdl).Replace('\', '/')
}
& cmake -S $Generated -B $Build -G Ninja '-DCMAKE_BUILD_TYPE=Release' '-DCMAKE_C_COMPILER=clang' '-DCMAKE_CXX_COMPILER=clang++' "-DSATURN_NO_SDL=$mode" "-DSATURN_RUNTIME=$runtimeCmake" "-DSATURN_EXTRA=$extra" @options
if ($LASTEXITCODE -ne 0) { throw 'CMake configuration failed' }
$targets = @('saturn')
if ($WithWindow) { $targets += @('controller_setup', 'controller_selftest', 'replay_checkpoint') }
& cmake --build $Build --target @targets --parallel 4
if ($LASTEXITCODE -ne 0) { throw 'Native build failed' }
if ($WithWindow) {
    Copy-Item -LiteralPath (Join-Path $Sdl 'lib\x64\SDL3.dll') -Destination (Join-Path $Build 'SDL3.dll') -Force
    $controllerDirectory = Split-Path ([System.IO.Path]::GetFullPath($Generated)) -Parent
    $database = Join-Path $repo '.local\controllerdb'
    if (-not (Test-Path -LiteralPath (Join-Path $database 'gamecontrollerdb.txt'))) {
        throw 'Missing .local/controllerdb: clone mdqinc/SDL_GameControllerDB before packaging controller support.'
    }
    Copy-Item -LiteralPath (Join-Path $Build 'controller_setup.exe') -Destination (Join-Path $controllerDirectory 'controller-setup.exe') -Force
    Copy-Item -LiteralPath (Join-Path $Sdl 'lib\x64\SDL3.dll') -Destination (Join-Path $controllerDirectory 'SDL3.dll') -Force
    Copy-Item -LiteralPath (Join-Path $database 'gamecontrollerdb.txt') -Destination $controllerDirectory -Force
    Copy-Item -LiteralPath (Join-Path $database 'LICENSE') -Destination (Join-Path $controllerDirectory 'CONTROLLER-DATABASE-LICENSE.txt') -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Controller Setup.cmd'),(Join-Path $PSScriptRoot 'Controller Test.cmd') -Destination $controllerDirectory -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'run-native.ps1'),(Join-Path $PSScriptRoot 'publish-replay-save.ps1'),(Join-Path $PSScriptRoot 'Launch Native SFIII.cmd'),(Join-Path $PSScriptRoot 'Load Replay Checkpoint.cmd') -Destination $controllerDirectory -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Import Saturn Saves.cmd'),(Join-Path $PSScriptRoot 'import-saturn-save.ps1'),(Join-Path $PSScriptRoot 'import-saturn-save.py') -Destination $controllerDirectory -Force
    $builtDirectory = [IO.Path]::GetFullPath($Build).TrimEnd('\')
    if (-not $NoActivate -and (Split-Path $builtDirectory -Parent) -eq $controllerDirectory -and (Split-Path $builtDirectory -Leaf) -match '^build-[A-Za-z0-9_-]+$') {
        [IO.File]::WriteAllText((Join-Path $controllerDirectory 'native-build.txt'), (Split-Path $builtDirectory -Leaf))
    }
}
