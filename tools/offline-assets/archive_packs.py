"""Measure local artwork packs and create optional verified ZIPs without changing them.

Only user-supplied external directories are read/written. Compression samples are
stratified by scenario, style and world/character role with an explicit seed.
Their projected sizes are estimates; optional ZIP results are actual measurements.
"""
import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import random
import time
import zipfile
import zlib

from PIL import Image


def external(path):
    path = Path(path).resolve()
    if any((parent / '.git').exists() for parent in (path, *path.parents)):
        raise ValueError('Choose an output directory outside a source repository')
    return path


def files_under(folder):
    """Use scandir and cached stat results instead of repeated directory walks."""
    with os.scandir(folder) as entries:
        for entry in sorted(entries, key=lambda entry: entry.name):
            if entry.name == 'materials.sf3idx' or entry.name.startswith('.index-temp'):
                continue  # Regenerable startup cache is unnecessary in backups.
            if entry.is_dir(follow_symlinks=False):
                yield from files_under(entry.path)
            elif entry.is_file(follow_symlinks=False):
                info = entry.stat(follow_symlinks=False)
                # Windows DirEntry.stat uses enumeration metadata with inode 0;
                # a normal stat opens the file to obtain its stable NTFS ID.
                if not info.st_ino:
                    info = os.stat(entry.path, follow_symlinks=False)
                yield Path(entry.path), info
            else:
                raise ValueError('Unsupported symlink or special file: ' + entry.path)


def inventory(pack, global_unique):
    total = Counter()
    unique = {}
    for path, info in files_under(pack):
        key = (info.st_dev, info.st_ino)
        if not info.st_ino:
            raise ValueError('Filesystem does not expose a stable file identity')
        if key in global_unique and global_unique[key] != info.st_size:
            raise ValueError('File changed during inventory: ' + str(path))
        global_unique[key] = info.st_size
        unique[key] = info.st_size
        total['logical_bytes'] += info.st_size
        total['file_count'] += 1
        total['hardlinked_paths'] += info.st_nlink > 1
        total['bytes:' + path.name] += info.st_size
    result = dict(total)
    result.update(unique_file_bytes=sum(unique.values()), unique_files=len(unique))
    return result


def sample_group(paths, label, count, seed):
    paths = sorted(paths)
    # Independent stable seed: adding a new scenario does not change old samples.
    rng = random.Random(hashlib.sha256(f'{seed}/{label}'.encode()).digest())
    return sorted(rng.sample(paths, min(count, len(paths))))


def measure_sample(paths, pack, archive, label):
    result = {'label': label, 'materials': len(paths), 'raw_bytes': 0,
              'zlib_1_bytes': 0, 'zlib_6_bytes': 0, 'png_6_bytes': 0,
              'zlib_1_seconds': 0, 'zlib_6_seconds': 0, 'png_6_seconds': 0,
              'samples': []}
    for material in paths:
        path = material / 'replacement.rgba'
        raw = path.read_bytes()
        lines = (material / 'asset.txt').read_text(encoding='utf-8').splitlines()
        if len(lines) < 3 or lines[0] != 'SF3HDASSET1':
            raise ValueError('Unsupported material: ' + str(material))
        width, height = map(int, lines[2].split())
        if len(raw) != width * height * 4:
            raise ValueError('Invalid replacement dimensions: ' + str(path))
        digest = hashlib.sha256(raw).hexdigest()
        row = {'id': material.name, 'width': width, 'height': height,
               'raw_bytes': len(raw), 'sha256': digest}
        result['raw_bytes'] += len(raw)
        for level in (1, 6):
            started = time.perf_counter()
            compressed = zlib.compress(raw, level)
            elapsed = time.perf_counter() - started
            if zlib.decompress(compressed) != raw:
                raise AssertionError('zlib round trip failed')
            result[f'zlib_{level}_bytes'] += len(compressed)
            result[f'zlib_{level}_seconds'] += elapsed
            row[f'zlib_{level}_bytes'] = len(compressed)
        started = time.perf_counter()
        buffer = io.BytesIO()
        Image.frombytes('RGBA', (width, height), raw).save(
            buffer, format='PNG', compress_level=6)
        encoded = buffer.getvalue()
        result['png_6_seconds'] += time.perf_counter() - started
        with Image.open(io.BytesIO(encoded)) as decoded:
            if decoded.convert('RGBA').tobytes() != raw:
                raise AssertionError('PNG round trip failed')
        row['png_6_bytes'] = len(encoded)
        result['png_6_bytes'] += len(encoded)
        # The ZIP sample includes all existing runtime files, preserving format.
        for source, _ in files_under(material):
            archive.write(source, label + '/' + source.relative_to(pack).as_posix())
        result['samples'].append(row)
    return result


