"""Generate local game code from an evidence-based module profile."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from module_entries import unrolled_copy_entries, arithmetic_shift_entries

p = argparse.ArgumentParser(__doc__)
p.add_argument('--framework', choices=['saturnkit', 'saturn-recomp'], required=True)
p.add_argument('--work', type=Path, required=True)
p.add_argument('--profile', type=Path, default=Path('profiles/usa-v1.001.json'))
p.add_argument('--optest', action='store_true')
p.add_argument('--out', type=Path, help='External generated-code directory; defaults to WORK/recomp[-saturnkit]')
a = p.parse_args()
repo = Path(__file__).resolve().parents[1]
work = a.work.resolve()
out = (a.out or work / ('recomp-saturnkit' if a.framework == 'saturnkit' else 'recomp')).resolve()
if work == repo or repo in work.parents or out == repo or repo in out.parents:
    raise SystemExit('Game-derived output must be outside the repository')
profile = json.loads(a.profile.read_text())
manifest = json.loads((work / 'manifest.json').read_text())
hashes = json.loads((work / 'hashes.json').read_text())
if not any(h['sha256'] == profile['track1_sha256'] for h in hashes.values()):
    raise SystemExit('Local inventory does not match profile')
specs = []
for m in profile['modules']:
    source = work / 'extract' / m['file']
    original = source.read_bytes()
    expected = manifest['files']['/' + m['file']]
    if len(original) != expected['size'] or hashlib.sha1(original).hexdigest() != expected['sha1']:
        raise SystemExit(f'Extracted module changed: {m["file"]}')
    if 'bytes' in m:
        prepared = work / 'modules' / m['file']
        prepared.parent.mkdir(exist_ok=True)
        prepared.write_bytes(source.read_bytes()[:int(m['bytes'], 16)])
        source = prepared
    base = int(m['base'], 16)
    seeds = {int(s, 16) for s in m['seeds']}
    data = source.read_bytes()
    seeds.update(unrolled_copy_entries(data, base))
    seeds.update(arithmetic_shift_entries(data, base))
    # Common SFIII export veneer: mov.l @(PC),r0; jmp @r0; nop; nop; target.
    # Only aligned veneers whose literal points within this verified image qualify.
    for at in range(0, len(data) - 11, 4):
        if data[at:at+8] == bytes.fromhex('d001402b00090009'):
            target = int.from_bytes(data[at+8:at+12], 'big')
            if base <= target < base + len(data) and target % 2 == 0:
                seeds.add(base + at)
    specs.append((m['name'], str(source), base, sorted(seeds)))
overlays = {m['name'] for m in profile['modules'] if m.get('overlay')}
if a.framework == 'saturnkit':
    sys.path.insert(0, str(repo / '.local'))
    from saturnkit.recomp.__main__ import generate
    generate(specs, str(out), overlays=overlays, optest=a.optest)
else:
    sys.path.insert(0, str(repo / '.local' / 'saturn-recomp' / 'src'))
    from saturnrecomp.recomp.__main__ import generate
    generate(specs, str(out), callable_entries=overlays,
             runtime_literals={m['name'] for m in profile['modules']}, optest=a.optest)
