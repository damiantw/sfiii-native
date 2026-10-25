"""SF3 story driver (round 26): play a scenario's story forward from a save record by chaining
goal-directed autoplay (sf3test/autoplay.py: battles aimed, towns walked) and record every press
(and every test-only assist poke) as a replayable segment.

  drive   load RECORD of SAVE, play up to FRAMES; the goals are the later records of the scenario
          (in play-time order); a goal is reached when all its story-flag bits are set live
          (sf3test/story.py). Writes OUT/segment.txt (inputs only), OUT/result.json, key frames.
          --continue SEG first replays SEG's actions (same record), then drives on with --seed.
  replay  replay SEG frame for frame and check the end hashes it records (deterministic rerun).
  order   list a scenario's records in story order with their story-flag bit counts.
  suite   replay every tools/story-replays/<key>/*.seg (keys sc1 sc2v2 sc2v1 sc3) with the build,
          cue and saves directory in SF3_BUILD_<KEY>, SF3_CUE_<KEY>, SF3_SAVES_<KEY>; -j N jobs.

  python tools/sf3-story.py drive --saturn BUILD/saturn --cue DISC.cue --profile P \
      --saves DIR/*.bin --record 3-Battle-22-to-End:25 --frames 30000 --assist party+enemy1 --out OUT
  python tools/sf3-story.py replay --saturn BUILD/saturn --cue DISC.cue --saves DIR/*.bin SEG

Bring-your-own build, disc and saves; outputs stay outside the repository. --assist pokes the
force's battle stats (TEST ONLY, labelled in the segment header and result); segments with pokes
are never committed (tools/story-replays holds pad-only segments, checked by story.check_committed).

Determinism: the SMPC clock is the host's unless `saturn --clock` sets it, and the game keeps the
date and time in work RAM (Sc2 V2.000 0x06004F4C, BCD), so two replays a few seconds apart ended
with different RAM hashes. Every run here passes --clock (default CLOCK, kept in the segment
header); replays use the header's clock."""
import argparse
import hashlib
import json
import re
import os
from pathlib import Path
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
for p in (ROOT / '.local' / 'saturn-recomp' / 'src', Path(os.environ.get('SF3_RECOMP_SRC', ROOT / '.local'))):
    if p.exists():
        sys.path.insert(0, str(p))
from sf3test import autoplay, diff, memory_map, story, sweep  # noqa: E402

CHECK = 30           # frames between flag reads
SHOT_EVERY = 3000    # frames between progress shots
MAP_HOLD = 20        # flag checks a map goal's map must hold
CLOCK = '2026-01-01T00:00:00'   # SMPC clock at power-on for every recorded or replayed run
# Segments are recorded with the agent's default pause at VBlank-IN; SF3_AGENT_LINE (used by Beetle
# diffs) moves the step edge and would shift every press, so story runs never inherit it.
os.environ.pop('SF3_AGENT_LINE', None)


class Done(Exception):
    pass


