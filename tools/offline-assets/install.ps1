param(
    [Parameter(Mandatory=$true)][string]$Destination,
    [Parameter(Mandatory=$true)][string]$PythonRoot,
    [Parameter(Mandatory=$true)][string]$SF3ToolsRoot,
    [Parameter(Mandatory=$true)][string]$FrameworkRoot,
    [Parameter(Mandatory=$true)][string]$UpscalerRoot,
    [Parameter(Mandatory=$true)][string]$Chdman,
    [string]$Icon = '',
    [switch]$DesktopShortcut
)
$ErrorActionPreference = 'Stop'
$Destination = [IO.Path]::GetFullPath($Destination)
for($folder=[IO.DirectoryInfo]$Destination;$null -ne $folder;$folder=$folder.Parent) {
    if(Test-Path -LiteralPath (Join-Path $folder.FullName '.git')) {throw 'Install outside a source repository'}
}
$app = Join-Path $Destination 'app'
New-Item -ItemType Directory -Force $app | Out-Null
$runtime = Join-Path $Destination 'runtime'
$copyRuntime = @'
import importlib.metadata,pathlib,shutil,sys
source=pathlib.Path(sys.argv[1]);dest=pathlib.Path(sys.argv[2]);dest.mkdir(parents=True,exist_ok=True)
for p in source.iterdir():
    if p.is_file() and (p.suffix.lower() in ('.exe','.dll') or p.name.lower().startswith('license')):shutil.copy2(p,dest/p.name)
for name in ('DLLs','Lib','tcl'):
    if (source/name).exists():shutil.copytree(source/name,dest/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('site-packages','__pycache__'))
import PIL
packages=dest/'Lib'/'site-packages';packages.mkdir(parents=True,exist_ok=True)
shutil.copytree(pathlib.Path(PIL.__file__).parent,packages/'PIL',dirs_exist_ok=True)
distribution=importlib.metadata.distribution('Pillow')
for path in distribution.files or []:
    if path.parts[0].endswith('.dist-info') or path.parts[0].lower().startswith('pillow.libs'):
        p=pathlib.Path(distribution.locate_file(path));target=packages/path
        if p.is_file():target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
'@
& (Join-Path $PythonRoot 'python.exe') -c $copyRuntime $PythonRoot $runtime
if($LASTEXITCODE -ne 0){throw 'Could not assemble standalone Python runtime'}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'worker.py'),(Join-Path $PSScriptRoot 'gui.py'),(Join-Path $PSScriptRoot 'select_packs.py'),(Join-Path $PSScriptRoot 'character_packs.py'),(Join-Path $PSScriptRoot 'index_packs.py'),(Join-Path $PSScriptRoot 'archive_packs.py'),(Join-Path $PSScriptRoot 'bootstrap.py'),(Join-Path $PSScriptRoot 'ExtractAssets.cs') -Destination $app -Force
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Copy-Item -LiteralPath (Join-Path $repo 'desktop\disc_input.py'),(Join-Path $repo 'tools\disc_profile.py'),(Join-Path $repo 'desktop\ai_packs.py') -Destination $app -Force
New-Item -ItemType Directory -Force (Join-Path $app 'profiles'),(Join-Path $app 'vendor\saturnrecomp'),(Join-Path $app 'chdman') | Out-Null
Get-ChildItem (Join-Path $repo 'profiles') -Filter '*.json' | Copy-Item -Destination (Join-Path $app 'profiles') -Force
Copy-Item -LiteralPath (Join-Path $FrameworkRoot 'src\saturnrecomp\disc.py') -Destination (Join-Path $app 'vendor\saturnrecomp\disc.py') -Force
[IO.File]::WriteAllText((Join-Path $app 'vendor\saturnrecomp\__init__.py'),'')
Copy-Item -LiteralPath (Join-Path $repo 'LICENSES\saturn-recomp.txt') -Destination (Join-Path $app 'vendor\SATURN-RECOMP-LICENSE.txt') -Force
& (Join-Path $runtime 'python.exe') -c 'import shutil,sys;shutil.copytree(sys.argv[1],sys.argv[2],dirs_exist_ok=True)' $UpscalerRoot (Join-Path $app 'upscaler')
if($LASTEXITCODE -ne 0){throw 'Could not copy local GPU upscaler'}
Copy-Item -LiteralPath $Chdman -Destination (Join-Path $app 'chdman\chdman.exe') -Force
if($Icon){Copy-Item -LiteralPath $Icon -Destination (Join-Path $app 'app.ico') -Force}
$projectDirectory = Join-Path $Destination 'extractor-project'
New-Item -ItemType Directory -Force $projectDirectory | Out-Null
$source = [Security.SecurityElement]::Escape((Join-Path $PSScriptRoot 'ExtractAssets.cs'))
$library = [Security.SecurityElement]::Escape((Join-Path $SF3ToolsRoot 'SF3Lib\SF3Lib.csproj'))
$project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net9.0</TargetFramework><LangVersion>latest</LangVersion><Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings><EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup><ItemGroup><Compile Include="'+$source+'"/><ProjectReference Include="'+$library+'"/></ItemGroup></Project>'
[IO.File]::WriteAllText((Join-Path $projectDirectory 'ExtractAssets.csproj'),$project)
& dotnet publish (Join-Path $projectDirectory 'ExtractAssets.csproj') -c Release -r win-x64 --self-contained true -p:LangVersion=latest -p:DebugType=none -p:DebugSymbols=false --artifacts-path (Join-Path $Destination 'build-artifacts') -o (Join-Path $app 'extractor') --nologo -v quiet *> (Join-Path $Destination 'extractor-build.log')
if($LASTEXITCODE -ne 0){throw 'Extractor build failed; see extractor-build.log'}
$config=Join-Path $Destination 'settings.json'
if(-not(Test-Path -LiteralPath $config)) {
    @{scenarios=@();out=(Join-Path $Destination 'output');gpu=0;models=@('video','anime','general');categories=@('world','sprites','backgrounds')} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $config -Encoding utf8
}
$launcher = '@echo off'+"`r`n"+'start "SFIII Offline Graphics Builder" "%~dp0runtime\pythonw.exe" "%~dp0app\gui.py"'+"`r`n"
[IO.File]::WriteAllText((Join-Path $Destination 'Start Offline Graphics Builder.cmd'),$launcher,[Text.Encoding]::ASCII)
if($DesktopShortcut) {
    $shell=New-Object -ComObject WScript.Shell
    $shortcut=$shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'SFIII Offline Graphics Builder.lnk'))
    $shortcut.TargetPath=Join-Path $Destination 'Start Offline Graphics Builder.cmd';$shortcut.WorkingDirectory=$Destination
    $shortcut.Description='Local GPU artwork generation; no Codex or cloud connection required'
    if($Icon){$shortcut.IconLocation=Join-Path $app 'app.ico'}
    $shortcut.Save()
}
Write-Output ('Standalone builder installed: '+$Destination)
