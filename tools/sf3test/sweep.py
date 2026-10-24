"""Scene/battle reachability sweep: boot a save (or an edited save) per target, drive it headless,
and classify the run. Pure functions here are unit-tested with invented data; the runner needs a
built `saturn`, a disc and saves, all outside the repository."""
import json
import os
from pathlib import Path
import random
import re
import subprocess
import time

from . import frames, memory_map, saves

FATAL = re.compile(r'FATAL[: ]+(.*)')
CALL = re.compile(r'call to ([0-9A-F]{8}), not an entry of an active module \(from pr ([0-9A-F]{8})\)')
NOT_DONE = re.compile(r'\] (.*is not done.*)$')
STALL = re.compile(r'STALL: no VBlank for 5 s after VBlank (\d+)')
STOPPED = re.compile(r'stopped \(([^)]*)\) after (\d+) VBlanks')
LOAD_END = 5200          # by here the Continue menu, record select and load are done in all scenarios


def menu_inputs(menu_end=LOAD_END):
    """Title -> START, then C every 158 VBlanks: Gabriel's line, Continue, record 01, dialogue."""
    steps = [(1100, 'START'), (1308, 'START')]
    v = 1474
    while v < menu_end:
        steps.append((v, 'C'))
        v += 158
    return steps


def explore_inputs(start, end, seed):
    """Deterministic button mashing: mostly C (talk/confirm), walks, some B (back out of menus)."""
    rnd = random.Random(seed)
    steps, v = [], start
    moves = ['UP', 'DOWN', 'LEFT', 'RIGHT']
    while v < end:
        r = rnd.random()
        if r < 0.45:
            steps.append((v, 'C')); hold = 6
        elif r < 0.85:
            steps.append((v, rnd.choice(moves))); hold = rnd.choice([10, 20, 40])
        elif r < 0.95:
            steps.append((v, 'B')); hold = 6
        else:
            steps.append((v, 'A')); hold = 6
        steps.append((v + hold, ''))
        v += hold + rnd.choice([12, 20, 30])
    return steps


def input_script(steps, hold=8):
    """--input text. A step with buttons and no release gets one after `hold` VBlanks."""
    out, explicit = [], {v for v, b in steps if b == ''}
    for v, b in steps:
        out.append(f'{v}:{b}')
        if b and not any(e > v and e <= v + 60 for e in explicit) and (v + hold) not in explicit:
            out.append(f'{v + hold}:')
    seen, uniq = set(), []
    for item in sorted(out, key=lambda s: (int(s.split(':')[0]), s.split(':')[1] == '')):
        if item not in seen:
            seen.add(item); uniq.append(item)
    return ','.join(uniq)