class Recorder(diff.OurSide):
    """OurSide that logs pad changes and writes as segment actions and watches story progress."""

    def __init__(self, run, profile, goals, out, stop_after=None, max_frames=None):
        super().__init__(run)
        self.actions, self.profile, self.goals, self.out = [], profile, goals, Path(out)
        self.mm = memory_map.lookup(profile)
        self.fa = story.flag_addr(profile)
        self.g, self.events, self.best_bits, self.stop_after = 0, [], -1, stop_after
        self.loaded, self.last_mb, self.max_frames = None, None, max_frames
        self.held = None
        self.map_hold = 0

    def pad(self, buttons):
        spec = '+'.join(sorted(buttons))
        if spec != self.held:
            self.actions.append((self.r.vblank, 'pad', spec))
            self.held = spec
        self.r.pad(spec)

    def write(self, addr, data):
        if self.r.read(addr, len(data)) == bytes(data):
            return                       # a no-op poke (assist re-pokes every turn): not logged
        self.actions.append((self.r.vblank, 'poke', f'{addr:08X}', bytes(data).hex()))
        self.r.write(addr, data)

    def shot(self, name):
        try:
            self.frame().save_png(str(self.out / f'{name}.png'))
        except Exception:
            pass

    def step(self):
        super().step()
        v = self.r.vblank
        if self.loaded is None or v % CHECK:
            return
        live = self.read(self.fa, story.FLAG_HI - story.FLAG_LO)
        m = self.read(self.mm['map_id'], 1)[0]
        b = self.read(self.mm['battle_id'], 1)[0]
        n = story.bits(live)
        if n > self.best_bits:
            if self.best_bits >= 0:
                self.events.append(dict(v=v, kind='flags', bits=n, map=m, battle=b))
            self.best_bits = n
        if (m, b) != self.last_mb:
            self.events.append(dict(v=v, kind='map', map=m, battle=b))
            self.last_mb = (m, b)
        while self.g < len(self.goals):
            t = self.goals[self.g]
            miss, extra = story.compare(live, t['flags'])
            t['best_missing'] = min(t.get('best_missing', 1 << 30), miss)
            if t.get('map_goal'):
                self.map_hold = self.map_hold + 1 if (m, b) == (t['map'], 0) else 0
                if miss > 0 or self.map_hold < MAP_HOLD:
                    break
            elif miss > 0:
                break
            self.events.append(dict(v=v, kind='map-goal' if t.get('map_goal') else 'goal', goal=t['id'], playtime=t['pt'], map=m, battle=b, extra=extra))
            self.shot(f'goal-{t["id"].split(":")[-1]}-{v}')
            print(f'  {self.out.name}: reached {t["id"]} at VBlank {v}', flush=True)
            self.g += 1
            if self.stop_after is not None and self.g >= self.stop_after:
                self.stop_at = v + 300
        if getattr(self, 'stop_at', None) and v >= self.stop_at:
            raise Done('goal')
        if v % SHOT_EVERY == 0:
            self.shot(f'shot-{v:06d}')


def scenario_targets(profile, saves):
    mm = memory_map.lookup(profile)
    ts = story.story_order(sweep.targets_from_saves(saves, mm['scenario']))
    for t in ts:
        t['flags'] = story.flags_of(t['record']['data'])
        t['pt'] = story.hms(story.playtime(t['record']['data']))
    return ts


def find(ts, rid):
    hit = [t for t in ts if t['id'] == rid or t['id'].endswith(':' + rid) or t['id'].endswith(rid)]
    if len(hit) != 1:
        raise SystemExit(f'record {rid}: {len(hit)} matches')
    return hit[0]


def end_hashes(s, profile):
    mm = memory_map.lookup(profile)
    ram = b''.join(s.read(0x06000000 + i, 0x10000) for i in range(0, 0x100000, 0x10000))
    fl = s.read(story.flag_addr(profile), story.FLAG_HI - story.FLAG_LO)
    units = None
    if mm.get('units'):
        units = {k: [list(u) for u in memory_map.read_units(s.read, mm['units'][k], mm['units'].get('live'))][:24]
                 for k in ('force', 'enemies')}
    if os.environ.get('SF3_STORY_DUMP'):           # debugging determinism: keep the RAM image
        Path(os.environ['SF3_STORY_DUMP'] + f'-{s.r.vblank}.ram').write_bytes(ram)
    return dict(units=units, vblank=s.r.vblank, ram_sha1=hashlib.sha1(ram).hexdigest()[:16],
                flags_sha1=hashlib.sha1(fl).hexdigest()[:16], flag_bits=story.bits(fl),
                map=s.read(mm['map_id'], 1)[0], battle=s.read(mm['battle_id'], 1)[0])


def start_run(saturn, cue, target, scenario, work, coverage=True, clock=CLOCK):
    from saturnrecomp import agent
    work.mkdir(parents=True, exist_ok=True)
    (work / 'backup.bin').write_bytes(sweep.backup_for(target, scenario))
    args = ['--headless', '--cue', str(cue), '--save', str(work / 'backup.bin'), '--settings', '-',
            '--log', str(work / 'run.log')]
    if clock:
        args += ['--clock', clock]
    if coverage:
        args += ['--coverage', str(work / 'coverage.tsv')]
    os.environ.setdefault('SDL_VIDEO_DRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIO_DRIVER', 'dummy')
    r = agent.start(str(saturn), args, str(work / 'o'))
    r._sock.settimeout(120)
    return r


