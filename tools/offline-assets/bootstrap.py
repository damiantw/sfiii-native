"""One-time user-local dependency preparation for the optional Windows builder.

The published ZIP contains no SF3Tools implementation/resources, model weights or
game-derived artwork. This program fetches pinned upstream archives and compiles
the extraction adapter automatically on the user's own computer.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

APP = Path(__file__).resolve().parent
ROOT = APP.parent
REVISION = '35d64099970b9d6e96d1e07c5ec2c522c4b37969'
DEPENDENCIES = {
    'sf3tools': dict(filename='sf3tools.zip',
        url='https://codeload.github.com/Synival/sf3tools/zip/' + REVISION,
        sha256='4612f00af9cfca47e664110aac2e4ea16df1952c15f215b93b1a91facfa1e835'),
    'dotnet': dict(filename='dotnet-sdk-9.0.305-win-x64.zip',
        url='https://builds.dotnet.microsoft.com/dotnet/Sdk/9.0.305/dotnet-sdk-9.0.305-win-x64.zip',
        sha512='dba55e7566acf4f33bf0dc4f2378bca891a3320070c11a24ac27e22ffdd6d1ffb11aac670d4b5f2a056d0698c72db23a787749e054c828109b6554b4062bc31d'),
    'upscaler': dict(filename='realesrgan-ncnn-vulkan-20220424-windows.zip',
        url='https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip',
        sha256='abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d'),
    'chdman': dict(filename='mame0289b_x64.exe',
        url='https://github.com/mamedev/mame/releases/download/mame0289/mame0289b_x64.exe',
        sha256='a1aa7912168c9d1b05e611906bc21b8b9be3935822aead36d12a1da363150b7d'),
}


def digest(path, algorithm='sha256'):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def external(path):
    path = Path(path).resolve()
    if any((p / '.git').exists() for p in (path, *path.parents)):
        raise ValueError('Extract the builder outside a source repository before starting it.')
    return path


def download(spec, cache):
    algorithm = 'sha512' if 'sha512' in spec else 'sha256'
    archive = cache / spec['filename']
    if archive.is_file() and digest(archive, algorithm) == spec[algorithm]:
        print('Using verified download: ' + archive.name, flush=True)
        return archive
    temporary = archive.with_name(archive.name + '.partial')
    print('Downloading ' + spec['url'], flush=True)
    request = urllib.request.Request(spec['url'], headers={'User-Agent': 'SFIII-Offline-Graphics-Builder'})
    try:
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open('wb') as output:
            total = int(response.headers.get('Content-Length', 0)); done = 0; last = time.monotonic()
            while block := response.read(1024 * 1024):
                output.write(block); done += len(block)
                if time.monotonic() - last > 3:
                    print(f'  {done // 1048576} MiB' + (f' / {total // 1048576} MiB' if total else ''), flush=True)
                    last = time.monotonic()
        if digest(temporary, algorithm) != spec[algorithm]:
            raise ValueError('Upstream download checksum mismatch: ' + archive.name)
        os.replace(temporary, archive)
        return archive
    finally:
        temporary.unlink(missing_ok=True)


def extract_zip(archive, destination, strip_prefix='', include=()):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            name = item.filename
            if strip_prefix:
                if not name.startswith(strip_prefix):
                    continue
                name = name[len(strip_prefix):]
            if not name or (include and not name.startswith(include)):
                continue
            target = (destination / name).resolve()
            if target != destination and destination not in target.parents:
                raise ValueError('Unsafe upstream archive member')
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unexpected upstream archive symlink')
            # The SDK and SF3Tools contain deep paths; portable installs are often
            # already nested under Downloads. Extended Windows paths avoid MAX_PATH.
            filesystem_target = Path('\\\\?\\' + str(target)) if os.name == 'nt' else target
            if item.is_dir():
                filesystem_target.mkdir(parents=True, exist_ok=True)
            else:
                filesystem_target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(item) as incoming, filesystem_target.open('wb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing)


@contextmanager
def short_build_root(root):
    """Give MSBuild/NuGet short user-local paths without moving any files.

    Some upstream MSBuild copy tasks still reject ordinary paths over MAX_PATH.
    SUBST is a per-user temporary alias, requires no administrator permission,
    and is removed as soon as preparation finishes (including failures).
    """
    if os.name != 'nt':
        yield root
        return
    import ctypes
    command = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/subst.exe')
    for letter in 'ZYXWVUTSRQPONMLKJIHGFED':
        name = letter + ':'
        buffer = ctypes.create_unicode_buffer(4096)
        if ctypes.windll.kernel32.QueryDosDeviceW(name, buffer, len(buffer)):
            continue
        result = subprocess.run([command, name, str(root)], capture_output=True)
        if result.returncode:
            continue
        try:
            yield Path(name + '\\')
        finally:
            subprocess.run([command, name, '/D'], capture_output=True)
        return
    raise RuntimeError('No unused drive letter is available for temporary local preparation. '
                       'Extract the builder into a short folder path and retry.')


def compile_extractor(root):
    with short_build_root(root) as alias:
        app = alias / 'app'; build = alias / 'setup-work'; source = build / 'sf'; sdk = build / 'dotnet'
        import xml.sax.saxutils
        escape = xml.sax.saxutils.escape
        project = build / 'extractor'; project.mkdir(exist_ok=True)
        project_path = project / 'ExtractAssets.csproj'
        project_path.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
            '<TargetFramework>net9.0</TargetFramework><LangVersion>latest</LangVersion><Nullable>enable</Nullable>'
            '<ImplicitUsings>enable</ImplicitUsings><EnableDefaultCompileItems>false</EnableDefaultCompileItems>'
            '</PropertyGroup><ItemGroup><Compile Include="' + escape(str(app / 'ExtractAssets.cs'), {'"': '&quot;'}) + '"/>'
            '<ProjectReference Include="' + escape(str(source / 'SF3Lib/SF3Lib.csproj'), {'"': '&quot;'}) +
            '"/></ItemGroup></Project>', encoding='utf-8')
        env = os.environ.copy()
        env.update(DOTNET_ROOT=str(sdk), DOTNET_CLI_HOME=str(build / 'dotnet-home'),
                   DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1', DOTNET_CLI_TELEMETRY_OPTOUT='1',
                   DOTNET_NOLOGO='1', NUGET_PACKAGES=str(build / 'nuget'))
        print('Preparing local extractor automatically (this may take a few minutes)...', flush=True)
        log = root / 'extractor-setup.log'
        with log.open('w', encoding='utf-8') as output:
            result = subprocess.run([str(sdk / 'dotnet.exe'), 'publish', str(project_path), '-c', 'Release', '-r', 'win-x64',
                '--self-contained', 'true', '-p:LangVersion=latest', '-p:DebugType=none', '-p:DebugSymbols=false',
                '--artifacts-path', str(build / 'artifacts'), '-o', str(app / 'extractor'), '--nologo', '-v', 'quiet'],
                cwd=str(alias), env=env, stdout=output, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError('Local extractor preparation failed. See ' + str(log))


def prepare(root=ROOT, include_chd=False):
    root = external(root); app = root / 'app'
    cache = root / 'setup-cache'; cache.mkdir(parents=True, exist_ok=True)
    build = root / 'setup-work'; build.mkdir(exist_ok=True)
    stamp_path = app / 'setup-complete.json'
    adapter_hash = digest(app / 'ExtractAssets.cs')
    signature = hashlib.sha256((json.dumps(DEPENDENCIES, sort_keys=True) + adapter_hash).encode()).hexdigest()
    expected = [app / 'extractor/ExtractAssets.exe', app / 'upscaler/realesrgan-ncnn-vulkan.exe',
                app / 'upscaler/models/realesrgan-x4plus.bin', app / 'upscaler/models/realesrgan-x4plus-anime.bin',
                app / 'upscaler/models/realesr-animevideov3-x4.bin']
    try:
        stamp = json.loads(stamp_path.read_text())
    except (OSError, ValueError):
        stamp = {}
    if stamp.get('signature') != signature or not all(p.is_file() for p in expected):
        print('First-run setup downloads tools from their authors and builds the extractor locally.', flush=True)
        print('No game data, BIOS or saves are uploaded. NuGet restore also contacts nuget.org.', flush=True)
        source_zip = download(DEPENDENCIES['sf3tools'], cache)
        sdk_zip = download(DEPENDENCIES['dotnet'], cache)
        gpu_zip = download(DEPENDENCIES['upscaler'], cache)
        source = build / 'sf'; sdk = build / 'dotnet'
        if not (source / '.extraction-complete').is_file():
            print('Extracting upstream SF3Tools for local use only...', flush=True)
            extract_zip(source_zip, source, 'sf3tools-' + REVISION + '/', ('SF3Lib/', 'CommonLib/'))
            (source / '.extraction-complete').write_text(DEPENDENCIES['sf3tools']['sha256'])
        if not (sdk / '.extraction-complete').is_file():
            print('Extracting portable .NET SDK...', flush=True)
            extract_zip(sdk_zip, sdk)
            (sdk / '.extraction-complete').write_text(DEPENDENCIES['dotnet']['sha512'])
        if not (app / 'upscaler/.extraction-complete').is_file():
            extract_zip(gpu_zip, app / 'upscaler')
            (app / 'upscaler/.extraction-complete').write_text(DEPENDENCIES['upscaler']['sha256'])
        compile_extractor(root)
        if not all(p.is_file() for p in expected):
            raise RuntimeError('Dependency preparation did not produce the expected files.')
        stamp_path.write_text(json.dumps(dict(signature=signature, sf3tools_revision=REVISION,
            redistribution='Downloaded SF3Tools and its generated local binaries/resources must not be redistributed.'), indent=2) + '\n')
        print('Local GPU builder preparation complete.', flush=True)
    if include_chd and not (app / 'chdman/chdman.exe').is_file():
        archive = download(DEPENDENCIES['chdman'], cache)
        destination = app / 'chdman'; destination.mkdir(exist_ok=True)
        print('Preparing the separate CHD image utility...', flush=True)
        # The official self-extractor may ignore member filters. Retain only the
        # standalone image utility and notices, never unrelated emulator programs.
        with tempfile.TemporaryDirectory(prefix='chd-', dir=build) as temporary:
            staging = Path(temporary)
            subprocess.run([str(archive), '-o' + str(staging), '-y', 'chdman.exe', 'COPYING', 'docs/legal/*'],
                           check=True, stdout=subprocess.DEVNULL)
            for name in ('chdman.exe', 'COPYING'):
                shutil.copy2(staging / name, destination / name)
            shutil.copytree(staging / 'docs/legal', destination / 'docs/legal', dirs_exist_ok=True)
        if not (destination / 'chdman.exe').is_file():
            raise ValueError('CHD utility missing from its official archive.')
    settings = root / 'settings.json'
    if not settings.exists():
        settings.write_text(json.dumps(dict(scenarios=[], out=str(Path.home() / 'SFIII Graphics'), gpu=0,
            models=['video', 'anime', 'general'], categories=['world', 'sprites', 'backgrounds']), indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--with-chd', action='store_true', help='Also fetch the optional CHD conversion tool')
    args = parser.parse_args()
    try:
        prepare(include_chd=args.with_chd)
        if not args.prepare_only:
            subprocess.Popen([str(ROOT / 'runtime/pythonw.exe'), str(APP / 'gui.py')], cwd=str(ROOT),
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        return 0
    except Exception as error:
        print('\nSetup stopped: ' + str(error), flush=True)
        print('Completed downloads are cached. Run the same launcher to retry.', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
