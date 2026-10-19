param([string]$VisualStudio = '')
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $VisualStudio) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) { throw 'Install Visual Studio Build Tools with Desktop development with C++.' }
    $VisualStudio = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
}
$devcmd = Join-Path $VisualStudio 'Common7\Tools\VsDevCmd.bat'
if (-not (Test-Path -LiteralPath $devcmd)) { throw 'Visual Studio C++ developer environment not found.' }
$variables = & cmd.exe /d /c "`"$devcmd`" -arch=x64 -host_arch=x64 >nul && set"
if ($LASTEXITCODE -ne 0) { throw 'VsDevCmd failed' }
foreach ($line in $variables) {
    if ($line -match '^([^=]+)=(.*)$' -and $Matches[1] -notin @('HOME', 'CODEX_HOME')) {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
    }
}
$cmake = Join-Path $VisualStudio 'Common7\IDE\CommonExtensions\Microsoft\CMake'
$localClang = Join-Path $repo '.local\llvm\bin'
$env:PATH = "$localClang;$cmake\CMake\bin;$cmake\Ninja;$env:PATH"
foreach ($tool in @('cmake','ninja','clang','clang++')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing $tool. See docs/BUILDING.md." }
}