def apply_actions(s, actions, until=None):
    """Press/poke `actions` frame for frame (s a Recorder: they are logged again)."""
    i = 0
    while i < len(actions):
        v = actions[i][0]
        while s.r.vblank < v:
            s.step()
        while i < len(actions) and actions[i][0] == v:
            a = actions[i]
            if a[1] == 'pad':
                s.pad(tuple(x for x in a[2].split('+') if x))
            else:
                s.write(int(a[2], 16), bytes.fromhex(a[3]))
            i += 1
    if until:
        while s.r.vblank < until:
            s.step()


def modules_run(path):
    mods = set()
    if path.exists():
        for line in path.read_text(errors='replace').splitlines():
            p = line.split()
            if len(p) >= 4 and p[3].isdigit() and int(p[3]) > 0:
                mods.add(p[0])
    return sorted(mods)


def fatal_lines(work):
    out = []
    for name in ('run.log', 'o/log.txt'):
        f = work / name
        if f.exists():
            out += [l for l in f.read_text(errors='replace').splitlines() if 'FATAL' in l or 'unresolved' in l][:5]
    return out


def goal_list(ts, start):
    i0 = ts.index(start)
    goals = [dict(t) for t in ts[i0 + 1:] if story.playtime(t['record']['data']) > story.playtime(start['record']['data'])]
    # only records that add story-flag bits are flag goals (end-of-battle and suspend saves often
    # carry the same flags as the start: those are proven by the battle outcome and map events)
    # Town/complete records with no new flag bits become map goals: the state block shows their map
    # with battle 0 for MAP_HOLD checks in a row (the ending's COMPLETE record, Sc1 map A0).
    # Item/class-change saves are not story points.
    union, kept, last_map = bytearray(start['flags']), [], start['map']
    for t in goals:
        if re.search(r'(?i)items|class', t['id']):
            continue
        if story.compare(union, t['flags'])[0] > 0:
            kept.append(t)
            union = bytearray(x | y for x, y in zip(union, t['flags']))
        elif t['battle'] == 0 and t['map'] != last_map:
            kept.append(dict(t, map_goal=True))
        last_map = t['map']
    return kept


def _stop_reset(sd):
    raise Done('reset')


