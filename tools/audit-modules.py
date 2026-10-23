"""Audit local SFIII modules before gameplay; emit an external candidate profile.

Mappings from observed RAM and SF3Tools are kept distinct. Discovery is a static
coverage audit, not a claim of correct gameplay or of every byte being executable.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

from module_entries import arithmetic_shift_entries, unrolled_copy_entries, registered_store_callback_entries
from disc_profile import verify_inventory
from module_images import expand_modules, verified_source, image_bytes

REPO = Path(__file__).resolve().parents[1]
VENEER = bytes.fromhex('d001402b00090009')
MODEL_REVISION = '35d64099970b9d6e96d1e07c5ec2c522c4b37969'
# SF3Lib/Models/Files/<name>/<name>_File.cs, Scenario1 RamAddress.
# These are documented mappings until separately corroborated by this revision.
MODEL_BASES = {
    'X011': 0x06068000, 'X012': 0x06070000, 'X013': 0x06080000,
    'X014': 0x06088000, 'X016': 0x06088000, 'X017': 0x06088000,
    'X018': 0x06088000, 'X019': 0x060A0000, 'X021': 0x06068000,
    'X023': 0x06078000, 'X024': 0x0607B000, 'X026': 0x06078000,
    'X027': 0x06078000, 'X031': 0x06053000, 'X032': 0x06088000,
    'X033': 0x06078000, 'X035': 0x06088000, 'X044': 0x06078000,
}


def veneers(data, base):
    """Validated in-image veneer entry addresses, never arbitrary pointer values."""
    return {base + at for at in range(0, len(data) - 11, 4)
            if data[at:at+8] == VENEER
            and base <= int.from_bytes(data[at+8:at+12], 'big') < base + len(data)
            and not int.from_bytes(data[at+8:at+12], 'big') & 1}


def external(path):
    path = Path(path).resolve()
    if path == REPO or REPO in path.parents:
        raise ValueError('Game-derived audit/output must stay outside source repository')
    return path


def verified(path, manifest):
    data = path.read_bytes()
    expected = manifest['files']['/' + path.name]
    if len(data) != expected['size'] or hashlib.sha1(data).hexdigest() != expected['sha1']:
        raise ValueError('Extracted file changed: ' + path.name)
    return data


def main():
    ap = argparse.ArgumentParser(__doc__)
    ap.add_argument('--work', type=Path, required=True)
    ap.add_argument('--profile', type=Path, default=REPO/'profiles/usa-v1.001.json')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--session', type=Path, help='Optional crash RAM to corroborate whole images')
    a = ap.parse_args()
    work, out = external(a.work), external(a.out)
    profile = json.loads(a.profile.read_text(encoding='utf-8-sig'))
    manifest = verify_inventory(work, profile)
    profile['modules'] = expand_modules(profile, manifest)
    model_bases = {k:int(v,16) for k,v in profile.get('model_bases',{}).items()} if profile.get('scenario',1) != 1 else MODEL_BASES
    known = {m['file']: m for m in profile['modules']}
    ram = (a.session/'crash-wram-high.bin').read_bytes() if a.session else None
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(REPO/'.local/saturn-recomp/src'))
    from saturnrecomp import sh2
    from saturnrecomp.recomp.discover import Program
    rows, additions, programs, images, entry_seeds = [], [], {}, {}, {}
    containers = {c['file'] for c in profile.get('module_containers', [])}
    inputs = [(file, None) for file in sorted((work/'extract').glob('*.BIN')) if file.name not in containers]
    inputs.extend((Path(m['file']), m) for m in profile['modules'] if 'source_file' in m)
    for file, sliced in inputs:
        if sliced:
            _, original = verified_source(work, sliced, manifest)
            data = image_bytes(sliced, original)
        else:
            if '/' + file.name not in manifest['files']:
                continue  # IP.BIN is boot metadata, not a filesystem module.
            data = verified(file, manifest)
            if file.name in known:
                # Fail on invalid configured entries instead of silently dropping
                # a loader entry while still reporting this module as compiled.
                image_bytes(known[file.name], data)
        raw_veneers = [at for at in range(0, len(data)-11, 4) if data[at:at+8] == VENEER]
        if not raw_veneers and file.name not in known and file.stem not in model_bases:
            continue
        m = known.get(file.name)
        row = dict(file=file.name, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                   configured=m is not None, veneer_signatures=len(raw_veneers))
        if sliced:
            row.update(source_file=sliced['source_file'], source_offset=sliced['offset'],
                       source_sha256=hashlib.sha256(original).hexdigest())
        base = int(m['base'], 16) if m else None
        source = 'existing-profile' if m else None
        if base is None and re.fullmatch(r'X1[A-Z0-9_]+', file.stem):
            base = 0x06060000 if file.stem == 'X1BTL99' else int(profile.get('scene_base','0605F000'),16)
            source = 'SF3Tools scenario-specific X1 model; static mapping, see profile scenario'
        if base is None and file.stem in model_bases:
            base, source = model_bases[file.stem], 'SF3Tools scenario-specific file model'
        if base is None and file.stem.startswith('X3') and raw_veneers and profile.get('effect_base','0604A800'):
            # X014's effect loader uses this destination; X3HEAL is also an
            # exact whole-image match in the 20261018-081749 crash. Require
            # every export to resolve inside its image before applying it to
            # another family member (X3ELEM5 fails and stays under review).
            effect_base = int(profile.get('effect_base','0604A800'),16)
            if all(effect_base <= int.from_bytes(data[at+8:at+12], 'big') < effect_base+len(data)
                   and not int.from_bytes(data[at+8:at+12], 'big') & 1
                   for at in raw_veneers):
                base, source = effect_base, 'X014 effect-loader destination; all X3 exports inside image; family inference, gameplay unvalidated'
        match = ram.find(data) if ram is not None else -1
        if match >= 0 and ram.find(data, match+1) < 0:
            observed = 0x06000000 + match
            row['whole_image_ram_match'] = dict(base=f'{observed:08X}', session=a.session.name)
            if base is not None and observed != base:
                row['mapping_conflict'] = f'{base:08X} vs observed {observed:08X}'
            elif base is None:
                base, source = observed, 'whole-image crash RAM match'
        row['mapping_source'] = source
        if base is None or row.get('mapping_conflict'):
            row['status'] = 'needs-load-address-review'
            rows.append(row)
            continue
        image = data[:int(m['bytes'],16)] if m and 'bytes' in m else data
        entries = veneers(image, base)
        entries.update(unrolled_copy_entries(image, base))
        entries.update(arithmetic_shift_entries(image, base))
        entries.update(registered_store_callback_entries(image, base))
        if m:
            entries.update(int(s,16) for s in m['seeds'] if base <= int(s,16) < base+len(image))
        row.update(base=f'{base:08X}', image_bytes=len(image),
                   validated_veneer_entries=len(veneers(image,base)), seed_entries=len(entries))
        if not m and not veneers(image,base):
            row['status'] = 'needs-executable-entry-review'
            rows.append(row)
            continue
        prog = Program(sh2.Image(image,base), [base]+sorted(entries))
        programs[file.name], images[file.name], entry_seeds[file.name] = prog, image, entries
        row['discovery'] = prog.summary()
        row['problems'] = [dict(entry=f'{f.entry:08X}', reason=f.bad[0], at=f'{f.bad[1]:08X}')
                           for f in prog.funcs.values() if f.bad]
        row['unresolved'] = [dict(function=f'{f.entry:08X}', at=f'{at:08X}', kind=kind)
                             for f in prog.funcs.values() for at,kind in f.unresolved]
        row['external_calls'] = [f'{target:08X}' for target in sorted({target
                                for f in prog.funcs.values() for target in f.calls
                                if not base <= target < base+len(image)})]
        row['entry_points'] = [f'{e:08X}' for e in sorted(prog.funcs)]
        row['status'] = 'configured' if m else 'candidate-for-build-not-gameplay-validated'
        if not m:
            additions.append(dict(name=file.stem,file=file.name,base=f'{base:08X}',
                                  seeds=[f'{s:08X}' for s in sorted(entries)],overlay=True,
                                  evidence=source+'; exact in-image SH-2 export veneers; see external module-audit.json'))
        rows.append(row)
        print(file.name, row['discovery']['functions'], 'functions;',
              row['discovery']['unresolved indirect'], 'unresolved indirect;', source, flush=True)
    # Close statically resolved calls across uniquely owned image ranges. Never
    # fan a target out to every overlay sharing an address. Each new entry must
    # descend cleanly without entering classified data, then gets rediscovered.
    promoted = []
    for iteration in range(8):
        requests = {}
        for caller, prog in list(programs.items()):
            for f in prog.funcs.values():
                if f.bad:
                    continue
                for target in f.calls:
                    if prog.inside(target):
                        continue
                    owners = [(name, p) for name,p in programs.items() if p.inside(target)]
                    if len(owners) != 1:
                        continue
                    owner, destination = owners[0]
                    if target not in destination.funcs and target not in destination.data:
                        requests.setdefault(owner, {}).setdefault(target, set()).add(caller)
        changed = False
        for owner, targets in sorted(requests.items()):
            old = programs[owner]
            trial_seeds = entry_seeds[owner] | set(targets)
            trial = Program(sh2.Image(images[owner],old.img.base), [old.img.base]+sorted(trial_seeds))
            accepted = {target for target in targets if target in trial.funcs
                        and not trial.funcs[target].bad
                        and not trial.funcs[target].code & trial.data}
            if accepted:
                entry_seeds[owner].update(accepted)
                programs[owner] = Program(sh2.Image(images[owner],old.img.base),
                                         [old.img.base]+sorted(entry_seeds[owner]))
                promoted.extend(dict(file=owner,entry=f'{target:08X}',callers=sorted(targets[target]))
                                for target in sorted(accepted))
                changed = True
        if not changed:
            break
    candidate = copy.deepcopy(profile)
    candidate['modules'].extend(additions)
    for module in candidate['modules']:
        if module['file'] in entry_seeds:
            module['seeds'] = [f'{s:08X}' for s in sorted(entry_seeds[module['file']])]
    cross_gaps = []
    for row in rows:
        if row['file'] not in programs:
            continue
        prog = programs[row['file']]
        row['discovery'] = prog.summary()
        row['entry_points'] = [f'{e:08X}' for e in sorted(prog.funcs)]
        row['problems'] = [dict(entry=f'{f.entry:08X}',reason=f.bad[0],at=f'{f.bad[1]:08X}')
                           for f in prog.funcs.values() if f.bad]
        row['unresolved'] = [dict(function=f'{f.entry:08X}',at=f'{at:08X}',kind=kind)
                             for f in prog.funcs.values() for at,kind in f.unresolved]
        calls = {t for f in prog.funcs.values() if not f.bad for t in f.calls if not prog.inside(t)}
        row['external_calls'] = [f'{t:08X}' for t in sorted(calls)]
        for target in sorted(calls):
            owners = [name for name,p in programs.items() if p.inside(target)]
            missing = [name for name in owners if target not in programs[name].funcs]
            if not owners or missing:
                cross_gaps.append(dict(caller=row['file'],target=f'{target:08X}',
                                       owners=owners,missing_entries=missing,
                                       status='unmapped-or-hardware' if not owners else
                                       'ambiguous-overlay' if len(owners)>1 else 'rejected-entry'))
    candidate['audit_note'] = 'Experimental bulk profile. Static discovery and documented bases are not gameplay validation.'
    report = dict(profile=str(a.profile), modules=rows, configured=len(known),
                  containers=profile.get('module_containers', []),
                  sf3tools_mapping_revision=MODEL_REVISION,
                  candidate_additions=len(additions), bulk_modules=len(candidate['modules']),
                  cross_module_promoted_entries=promoted, cross_module_gaps=cross_gaps,
                  cross_module_closure_converged=not changed,
                  blockers=[r['file'] for r in rows if r['status'].startswith('needs-')],
                  caveat='Unclassified bytes may be data; generated functions do not establish complete coverage or correctness.')
    (out/'module-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'candidate-profile.json').write_text(json.dumps(candidate,indent=2)+'\n')
    (out/'summary.txt').write_text(f'{len(known)} configured; {len(additions)} candidate additions; '
                                  f'{len(report["blockers"])} need mapping/entry review\n'
                                  f'{len(promoted)} cross-module entry promotions; '
                                  f'{len(cross_gaps)} cross-module review records\n'
                                  + '\n'.join(report['blockers'])+'\n')
    print((out/'summary.txt').read_text())


if __name__ == '__main__':
    main()
