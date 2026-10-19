"""Invented input/data tests for checkpoint integrity and compatibility; no game assets."""
import argparse
import json
from pathlib import Path
import subprocess

p=argparse.ArgumentParser(__doc__)
p.add_argument('--helper', required=True)
p.add_argument('--out', type=Path, required=True)
a=p.parse_args()
seed=a.out/'seed'; seed.mkdir(parents=True, exist_ok=True)
(seed/'context.json').write_text(json.dumps({'clock':'2026-10-17T12:00:00'}))
(seed/'build-id.txt').write_text('invented-build')
(seed/'disc-id.txt').write_text('invented-disc')
(seed/'backup.bin').write_bytes(bytes(range(64)))
(seed/'settings.ini').write_text('[touch]\ncontrols=off\n')
(seed/'backup.bin.cartridge').write_bytes(b'invented cartridge')
record=a.out/'input.txt'; record.write_text('10:START,20:,200:A,300:C,')
def run(*args, good=True):
    r=subprocess.run([a.helper, *map(str,args)], capture_output=True, text=True)
    assert (r.returncode == 0)==good, (r.returncode,r.stdout,r.stderr)
    return r.stdout.strip()
checkpoint=Path(run('save',a.out/'points',seed,record,200))
assert (checkpoint/'input.txt').read_text()=='10:START,20:,'
assert run('verify',checkpoint,seed)=='200'
again=Path(run('save',a.out/'points',seed,record,210))
assert again!=checkpoint and (a.out/'points/latest.txt').read_text()==again.name
assert run('verify',checkpoint,seed)=='200'  # Prior point retained.
(seed/'build-id.txt').write_text('changed-build'); run('verify',checkpoint,seed,good=False)
(seed/'build-id.txt').write_text('invented-build')
(seed/'disc-id.txt').write_text('changed-disc'); run('verify',checkpoint,seed,good=False)
(seed/'disc-id.txt').write_text('invented-disc')
for file in ['input.txt','point.txt','seed/backup.bin','seed/context.json','seed/settings.ini','seed/backup.bin.cartridge']:
    path=checkpoint/file; original=path.read_bytes(); path.write_bytes(original+b'damaged')
    run('verify',checkpoint,seed,good=False); path.write_bytes(original)
run('verify',checkpoint,seed)
print('PASS: exclusive frame cutoff, repeated saves, retained points, build/disc mismatch, 6 corruption cases including cartridge')
