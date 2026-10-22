param(
    [Parameter(Mandatory=$true)][string]$Work,
    [string]$Python = 'python',
    [string]$Session = '',
    [switch]$AuditOnly,
    [switch]$Headless
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$workPath = [IO.Path]::GetFullPath($Work)
$audit = Join-Path $workPath 'module-audit'
$generated = Join-Path $workPath 'recomp-bulk'
$build = Join-Path $workPath 'build-bulk'
$argsList = @((Join-Path $PSScriptRoot 'audit-modules.py'), '--work', $workPath, '--out', $audit)
$revisionFile = Join-Path $workPath 'revision.json'
if (Test-Path -LiteralPath $revisionFile) {
    $revision = Get-Content -LiteralPath $revisionFile -Raw | ConvertFrom-Json
    $profileName = [string]$revision.profile
    if ($profileName -notmatch '^[A-Za-z0-9_-][A-Za-z0-9_.-]*\.json$') { throw 'Invalid revision profile filename' }
    $profilePath = Join-Path (Join-Path $repo 'profiles') $profileName
    if (-not (Test-Path -LiteralPath $profilePath -PathType Leaf)) { throw 'Identified revision profile is missing' }
    $argsList += @('--profile', $profilePath)
}
if ($Session) { $argsList += @('--session', [IO.Path]::GetFullPath($Session)) }
& $Python @argsList
if ($LASTEXITCODE -ne 0) { throw 'Module audit failed' }
if ($AuditOnly) { return }
& $Python (Join-Path $PSScriptRoot 'generate.py') --framework saturn-recomp --work $workPath --profile (Join-Path $audit 'candidate-profile.json') --out $generated
if ($LASTEXITCODE -ne 0) { throw 'Bulk generation failed' }
& $Python (Join-Path $PSScriptRoot 'check-module-build.py') --audit (Join-Path $audit 'module-audit.json') --generated $generated --out (Join-Path $audit 'emission-check.json')
if ($LASTEXITCODE -ne 0) { throw 'Audited module/entry emission gate failed' }
. (Join-Path $PSScriptRoot 'dev-env.ps1')
& (Join-Path $PSScriptRoot 'build-headless.ps1') -Generated $generated -Build $build -Runtime (Join-Path $repo '.local/saturn-recomp/runtime') -WithWindow:(!$Headless) -NoActivate
Write-Output "Built $build. Launcher selection stays unchanged until replay validation. Review module-audit/summary.txt and module-audit.json for unresolved coverage."