def drive(a):
    from saturnrecomp import agent
    mm = memory_map.lookup(a.profile)
    ts = scenario_targets(a.profile, a.saves)
    start = find(ts, a.record)
    goals = goal_list(ts, start)
    if a.goals:
        goals = goals[:a.goals]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    prefix, prefix_check = [], None
    if a.cont:
        h, prefix = story.parse_segment(Path(a.cont).read_text())
        assert h['record'] == start['id'], 'continue: segment starts at another record'
        if h.get('clock', 'host') != a.clock:
            print(f"continue: segment clock {h.get('clock', 'host')} (not {a.clock}); prefix will not match", flush=True)
    r = start_run(a.saturn, a.cue, start, mm['scenario'], out, clock=a.clock)
    s = Recorder(r, a.profile, goals, out, stop_after=a.stop_after, max_frames=a.max_vblank)
    t0, status, load, res = time.time(), 'ok', None, None
    try:
        if prefix:
            s.loaded = True
            apply_actions(s, prefix, until=int(h['end_vblank']))
            load = int(h.get('load', 0)) or None
            e = end_hashes(s, a.profile)
            prefix_check = 'MATCH' if e['ram_sha1'] == h.get('end_ram_sha1') else 'DIFF'
            print(f'continue: prefix replay at VBlank {e["vblank"]}: {prefix_check}', flush=True)
        else:
            load = diff.drive_to_load(s, mm['tick'], [], 6500, start_frames=(1100, 1308))
            if load is None:
                raise Done('no-load')
            s.loaded = load
        res = autoplay.play(s, a.profile, a.frames, a.seed, assist=a.assist, walker=True, rearm=20, idle_over_turns=60, pathing=a.pathing,
                            reload=_stop_reset if a.no_reload else lambda sd: autoplay.reload_menu(sd, a.profile, 6500))
    except Done as e:
        status = 'ok' if str(e) in ('frames', 'goal') else str(e)
    except (agent.RunEnded, agent.AgentError, BrokenPipeError, ConnectionResetError) as e:
        status = 'ended'
        print('ended', e, flush=True)
    except socket.timeout:
        status = 'hang'
        r._proc.kill()
    end = None
    if status == 'ok':
        s.shot(f'end-{r.vblank}')
        end = end_hashes(s, a.profile)
    try:
        r.close()
    except Exception:
        r._proc.kill()
    fat = fatal_lines(out)
    if fat and status in ('ok', 'ended'):
        status = 'crash'
    reached = [e['goal'] for e in s.events if e['kind'] in ('goal', 'map-goal')]
    header = dict(profile=a.profile, save=Path(start_save(a.saves, start)).name, record=start['id'],
                  seed=a.seed if not a.cont else f"{h.get('seed')}+{a.seed}", assist=a.assist or 'none',
                  clock=a.clock, record_sha1=hashlib.sha1(start['record']['data']).hexdigest()[:16],
                  load=load, binary=sha_bin(a.saturn), end_vblank=end and end['vblank'],
                  end_ram_sha1=end and end['ram_sha1'], end_flags_sha1=end and end['flags_sha1'],
                  reached=','.join(reached) or '-')
    (out / 'segment.txt').write_text(story.segment_text(header, s.actions))
    result = dict(status=status, prefix_check=prefix_check, fatal=fat, start=start['id'], start_playtime=start['pt'], load=load,
                  seconds=round(time.time() - t0), reached=reached, end=end, actions=len(s.actions),
                  actions_sha1=story.actions_sha1(s.actions), assist=a.assist, seed=header['seed'],
                  next_goal=goals[s.g]['id'] if s.g < len(goals) else None,
                  next_goal_best_missing=goals[s.g].get('best_missing') if s.g < len(goals) else None,
                  events=s.events[-200:], outcomes=res and res.get('outcomes'), resets=res and res.get('resets'),
                  modules=modules_run(out / 'coverage.tsv'))
    (out / 'result.json').write_text(json.dumps(result, indent=1) + '\n')
    print(f"{start['id']} {status} reached={reached} next={result['next_goal']} missing={result['next_goal_best_missing']} "
          f"X049={'X049' in result['modules']} {result['seconds']}s", flush=True)
    return result


def start_save(saves, t):
    from sf3test import saves as sv
    for p in saves:
        for rec in sv.load_any(Path(p).read_bytes()):
            if rec['data'] == t['record']['data']:
                return p
    return '?'


