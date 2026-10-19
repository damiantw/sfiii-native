"""Import validated raw Scenario 1 saves into a native backup, without editing payloads."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import time


def records(data):
    result = {}
    while data:
        if len(data) < 32:
            raise ValueError('Truncated native backup header')
        head, data = data[:32], data[32:]
        name = head[:12].split(b'\0')[0].decode('ascii')
        size = struct.unpack_from('<I', head, 28)[0]
        if not name or name in result or size > 524288 or size > len(data):
            raise ValueError('Invalid or duplicate native backup record')
        result[name] = head + data[:size]
        data = data[size:]
    return result


def raw_record(path):
    data = path.read_bytes()
    if not re.fullmatch(r'SFORCE31_[0-9]{2}', path.stem, re.IGNORECASE):
        raise ValueError('Raw saves must retain their Saturn filename: SFORCE31_XX.BIN')
    if len(data) != 12904 or int.from_bytes(data[:4], 'big') != len(data)-8:
        raise ValueError('Unsupported raw save layout; expected Scenario 1, 12904 bytes')
    if int.from_bytes(data[4:8], 'big') != sum(data[8:]):
        raise ValueError('SFIII payload checksum mismatch; original file was not changed')
    name = path.stem.upper()
    # Raw exports have no directory metadata. Date/comment below are import
    # metadata, not a reconstruction of the original Saturn directory entry.
    date = max(0, int((datetime.datetime.now()-datetime.datetime(1980, 1, 1)).total_seconds()/60))
    head = name.encode().ljust(12, b'\0') + b'Imported'.ljust(11, b'\0') + b'\x01' + struct.pack('<II', date, len(data))
    return name, head+data


def import_files(backup, device, sources, replace=False):
    backup = backup.resolve()
    for parent in [backup.parent, *backup.parents]:
        if (parent/'.git').exists():
            raise ValueError('Save data must stay outside the source repository')
    target = Path(str(backup)+('.cartridge' if device == 'cartridge' else ''))
    old = target.read_bytes() if target.exists() else b''
    existing = records(old)
    added, seen = [], set()
    for path in sources:
        path = path.resolve()
        if path == target:
            raise ValueError('Import source cannot be the native backup')
        name, record = raw_record(path)
        if name in seen or (name in existing and not replace):
            raise ValueError(f'{name} already exists; import was cancelled without changes')
        seen.add(name)
        existing[name] = record
        added.append(dict(name=name, source=str(path), bytes=len(record)-32,
                          payload_sha256=hashlib.sha256(record[32:]).hexdigest()))
    size, block = (32768, 64) if device == 'internal' else (524288, 512)
    used = sum(((len(v)-32+34+block-1)//block)+1 for v in existing.values())
    if used > size//block-2:
        raise ValueError('Not enough space on this device. Choose cartridge memory; no files were changed.')
    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = str(time.time_ns())
    previous = Path(str(target)+'.before-import-'+stamp)
    if target.exists():
        with previous.open('xb') as f:
            f.write(old)
    output = b''.join(existing[k] for k in sorted(existing))
    fd, temporary = tempfile.mkstemp(prefix='save-import-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(output)
            f.flush()
            os.fsync(f.fileno())
        if (target.read_bytes() if target.exists() else b'') != old:
            raise ValueError('Backup changed during import. Close the game and retry.')
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    report = dict(device=device, target=str(target), previous=str(previous) if previous.exists() else None,
                  imported=added, used_blocks=used, available_blocks=size//block-2,
                  metadata='Filename retained; comment/date generated at import because raw BIN lacks directory metadata')
    Path(str(target)+'.import-'+stamp+'.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    ap = argparse.ArgumentParser(__doc__)
    ap.add_argument('--backup', type=Path, required=True)
    ap.add_argument('--device', choices=['internal', 'cartridge'], default='cartridge')
    ap.add_argument('--replace', action='store_true', help='Explicitly replace matching names; previous backup retained')
    ap.add_argument('files', nargs='+', type=Path)
    a = ap.parse_args()
    try:
        print(json.dumps(import_files(a.backup, a.device, a.files, a.replace), indent=2))
    except (OSError, ValueError) as e:
        ap.exit(1, str(e)+'\n')


if __name__ == '__main__':
    main()
