"""Build immutable native-pack startup indexes using only the Python standard library.

Run on a pack root or a parent containing pack roots. All game bytes stay beside
the supplied packs. A publisher must change manifest.json whenever a pack changes;
the runtime compares that exact small file before trusting the index. The index
does not validate replacement files at startup: they retain lazy size/read checks.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import struct
import tempfile
import time


MAGIC = b'SF3HDIX1'
HEADER = struct.Struct('<8sIIQQQIIQQ')
RECORD = struct.Struct('<8I4f')
NAME = 'materials.sf3idx'
FNV_OFFSET = 14695981039346656037
FNV_PRIME = 1099511628211
MAX_BYTES = 512 * 1024 * 1024
MAX_MANIFEST = 16 * 1024 * 1024
MAX_ENTRIES = 100000
SAFE = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*\Z', re.ASCII)


def fnv(data, value=FNV_OFFSET):
    for byte in data:
        value = ((value ^ byte) * FNV_PRIME) & 0xffffffffffffffff
    return value


def material(directory):
    """Validate an indexed material before publishing any cached startup result."""
    if directory.is_symlink() or not SAFE.fullmatch(directory.name) or directory.name.endswith('.'):
        raise ValueError(f'Unsafe material directory: {directory.name}')
    path = (directory.name + '/replacement.rgba').encode('ascii')
    if len(path) > 240:
        raise ValueError(f'Material path is too long: {directory.name}')
    for name in ('asset.txt', 'original.rgba', 'replacement.rgba'):
        if (directory / name).is_symlink():
            raise ValueError(f'Material file must not be a symlink: {directory.name}/{name}')
    fields = (directory / 'asset.txt').read_text(encoding='ascii').split()
    if len(fields) < 5 or fields[0] != 'SF3HDASSET1':
        raise ValueError(f'Invalid descriptor: {directory.name}')
    w, h, hw, hh = map(int, fields[1:5])
    if not (1 <= w <= 1024 and 1 <= h <= 1024 and w <= hw <= 4096 and h <= hh <= 4096):
        raise ValueError(f'Invalid material dimensions: {directory.name}')
    uv = (0., 0., 1., 1.)
    character = 0
    if len(fields) > 5:
        if len(fields) < 9:
            raise ValueError(f'Incomplete UV descriptor: {directory.name}')
        # Round to the same binary32 values consumed by the native reader.
        uv = struct.unpack('<4f', struct.pack('<4f', *map(float, fields[5:9])))
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in uv) or uv[2] <= uv[0] or uv[3] <= uv[1]:
            raise ValueError(f'Invalid material UV: {directory.name}')
        if len(fields) > 9:
            if fields[9] not in ('character', 'world'):
                raise ValueError(f'Invalid material type: {directory.name}')
            character = int(fields[9] == 'character')
    original = (directory / 'original.rgba').read_bytes()
    if len(original) != w * h * 4 or (directory / 'replacement.rgba').stat().st_size != hw * hh * 4:
        raise ValueError(f'Material payload size mismatch: {directory.name}')
    return RECORD.pack(w, h, hw, hh, character, len(path), len(original), 0, *uv), path, original


def build_index(root):
    root = Path(root).resolve()
    marker = (root / 'manifest.json').read_bytes()
    if len(marker) > MAX_MANIFEST:
        raise ValueError('Pack manifest exceeds the index limit')
    # Parsing also catches an incomplete manifest write before publishing an index.
    json.loads(marker)
    started = time.perf_counter()
    fd, temporary = tempfile.mkstemp(prefix='.sf3idx-', suffix='.tmp', dir=root)
    count = size = 0
    checksum = FNV_OFFSET
    try:
        with os.fdopen(fd, 'w+b') as out:
            out.write(bytes(HEADER.size))
            # Preserve filesystem enumeration order used by directory_iterator, so
            # a pre-existing duplicate original keeps the same match precedence.
            with os.scandir(root) as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False):
                        if entry.is_symlink() and (Path(entry.path) / 'asset.txt').exists():
                            raise ValueError(f'Symlink material directory: {entry.name}')
                        continue
                    directory = Path(entry.path)
                    if not (directory / 'asset.txt').exists():
                        continue
                    chunks = material(directory)
                    count += 1
                    if count > MAX_ENTRIES:
                        raise ValueError('Pack exceeds the entry limit')
                    for chunk in chunks:
                        size += len(chunk)
                        if HEADER.size + size > MAX_BYTES:
                            raise ValueError('Pack original pixels exceed the index limit')
                        checksum = fnv(chunk, checksum)
                        out.write(chunk)
            if (root / 'manifest.json').read_bytes() != marker:
                raise ValueError('Pack manifest changed during indexing; retry once the builder is stopped')
            out.seek(0)
            out.write(HEADER.pack(MAGIC, 1, HEADER.size, HEADER.size + size,
                                  fnv(marker), checksum, count, 0, len(marker), 0))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, root / NAME)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return dict(pack=str(root), materials=count, index_bytes=HEADER.size + size,
                seconds=round(time.perf_counter() - started, 3),
                validation='Manifest, descriptor, original length and replacement length at index creation; replacement reads remain lazy')


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('roots', nargs='+', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    packs = []
    for root in args.roots:
        root = root.resolve()
        if (root / 'manifest.json').is_file():
            packs.append(root)
        elif (root / 'packs-report.json').is_file():
            # Builder reports avoid traversing hundreds of thousands of payload
            # files just to discover a handful of pack roots.
            records = json.loads((root / 'packs-report.json').read_text(encoding='utf-8-sig'))
            for record in records:
                candidate = Path(record['path']).resolve()
                if candidate != root and root not in candidate.parents:
                    raise ValueError('Pack report path escapes the selected root')
                if not (candidate / 'manifest.json').is_file():
                    raise ValueError('Pack report names a missing manifest: ' + str(candidate))
                packs.append(candidate)
        else:
            packs.extend(path.parent for path in root.rglob('manifest.json'))
    packs = list(dict.fromkeys(packs))
    if not packs:
        parser.error('No pack manifest.json found')
    report = []
    for root in packs:
        try:
            record = dict(build_index(root), passed=True)
        except (OSError, ValueError, OverflowError, struct.error) as error:
            record = dict(pack=str(root), passed=False, error=str(error))
        report.append(record)
        print(json.dumps(record), flush=True)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if all(record['passed'] for record in report) else 1


if __name__ == '__main__':
    raise SystemExit(main())