def sha_bin(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def replay(a):
    h, actions = story.parse_segment(Path(a.segment).read_text())
    profile = h['profile']
    mm = memory_map.lookup(profile)
    ts = scenario_targets(profile, a.saves)
    start = find(ts, h['record'])
    out = Path(a.out)
    if h.get('binary') and h['binary'] != sha_bin(a.saturn):
        print(f"warning: segment recorded on binary {h['binary']}, replaying on {sha_bin(a.saturn)}")
    clock = h.get('clock')
    if not clock:
        print('warning: segment has no clock (recorded on the host clock): the RAM hash will not match')
    r = start_run(a.saturn, a.cue, start, mm['scenario'], out, coverage=a.coverage, clock=clock)
    want = [g for g in (h.get('reached') or '-').split(',') if g and g != '-']
    goals = goal_list(ts, start)
    s = Recorder(r, profile, goals, out)
    s.loaded = True
    t0 = time.time()
    apply_actions(s, actions, until=int(h['end_vblank']) if h.get('end_vblank') not in (None, 'None') else None)
    end = end_hashes(s, profile)
    s.shot(f'replay-end-{end["vblank"]}')
    r.close()
    reached = [e['goal'] for e in s.events if e['kind'] in ('goal', 'map-goal')]
    fat = fatal_lines(out)
    ok = (end['ram_sha1'] == h.get('end_ram_sha1') and end['flags_sha1'] == h.get('end_flags_sha1')
          and reached[:len(want)] == want and not fat)
    res = dict(segment=str(a.segment), match=ok, end=end, expect=dict(ram=h.get('end_ram_sha1'), flags=h.get('end_flags_sha1')),
               reached=reached, expect_reached=want, seconds=round(time.time() - t0), fatal=fat,
               modules=modules_run(out / 'coverage.tsv') if a.coverage else None)
    (out / 'replay.json').write_text(json.dumps(res, indent=1) + '\n')
    print(f"{a.segment}: {'MATCH' if ok else 'MISMATCH'} end {end} reached {reached}", flush=True)
    if a.rebase and not ok:
        # A runtime change moved the end state but the same pads still reach every goal: the replay on
        # this binary is the new recording. Write its binary and end hashes (load is kept: informational).
        if reached[:len(want)] != want or fat or not want:
            print(f'rebase: not written (reached {reached}, want {want}, fatal {len(fat)})', flush=True)
            return 1
        h.update(binary=sha_bin(a.saturn), end_ram_sha1=end['ram_sha1'], end_flags_sha1=end['flags_sha1'])
        Path(a.rebase).write_text(story.segment_text(h, actions))
        print(f"rebase: wrote {a.rebase} (binary {h['binary']}, ram {end['ram_sha1']}); replay it again to confirm", flush=True)
    return 0 if ok else 1


SUITE_KEYS = ('sc1', 'sc2v2', 'sc2v1', 'sc3')


def suite(a):
    """Replay every tools/story-replays/<key>/*.seg (the acceptance play-throughs) with the build,
    cue and saves directory from SF3_BUILD_<KEY>, SF3_CUE_<KEY>, SF3_SAVES_<KEY>; keys without them
    are skipped. Each replay runs in its own process; PASS when the end hashes match."""
    import concurrent.futures
    import glob
    import os
    import subprocess
    import tempfile
    here = Path(a.dir)
    out = Path(a.out or tempfile.mkdtemp(prefix='sf3-story-suite-'))
    out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for k in a.keys or SUITE_KEYS:
        env = [os.environ.get(f'SF3_{n}_{k.upper()}') for n in ('BUILD', 'CUE', 'SAVES')]
        segs = sorted((here / k).glob('*.seg'))
        if not segs:
            continue
        if not all(env):
            print(f'skip {k}: set SF3_BUILD_{k.upper()} SF3_CUE_{k.upper()} SF3_SAVES_{k.upper()}')
            continue
        for seg in segs:
            jobs.append((k, seg, env))

    def one(job):
        k, seg, (b, c, sv) = job
        name = f'{k}-{seg.stem}'
        cmd = [sys.executable, str(Path(__file__).resolve()), 'replay', '--saturn', b, '--cue', c, '--saves',
               *sorted(glob.glob(os.path.join(sv, '*.bin'))), '--out', str(out / name), str(seg)]
        with open(out / f'{name}.log', 'w') as log:
            rc = subprocess.call(cmd, stdout=log, stderr=subprocess.STDOUT)
        return f"{'PASS' if rc == 0 else 'FAIL'} {k}/{seg.stem}"

    with concurrent.futures.ThreadPoolExecutor(max(1, a.jobs)) as ex:
        lines = list(ex.map(one, jobs))
    for line in lines:
        print(line, flush=True)
    (out / 'summary.txt').write_text('\n'.join(lines) + '\n')
    print(f'{sum(x.startswith("PASS") for x in lines)}/{len(lines)} passed; outputs {out}')
    return 0 if lines and all(x.startswith('PASS') for x in lines) else 1


def order(a):
    for t in scenario_targets(a.profile, a.saves):
        print(f"{t['pt']:>10s} {t['id']:42s} map {t['map']:02X} battle {t['battle']:02X} flag bits {story.bits(t['flags'])}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('drive')
    d.add_argument('--saturn', required=True)
    d.add_argument('--cue', required=True)
    d.add_argument('--profile', required=True)
    d.add_argument('--saves', nargs='+', required=True)
    d.add_argument('--record', required=True)
    d.add_argument('--frames', type=int, default=30000)
    d.add_argument('--seed', type=int, default=1)
    d.add_argument('--goals', type=int, help='only the next N records as goals')
    d.add_argument('--stop-after', type=int, help='stop 300 frames after the N-th goal')
    d.add_argument('--max-vblank', type=int)
    d.add_argument('--continue', dest='cont', help='replay this segment first, then drive on')
    d.add_argument('--pathing', action='store_true', help='planned unit paths in battle (round 26)')
    d.add_argument('--no-reload', action='store_true', help='stop the drive (status reset) when the game falls back to its title (game over, quit) instead of reloading the save')
    d.add_argument('--assist', choices=['party', 'party+enemy1'], help='TEST ONLY battle stat pokes')
    d.add_argument('--clock', default=CLOCK, help='SMPC clock at power-on (default %(default)s)')
    d.add_argument('--out', required=True)
    r = sub.add_parser('replay')
    r.add_argument('--saturn', required=True)
    r.add_argument('--cue', required=True)
    r.add_argument('--saves', nargs='+', required=True)
    r.add_argument('--out', required=True)
    r.add_argument('--coverage', action='store_true')
    r.add_argument('--rebase', metavar='OUT', help='on an end-hash mismatch that still reaches every goal, write the segment '
                   'with this binary and its end hashes to OUT (re-record after a runtime change)')
    r.add_argument('segment')
    q = sub.add_parser('search', help='TAS-style battle search over save states (sf3test/search.py)')
    for n in ('--saturn', '--cue', '--profile', '--record', '--out'):
        q.add_argument(n, required=True)
    q.add_argument('--saves', nargs='+', required=True)
    q.add_argument('--continue', dest='cont', help='replay this segment first')
    q.add_argument('--clock', default=CLOCK)
    q.add_argument('--goals', type=int, default=1)
    q.add_argument('-k', type=int, default=8, help='candidates per level')
    q.add_argument('--window', type=int, default=1500, help='VBlanks committed per level')
    q.add_argument('--look', type=int, default=1500, help='greedy look-ahead VBlanks for the score')
    q.add_argument('--explore', type=float, default=0.35)
    q.add_argument('--seed', type=int, default=1)
    q.add_argument('--frames', type=int, default=150000)
    q.add_argument('--max-levels', type=int, default=400)
    q.add_argument('--max-backs', type=int, default=40)
    q.add_argument('--leader', type=int, help='force slot whose fall loses the battle (default: the lowest slot at the root; Sc3 Flagship: 31)')
    q.add_argument('--no-left', action='store_true', help='do not score battle id 0 as Egress/defeat (Sc2 V1.003: its map/battle bytes do not track in Ch6)')
    q.add_argument('--resync', action='store_true', help='after each level, replay the committed pads straight from the save and continue from that run (save-state restores are not exact)')
    q.add_argument('--stall', type=int, default=8, help='stop when the best score is flat this many levels (0: never)')
    q.add_argument('-j', '--jobs', type=int, default=4)
    o = sub.add_parser('order')
    o.add_argument('--profile', required=True)
    o.add_argument('--saves', nargs='+', required=True)
    u = sub.add_parser('suite', help='replay the committed acceptance segments')
    u.add_argument('--dir', default=str(ROOT / 'tools' / 'story-replays'))
    u.add_argument('--out')
    u.add_argument('-j', '--jobs', type=int, default=1)
    u.add_argument("keys", nargs="*", help="sc1 sc2v2 sc2v1 sc3 (default all)")
    a = ap.parse_args()
    for p in [getattr(a, 'cue', None), getattr(a, 'out', None), *getattr(a, 'saves', [])]:
        if p:
            sweep.external(p, ROOT)
    return {'drive': lambda: drive(a) and 0, 'replay': lambda: replay(a), 'order': lambda: order(a),
            'search': lambda: __import__('sf3test.search', fromlist=['search']).search(a), 'suite': lambda: suite(a)}[a.cmd]()


if __name__ == '__main__':
    sys.exit(main() or 0)