def verified_zip(pack, target):
    if target.exists():
        raise FileExistsError('Refusing to overwrite an existing archive: ' + str(target))
    started = time.perf_counter()
    source_hashes = {}
    logical_bytes = 0
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as archive:
        for source, info in files_under(pack):
            relative = source.relative_to(pack).as_posix()
            member_info = zipfile.ZipInfo(relative)
            member_info.compress_type = zipfile.ZIP_DEFLATED
            member_info.file_size = info.st_size
            member_info.external_attr = (info.st_mode & 0xffff) << 16
            digest = hashlib.sha256()
            actual_size = 0
            # Hash while copying: one source open/read instead of two per file.
            with source.open('rb') as stream, archive.open(member_info, 'w', force_zip64=info.st_size >= 2**31) as member:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    actual_size += len(chunk)
                    member.write(chunk)
            if actual_size != info.st_size:
                raise ValueError('Source changed while archiving: ' + str(source))
            source_hashes[relative] = digest.hexdigest()
            logical_bytes += info.st_size
    write_seconds = time.perf_counter() - started
    verify_started = time.perf_counter()
    with zipfile.ZipFile(target) as archive:
        if set(archive.namelist()) != set(source_hashes):
            raise AssertionError('ZIP member list differs from source')
        for name in archive.namelist():
            with archive.open(name) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != source_hashes[name]:
                    raise AssertionError('ZIP round trip differs: ' + name)
    with target.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(target), 'logical_bytes': logical_bytes,
            'archive_bytes': target.stat().st_size, 'sha256': digest,
            'files': len(source_hashes), 'compression_seconds': write_seconds,
            'verification_seconds': time.perf_counter() - verify_started,
            'verified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packs-report', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--sample-per-category', type=int, default=32)
    parser.add_argument('--seed', type=int, default=20261023)
    parser.add_argument('--archive', action='append', default=[], metavar='SCENARIO/MODEL',
                        help='Create and fully verify this complete ZIP, e.g. 2/video')
    args = parser.parse_args()
    if args.sample_per_category < 1:
        parser.error('sample-per-category must be positive')
    if os.name == 'nt':
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    output = external(args.output)
    rows = json.loads(args.packs_report.read_text(encoding='utf-8'))
    for row in rows:
        source = Path(row['path']).resolve()
        if output == source or output.is_relative_to(source):
            parser.error('Output must be outside every assessed pack')
    output.mkdir(parents=True, exist_ok=True)
    selected = {str(row['scenario']) + '/' + row['model']: row for row in rows}
    unknown = set(args.archive) - selected.keys()
    if unknown:
        parser.error('Unknown archive packs: ' + ', '.join(sorted(unknown)))
    report = {'seed': args.seed, 'sample_per_category': args.sample_per_category,
              'started_unix': time.time(), 'packs': [], 'samples': [], 'archives': [],
              'notes': [
                  'Logical bytes count every pathname. Unique file bytes deduplicate hardlinks within the assessed packs.',
                  'Unique file bytes are not physical allocated storage: cluster size, filesystem compression and cache links outside these packs are not measured.',
                  'Sample projection is approximate and covers replacement RGBA payload only; ZIP sample includes material metadata/originals too.',
                  'Lossless PNG is a potential future storage format. Current native packs still require RGBA.',
                  'Regenerable materials.sf3idx startup indexes and .index-temp files are excluded.',
              ]}
    unique = {}
    sample_zip = output / 'stratified-material-sample.zip'
    if sample_zip.exists():
        raise FileExistsError('Choose a new output directory; sample ZIP already exists')
    with zipfile.ZipFile(sample_zip, 'x', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as archive:
        for key, row in sorted(selected.items()):
            pack = Path(row['path'])
            world = {entry.name for entry in Path(row['source_world']).iterdir() if entry.is_dir()}
            paths = [entry for entry in pack.iterdir() if entry.is_dir()]
            measured = {'scenario': row['scenario'], 'model': row['model'], 'path': str(pack),
                        **inventory(pack, unique)}
            report['packs'].append(measured)
            print(key, measured['logical_bytes'], 'logical bytes', flush=True)
            for category in ('world', 'characters'):
                candidates = [path for path in paths if (path.name in world) == (category == 'world')]
                label = key + '/' + category
                sample = sample_group(candidates, label, args.sample_per_category, args.seed)
                result = measure_sample(sample, pack, archive, label)
                result['population_materials'] = len(candidates)
                result['population_replacement_bytes'] = row['replacement_bytes'] - row['character_replacement_bytes'] if category == 'world' else row['character_replacement_bytes']
                for kind in ('zlib_1', 'zlib_6', 'png_6'):
                    ratio = result[kind + '_bytes'] / result['raw_bytes']
                    result[kind + '_projected_bytes_ESTIMATE'] = round(ratio * result['population_replacement_bytes'])
                report['samples'].append(result)
    # ZIP CRC catches corruption in every sample member, in addition to RGBA codec byte checks above.
    with zipfile.ZipFile(sample_zip) as archive:
        if archive.testzip() is not None:
            raise AssertionError('Sample ZIP failed CRC verification')
    report['sample_archive'] = {'path': str(sample_zip), 'bytes': sample_zip.stat().st_size,
                                'crc_verified': True}
    report['logical_total_bytes'] = sum(row['logical_bytes'] for row in report['packs'])
    report['unique_file_bytes_within_assessed_packs'] = sum(unique.values())
    report['unique_files_within_assessed_packs'] = len(unique)
    # Preserve completed measurements even if a lengthy optional archive is stopped.
    (output / 'measurement-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    for key in args.archive:
        print('Compressing complete pack', key, flush=True)
        report['archives'].append(verified_zip(Path(selected[key]['path']), output / ('scenario-' + key.replace('/', '-') + '.zip')))
    report['finished_unix'] = time.time()
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('Report:', output / 'report.json', flush=True)


if __name__ == '__main__':
    main()
