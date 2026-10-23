"""Audit, emit, compile and boot each locally supplied revision; report coverage separately."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def external(path):
    value = Path(path).resolve()
    if value == ROOT or ROOT in value.parents:
        raise ValueError('Keep game inputs, generated code, builds and reports outside source')
    return value


def matrix(audit, profile, generated, built, executed):
    """An emitted stub or an unresolved mapping must never become a gameplay pass."""
    names = {m['file']: m['name'] for m in profile['modules']}
    rows = []
    for module in audit['modules']:
        name = names.get(module['file'], Path(module['file']).stem)
        expected = set(module.get('entry_points', []))
        table = generated / ('p_' + name.lower() + '_table.cpp')
        actual = set(re.findall(r'\{0x([0-9A-Fa-f]{8})u,\s*f_', table.read_text())) if table.exists() else set()
        mapped = 'entry_points' in module and not module.get('mapping_conflict')
        emitted = mapped and bool(expected) and expected <= {entry.upper() for entry in actual}
        rows.append(dict(module=name, file=module['file'], base=module.get('base'),
                         mapping_status=module['status'], mapped=mapped,
                         audited_entries=len(expected), missing_entries=sorted(expected-{e.upper() for e in actual}),
                         emitted=emitted, compiled=bool(built and emitted),
                         discovery_problems=len(module.get('problems', [])),
                         indirect_sites=len(module.get('unresolved', [])),
                         executed_in_tested_routes=name in executed,
                         gameplay_certified=False))
    return rows


def verify_reused_profile(source, candidate):
    for key, value in source.items():
        if key != 'modules' and candidate.get(key) != value:
            raise ValueError('Reused audit has stale profile field '+key)
    for module in source['modules']:
        matches = [m for m in candidate['modules'] if m['name']==module['name']]
        if len(matches)!=1:
            raise ValueError('Reused audit is missing or duplicates module '+module['name'])
        match = matches[0]
        if not set(module['seeds'])<=set(match['seeds']) or any(
                match.get(k)!=v for k,v in module.items() if k not in ('seeds', 'evidence')):
            raise ValueError('Reused audit has stale module '+module['name'])


def run_revision(item, config, out):
    folder = out/item['id']
    folder.mkdir()
    result = dict(revision=item['id'], build_gate_passed=False, available=False,
                  complete_game_validated=False, output=str(folder))
    env = os.environ.copy()
    env['PATH'] = os.pathsep.join(config.get('tool_paths', []) + [env.get('PATH', '')])
    for key in list(env):
        if key.startswith('SF3_'):
            env.pop(key)
    env['SDL_AUDIODRIVER'] = 'dummy'

    def command(phase, args, timeout=1200):
        with (folder/(phase+'.log')).open('w', encoding='utf-8') as log:
            log.write(json.dumps(list(map(str, args)))+'\n'); log.flush()
            process = subprocess.run(list(map(str, args)), env=env, stdout=log,
                                     stderr=subprocess.STDOUT, timeout=timeout, cwd=ROOT)
        if process.returncode:
            raise RuntimeError(phase+' failed; see '+str(folder/(phase+'.log')))

    try:
        profile_source = Path(item['profile']).resolve(strict=True)
        profile_data = profile_source.read_bytes()
        profile = folder/'profile.json'
        profile.write_bytes(profile_data)
        result.update(profile_source=str(profile_source), profile_snapshot=str(profile),
                      profile_sha256=hashlib.sha256(profile_data).hexdigest())
        cue = external(item['cue'])
        if not cue.is_file():
            raise FileNotFoundError('Disc CUE unavailable: '+str(cue))
        source = external(item['inventory'])
        if not (source/'manifest.json').is_file() or not (source/'extract').is_dir():
            raise FileNotFoundError('Extracted inventory unavailable: '+str(source))
        source_profile = json.loads(profile.read_text())
        from disc_profile import verify_inventory, content_id
        expected_disc = verify_inventory(source, source_profile)
        sys.path.insert(0, str(ROOT/'.local/saturn-recomp/src'))
        from saturnrecomp.disc import Disc, manifest as disc_manifest
        actual_disc = disc_manifest(Disc(str(cue)))
        if actual_disc != expected_disc:
            raise ValueError('Selected disc contents do not match this revision inventory')
        result['disc_contents_sha256'] = content_id(actual_disc)
        if item.get('reuse'):
            reuse = item['reuse']
            audit_dir, generated, build = (external(reuse[k]) for k in ('audit', 'generated', 'build'))
            # Reused build outputs are rebuilt below, never accepted just because an EXE exists.
            candidate = json.loads((audit_dir/'candidate-profile.json').read_text())
            verify_reused_profile(source_profile, candidate)
            reused_audit = json.loads((audit_dir/'module-audit.json').read_text())
            from module_images import verified_source, image_bytes
            for row in reused_audit['modules']:
                if row.get('source_file'):
                    module = next(m for m in candidate['modules'] if m['file']==row['file'])
                    _, raw = verified_source(source, module, expected_disc)
                    digest = hashlib.sha256(image_bytes(module, raw)).hexdigest()
                else:
                    digest = sha(source/'extract'/row['file'])
                if digest != row['sha256']:
                    raise ValueError('Reused module image changed: '+row['file'])
        else:
            inventory = folder/'inventory'; inventory.mkdir()
            for name in ('manifest.json', 'hashes.json', 'revision.json'):
                if (source/name).exists(): shutil.copy2(source/name, inventory/name)
            shutil.copytree(source/'extract', inventory/'extract')
            audit_dir, generated, build = folder/'audit', folder/'generated', folder/'build'
            command('audit', [sys.executable, '-X', 'utf8', '-B', ROOT/'tools/audit-modules.py',
                              '--work', inventory, '--profile', profile, '--out', audit_dir])
            command('generate', [sys.executable, '-X', 'utf8', '-B', ROOT/'tools/generate.py',
                                 '--framework', 'saturn-recomp', '--work', inventory,
                                 '--profile', audit_dir/'candidate-profile.json', '--out', generated])
            command('configure', [config['cmake'], '-S', generated, '-B', build, '-G', 'Ninja',
                                  *config.get('cmake_args', [])])
        command('emission', [sys.executable, '-X', 'utf8', '-B', ROOT/'tools/check-module-build.py',
                              '--audit', audit_dir/'module-audit.json', '--generated', generated,
                              '--out', folder/'emission.json', '--player'])
        command('build', [config['cmake'], '--build', build, '--target', 'saturn',
                          '--parallel', str(config.get('build_jobs', 4))])
        exe = build/('saturn.exe' if os.name=='nt' else 'saturn')
        if config.get('sdl_dll'):
            target = exe.parent/'SDL3.dll'
            dll = Path(config['sdl_dll'])
            if not target.exists() or sha(target)!=sha(dll): shutil.copy2(dll, target)
        exe_hash = sha(exe)
        boot = folder/'boot';boot.mkdir()
        command('boot', [exe, '--headless', '--cue', cue, '--save', boot/'backup.bin',
                          '--settings', '-', '--clock', '2026-10-22T12:00:00', '--vblanks', '1800',
                          '--coverage', boot/'coverage.tsv', '--shot', '1800',
                          '--out', boot, '--log', boot/'run.log'], timeout=240)
        boot_log = (boot/'run.log').read_text(errors='replace')
        if 'stopped (VBlank limit) after 1800 VBlanks' not in boot_log or not (boot/'shot-1800.png').exists():
            raise ValueError('Boot did not reach the requested field and produce a frame')
        coverage_files = [boot/'coverage.tsv']
        route_evidence = []
        for path in item.get('transition_reports', []):
            path = external(path); evidence = json.loads(path.read_text())
            if evidence['executable_sha256'] != exe_hash or not evidence['regression_passed'] or evidence.get('visual_review_required'):
                raise ValueError('Route evidence does not match this executable or did not pass')
            for route in evidence['results']:
                if route.get('output'):
                    coverage_files.append(external(Path(route['output'])/'coverage.tsv'))
            route_evidence.append(dict(report=str(path), sha256=sha(path)))
        executed = set()
        for path in coverage_files:
            for line in path.read_text().splitlines():
                fields = line.split()
                if len(fields)==4 and fields[3]=='1': executed.add(fields[0])
        audit = json.loads((audit_dir/'module-audit.json').read_text())
        candidate = json.loads((audit_dir/'candidate-profile.json').read_text())
        rows = matrix(audit, candidate, generated, True, executed)
        unresolved = dict(mapping_or_entry=len(audit['blockers']),
                          discovery_problems=sum(r['discovery_problems'] for r in rows),
                          indirect_sites=sum(r['indirect_sites'] for r in rows),
                          cross_module_records=len(audit['cross_module_gaps']))
        result.update(available=True, build_gate_passed=any(r['mapped'] for r in rows) and all(r['compiled'] for r in rows if r['mapped']),
                      executable_sha256=exe_hash, profile_sha256=sha(profile),
                      inventory_sha256=sha(source/'manifest.json'), audit_sha256=sha(audit_dir/'module-audit.json'),
                      candidate_modules=len(rows), mapped_modules=sum(r['mapped'] for r in rows),
                      compiled_modules=sum(r['compiled'] for r in rows),
                      executed_modules=sum(r['executed_in_tested_routes'] for r in rows),
                      unexecuted_compiled_modules=[r['module'] for r in rows if r['compiled'] and not r['executed_in_tested_routes']],
                      all_candidates_compiled=bool(rows) and all(r['compiled'] for r in rows),
                      static_complete=not any(unresolved.values()), unresolved=unresolved,
                      route_evidence=route_evidence, modules=rows)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
        result['error'] = str(error)
    (folder/'report.json').write_text(json.dumps(result, indent=2)+'\n')
    print(item['id']+': '+('mapped-module build/boot PASS; broader coverage incomplete' if result['build_gate_passed'] else 'FAILED or unavailable'), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--manifest', type=Path, required=True, help='External JSON: toolchain settings and revisions with profile, inventory and cue paths')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=1, choices=(1, 2))
    parser.add_argument('--require-complete', action='store_true', help='Fail on any unmapped candidate or unresolved static finding')
    args = parser.parse_args()
    config = json.loads(external(args.manifest).read_text(encoding='utf-8-sig'))
    tool_hash = sha(Path(__file__))
    out = external(args.out);out.mkdir(parents=True, exist_ok=False)
    items = config['revisions']
    registered = {p.name for p in (ROOT/'profiles').glob('*.json')}
    supplied = [Path(item['profile']).name for item in items]
    missing = sorted(registered-set(supplied))
    if (len(supplied)!=len(set(supplied)) or len(items)!=len({i['id'] for i in items})
            or any(not re.fullmatch(r'[a-zA-Z0-9_-]+', i['id']) for i in items)):
        parser.error('Each registered revision needs one safe, unique identifier')
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda item: run_revision(item, config, out), items))
    passed = bool(results) and not missing and all(r['build_gate_passed'] for r in results)
    complete = passed and all(r['all_candidates_compiled'] and r['static_complete'] for r in results)
    report = dict(mapped_module_builds_passed=passed, complete_static_validation=complete,
                  validation_tool_sha256=tool_hash, manifest_sha256=sha(args.manifest),
                  missing_registered_profiles=missing, complete_game_validated=False,
                  unsupported='Premium Disc and unregistered disc/translation revisions have no validation claim.',
                  caveat='Successful compilation and boot do not validate unvisited module behavior or indirect targets.', revisions=results)
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    lines = ['# Local module validation', '', '| Revision | Compiled candidates | Executed in tested routes | Unmapped / entry review | Discovery findings | Indirect sites |', '|---|---:|---:|---:|---:|---:|']
    for r in results:
        if r['build_gate_passed']:
            u=r['unresolved'];lines.append(f"| {r['revision']} | {r['compiled_modules']}/{r['candidate_modules']} | {r['executed_modules']} | {u['mapping_or_entry']} | {u['discovery_problems']} | {u['indirect_sites']} |")
        else:lines.append(f"| {r['revision']} | unavailable/failed | — | — | — | — |")
    lines.extend(['', 'Mapped-module build gates: '+str(passed), 'Complete static validation: '+str(complete), '', report['caveat'], report['unsupported']])
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    return 0 if passed and (complete or not args.require_complete) else 1


if __name__ == '__main__':
    raise SystemExit(main())
