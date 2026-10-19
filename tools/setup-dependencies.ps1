param()
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$local = Join-Path $repo '.local'
$lock = Get-Content -LiteralPath (Join-Path $repo 'dependencies.json') -Raw | ConvertFrom-Json
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows first.' }
New-Item -ItemType Directory -Force -Path $local | Out-Null
function Checkout-Dependency($Spec) {
    $destination = Join-Path $local $Spec.directory
    if (-not (Test-Path -LiteralPath $destination)) {
        & git clone --no-checkout $Spec.url $destination
        if ($LASTEXITCODE -ne 0) { throw "Clone failed: $($Spec.url)" }
        & git -C $destination checkout --detach $Spec.commit
        if ($LASTEXITCODE -ne 0) { throw 'Pinned checkout failed' }
    }
    $head = & git -C $destination rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $head -ne $Spec.commit) { throw "Unexpected dependency revision in $destination. Existing files were left intact." }
    return $destination
}
$runtime = Checkout-Dependency $lock.runtime
$database = Checkout-Dependency $lock.controllers
$patch = Join-Path $PSScriptRoot 'runtime-diagnostics.patch'
$savedPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& git -C $runtime apply --reverse --check $patch 2>$null
$reverseExit = $LASTEXITCODE
$ErrorActionPreference = $savedPreference
if ($reverseExit -ne 0) {
    & git -C $runtime apply --check $patch
    if ($LASTEXITCODE -ne 0) { throw 'Runtime patch does not apply. Existing dependency was left intact.' }
    & git -C $runtime apply $patch
    if ($LASTEXITCODE -ne 0) { throw 'Runtime patch failed' }
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
foreach ($archive in $lock.archives) {
    $destination = Join-Path $local $archive.directory
    $cached = Join-Path $local ([IO.Path]::GetFileName($archive.url))
    if (-not (Test-Path -LiteralPath $cached)) { Invoke-WebRequest -UseBasicParsing -Uri $archive.url -OutFile $cached }
    if ((Get-FileHash -LiteralPath $cached -Algorithm SHA256).Hash.ToLowerInvariant() -ne $archive.sha256) {
        throw "Dependency checksum mismatch: $cached"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $destination $archive.required_file))) {
        if (Test-Path -LiteralPath $destination) { throw "Incomplete dependency at $destination; inspect it before retrying." }
        Expand-Archive -LiteralPath $cached -DestinationPath $destination
    }
    Write-Host "Ready: $($archive.name)"
}
Write-Host 'Pinned dependencies ready. Install LLVM and Visual Studio C++ tools as described in docs/BUILDING.md.'