def parse_progress(text):
    """--progress lines -> [(vblank, map_id, battle_id)] (the first range is the map id byte)."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            out.append((int(parts[0]), int(parts[1], 16), int(parts[2], 16)))
    return out


def analyze(log, progress, shots, vblanks, expect=None, loaded_after=LOAD_END):
    """Classify one run. `shots` is [(vblank, stats)] in order."""
    fatals = [m.group(1).strip() for m in FATAL.finditer(log)]
    calls = sorted({(m.group(1), m.group(2)) for m in CALL.finditer(log)})
    stalls = [int(m.group(1)) for m in STALL.finditer(log)]
    stopped = STOPPED.search(log)
    not_done = sorted({m.group(1) for m in map(NOT_DONE.search, log.splitlines()) if m})
    ran = int(stopped.group(2)) if stopped else None
    # the state block holds other data until a save is loaded into it: count from the load on
    loaded_at = next((v for v, m, b in progress if expect is None or (m, b) == tuple(expect)), None)
    after = [(v, m, b) for v, m, b in progress if loaded_at is not None and v >= loaded_at]
    maps = sorted({m for v, m, b in after})
    battles = sorted({b for v, m, b in after if b})
    late = [s for v, s in shots if v > loaded_after]
    black = [v for v, s in shots if v > loaded_after and s.get('black')]
    frozen = len(late) >= 3 and len({s['sha1'] for s in late[-3:]}) == 1
    if fatals:
        status = 'crash'
    elif ran is None or (ran < vblanks and not stopped):
        status = 'hang' if stalls else 'died'
    elif stalls:
        status = 'stall'
    elif late and len(black) == len(late):
        status = 'black'
    elif frozen:
        status = 'frozen'
    elif not maps:
        status = 'no-load'
    else:
        status = 'ok'
    return dict(status=status, vblanks_run=ran, loaded_at=loaded_at, fatal=fatals[:5], unresolved_calls=[list(c) for c in calls],
                stalls=stalls, maps=maps, battles=battles, black_shots=black, frozen=frozen,
                unimplemented=not_done)


def external(path, root):
    p = Path(path).resolve()
    if p == root or root in p.parents:
        raise ValueError('sweep outputs and inputs must stay outside the source repository')
    return p


def run_target(saturn, cue, backup, work, vblanks, mm, seed, expect=None, shots_every=600, timeout=None, extra=()):
    """Run one target headless; returns the analysis plus its paths."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    bak = work / 'backup.bin'
    bak.write_bytes(backup)
    cart = work / 'backup.bin.cartridge'
    if cart.exists():
        cart.unlink()
    steps = menu_inputs() + explore_inputs(LOAD_END + 60, vblanks - 30, seed)
    (work / 'input.txt').write_text(input_script(steps) + '\n')
    shots = list(range(shots_every, vblanks + 1, shots_every))
    for p in work.glob('shot-*.png'):
        p.unlink()
    prog = work / 'progress.tsv'
    if prog.exists():
        prog.unlink()
    cmd = [str(saturn), '--headless', '--cue', str(cue), '--save', str(bak), '--settings', '-',
           '--vblanks', str(vblanks), '--input', '@' + str(work / 'input.txt'),
           '--shot', ','.join(map(str, shots)), '--out', str(work), '--log', str(work / 'run.log'),
           '--coverage', str(work / 'coverage.tsv'), '--checkpoint', '30',
           '--progress', str(prog), '--progress-keep', f"{mm['map_id']:08X}:1,{mm['battle_id']:08X}:1", *extra]
    env = dict(os.environ, SDL_VIDEO_DRIVER='dummy', SDL_AUDIO_DRIVER='dummy')
    t0 = time.time()
    with open(work / 'stdout.txt', 'w') as out:
        try:
            rc = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, env=env,
                                timeout=timeout or max(300, vblanks // 20)).returncode
        except subprocess.TimeoutExpired:
            rc = 'timeout'
    log = ''
    for name in ('run.log', 'stdout.txt'):
        p = work / name
        if p.exists():
            log += p.read_text(errors='replace')
    progress = parse_progress(prog.read_text()) if prog.exists() else []
    shot_stats = []
    for v in shots:
        p = work / f'shot-{v}.png'
        if p.exists():
            shot_stats.append((v, frames.stats(p.read_bytes())))
    result = analyze(log, progress, shot_stats, vblanks, expect)
    if rc == 'timeout' and result['status'] == 'ok':
        result['status'] = 'hang'
    result.update(rc=rc, seconds=round(time.time() - t0, 1), work=str(work),
                  last_shot=str(work / f'shot-{shot_stats[-1][0]}.png') if shot_stats else None,
                  progress=progress[:200])
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def targets_from_saves(paths, scenario):
    """One target per SFORCE3<scenario>_NN record in the given backup images/BUP files."""
    out = []
    for path in paths:
        for rec in saves.load_any(Path(path).read_bytes()):
            if not rec['name'].startswith(f'SFORCE3{scenario}_') or saves.check_sf3(rec) is False:
                continue
            stem = re.sub(r'(?i)^(external|internal)backupram', '', Path(path).stem)
            tag = re.sub(r'[^A-Za-z0-9]+', '-', stem).strip('-')[:32].strip('-')
            out.append(dict(id=f'save:{tag}:{rec["name"][-2:]}', record=rec, kind='save',
                            map=rec['data'][memory_map.MAP_ID], battle=rec['data'][memory_map.BATTLE_ID]))
    return out


def targets_from_maps(base_record, map_ids):
    out = []
    for m in map_ids:
        rec = dict(base_record, data=memory_map.with_map(base_record['data'], m, 0))
        out.append(dict(id=f'map:{m:02X}', record=rec, kind='map', map=m, battle=0))
    return out


def backup_for(target, scenario):
    rec = dict(target['record'], name=f'SFORCE3{scenario}_01')
    return saves.native_backup([rec])


def coverage_union(texts):
    """{module: [functions, ran in any run, instructions, instructions in ran functions]} from
    --coverage files' text (lines "MODULE ADDR INSTRUCTIONS RAN")."""
    seen = {}
    for text in texts:
        for line in text.splitlines():
            parts = line.split()
            if len(parts) != 4:
                continue
            key = (parts[0], parts[1])
            seen[key] = (int(parts[2]), seen.get(key, (0, False))[1] or parts[3] == '1')
    out = {}
    for (mod, _), (size, ran) in seen.items():
        row = out.setdefault(mod, [0, 0, 0, 0])
        row[0] += 1
        row[1] += ran
        row[2] += size
        row[3] += size if ran else 0
    return out


STATUSES = ['ok', 'frozen', 'black', 'no-load', 'stall', 'hang', 'died', 'crash']


def matrix(report):
    """Markdown coverage matrix from a sweep report (one profile)."""
    rows = report['results']
    counts = {s: sum(1 for r in rows if r['status'] == s) for s in STATUSES}
    maps = sorted({m for r in rows for m in r['maps']})
    battles = sorted({b for r in rows for b in r['battles']})
    lines = [f"## {report['profile']} ({len(rows)} targets, {report.get('vblanks')} VBlanks each)", '',
             '| status | ' + ' | '.join(STATUSES) + ' |', '|---' * (len(STATUSES) + 1) + '|',
             '| targets | ' + ' | '.join(str(counts[s]) for s in STATUSES) + ' |', '',
             f'Maps reached ({len(maps)}): ' + ' '.join(f'{m:02X}' for m in maps), '',
             f'Battles reached ({len(battles)}): ' + ' '.join(str(b) for b in battles), '',
             ]
    cov = report.get('coverage')
    if cov:
        f = sum(r[0] for r in cov.values()); ran = sum(r[1] for r in cov.values())
        mods = sorted(m for m, r in cov.items() if r[1])
        lines += [f'Functions executed (union): {ran}/{f} ({100 * ran / max(f, 1):.1f}%); modules with any '
                  f'function run: {len(mods)}/{len(cov)}', '']
    lines += ['| target | map | battle | status | maps seen | detail |', '|---|---|---|---|---|---|']
    for r in rows:
        detail = '; '.join(r['fatal'][:1] + [f'stall@{s}' for s in r['stalls'][:1]]
                           + (['frozen'] if r['frozen'] else []))
        lines.append(f"| {r['id']} | {r['map']:02X} | {r['battle']} | {r['status']} | "
                     f"{' '.join(f'{m:02X}' for m in r['maps'][:8])} | {detail} |")
    return '\n'.join(lines) + '\n'
