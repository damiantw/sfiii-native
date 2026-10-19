"""Local-only SFIII inventory and conservative boot-code generation (Python 3.11+)."""
import argparse
import csv
import hashlib
import json
import pathlib
import sys

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--cue', required=True, type=pathlib.Path)
    p.add_argument('--framework', required=True, type=pathlib.Path)
    p.add_argument('--out', required=True, type=pathlib.Path)
    p.add_argument('--generate', action='store_true')
    a = p.parse_args()
    sys.path.insert(0, str(a.framework.resolve() / 'src'))
    from saturnrecomp.disc import Disc, manifest
    from saturnrecomp.recomp.__main__ import generate
    out = a.out.resolve()
    repo = pathlib.Path(__file__).resolve().parents[1]
    if out == repo or repo in out.parents:
        raise SystemExit('Choose --out outside the source repository; extracted data and generated code must stay local.')
    out.mkdir(parents=True, exist_ok=True)
    disc = Disc(str(a.cue.resolve()))
    if (disc.ip.product, disc.ip.version, disc.ip.areas) != ('MK-81383', 'V1.001', 'U'):
        raise SystemExit('This probe supports only the USA MK-81383 V1.001 header; hashes still require review.')
    (out / 'disc-info.txt').write_text(disc.ip.describe(), encoding='utf-8')
    (out / 'manifest.json').write_text(json.dumps(manifest(disc), indent=2), encoding='utf-8')
    tracks = [a.cue] + [a.cue.parent / line.split('"')[1] for line in a.cue.read_text().splitlines() if line.strip().startswith('FILE "')]
    (out / 'hashes.json').write_text(json.dumps({f.name: {'size': f.stat().st_size, 'sha256': digest(f)} for f in tracks}, indent=2), encoding='utf-8')
    rows = []
    files = out / 'extract'
    files.mkdir(exist_ok=True)
    for r in disc.iso.walk():
        if r.is_dir:
            continue
        row = {'path': r.path, 'lba': r.lba, 'size': r.size, 'sha256': '', 'classification': 'unclassified asset', 'base': '', 'evidence': ''}
        if disc.is_cdda(r):
            row['classification'] = 'CD-DA record'
        else:
            data = disc.read_file(r)
            path = files / r.path.lstrip('/')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            row['sha256'] = hashlib.sha256(data).hexdigest()
            if path.name == '1ST.BIN':
                row.update(classification='boot SH-2', base='06004000', evidence='IP first-read address; startup disassembly')
            elif path.name.startswith('X1') and path.suffix == '.BIN':
                base = 0x06060000 if path.name == 'X1BTL99.BIN' else 0x0605F000
                entry = int.from_bytes(data[8:12], 'big')
                valid = data[:6] == bytes.fromhex('d001402b0009') and base <= entry < base + len(data)
                row.update(classification='scene SH-2 candidate', base=f'{base:08X}', evidence=f'SF3Tools base; entry trampoline/in-file target={valid}; dynamic load unverified')
            elif path.name.startswith('X0') and path.suffix == '.BIN':
                row.update(classification='resident/overlay candidate', evidence='requires loader trace; numeric filename alone is insufficient')
        rows.append(row)
    with (out / 'inventory.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    if a.generate:
        # Only boot is proven at this stage. Do not invent overlay bases from statistical guesses.
        generate([('BOOT', str(files / '1ST.BIN'), 0x06004000, [0x06004000])], str(out / 'recomp'))
    print(f'{len(rows)} records; {sum(r["classification"] == "scene SH-2 candidate" for r in rows)} scene candidates; reports: {out}')

if __name__ == '__main__':
    main()
