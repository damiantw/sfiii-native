param(
    [Parameter(Mandatory=$true)][string]$Cue,
    [Parameter(Mandatory=$true)][string]$Work,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$workPath = [IO.Path]::GetFullPath($Work)
for ($ancestor = [IO.DirectoryInfo]$workPath; $null -ne $ancestor; $ancestor = $ancestor.Parent) {
    if (Test-Path -LiteralPath (Join-Path $ancestor.FullName '.git')) { throw 'Choose a work folder outside all source repositories.' }
}
$cuePath = (Resolve-Path -LiteralPath $Cue).Path
if (-not (Test-Path -LiteralPath (Join-Path $repo '.local/saturn-recomp/runtime/runtime.cmake'))) { throw 'Run tools/setup-dependencies.ps1 first.' }
if (Test-Path -LiteralPath (Join-Path $workPath 'native-build.txt')) { throw 'This work folder already has an active build. Use a new work folder to preserve the runnable build and checkpoints.' }
& $Python (Join-Path $PSScriptRoot 'probe.py') --cue $cuePath --framework (Join-Path $repo '.local/saturn-recomp') --out $workPath
if ($LASTEXITCODE -ne 0) { throw 'Disc inventory failed' }
& (Join-Path $PSScriptRoot 'build-scenario1.ps1') -Work $workPath -Python $Python
if ($LASTEXITCODE -ne 0) { throw 'Game build failed' }
$revision = Get-Content -LiteralPath (Join-Path $workPath 'revision.json') -Raw | ConvertFrom-Json
$profile = Get-Content -LiteralPath (Join-Path (Join-Path $repo 'profiles') ([string]$revision.profile)) -Raw | ConvertFrom-Json
$config = [ordered]@{ cue=$cuePath; profile_id=[string]$profile.id }
$config | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $workPath 'game.json') -Encoding utf8
$pythonCommand = (Get-Command $Python -ErrorAction Stop).Source
[IO.File]::WriteAllText((Join-Path $workPath 'save-import-python.txt'),$pythonCommand)
Copy-Item -LiteralPath (Join-Path $repo 'desktop\ai_packs.py') -Destination (Join-Path $workPath 'ai-packs-helper.py') -Force
Copy-Item -LiteralPath (Join-Path $repo 'desktop\shared_saves.py') -Destination (Join-Path $workPath 'shared-saves.py') -Force
$artworkProfiles = Join-Path $workPath 'ai-profiles'
New-Item -ItemType Directory -Path $artworkProfiles -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $repo 'profiles') -Filter '*.json' | Copy-Item -Destination $artworkProfiles -Force
[IO.File]::WriteAllText((Join-Path $workPath 'native-build.txt'),'build-bulk')
Write-Host "Ready: $workPath\Launch Native SFIII.cmd"
