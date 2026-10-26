"""TAS-style battle search over native save states (round 5 of the story driver).

From a committed state, K candidates each restore it (a fresh process with --state-in), play W
VBlanks with the battle policy (candidate 0 greedy, the others with exploration and their own
seed), let go of the pad, save a state, then look ahead L VBlanks with the greedy policy and are
scored on the unit tables (enemy HP taken, kills, party HP, deaths, the leader's HP; a won battle
or a reached goal is best, a fallen leader worst). The best candidate's W VBlanks are committed;
when every candidate at a level loses, the search backs up one level and takes that level's next
best. Only pad presses are kept, so the result is an ordinary pad-only segment that `replay`
checks from the save; states stay in the work directory (never in the repository).
"""
import copy
import shutil
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

from . import autoplay, memory_map

_ST = None


def st():
    """The sf3-story.py module (Recorder, start_run, end_hashes ...)."""
    global _ST
    if _ST is None:
        p = Path(__file__).resolve().parents[1] / 'sf3-story.py'
        spec = importlib.util.spec_from_file_location('sf3_story', p)
        _ST = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_ST)
    return _ST


def unit_hp(read, units):
    """{side: {slot: (hp, max hp)}} for the live records of both unit tables."""
    out = {}
    for side in ('force', 'enemies'):
        base = units[side]
        got = {}
        for k, x, y, f, hp in memory_map.read_units(read, base, units.get('live')):
            e = read(base + k * memory_map.UNIT_STRIDE + memory_map.UNIT_MAX_HP, 2)
            got[k] = (hp, int.from_bytes(e, 'big'))
        out[side] = got
    return out


def metrics(units_now, root, leader):
    """Battle standing against the root roster (`root` a unit_hp result at the search start)."""
    f, e = units_now['force'], units_now['enemies']
    e_top = sum(max(m, h, 1) for h, m in root['enemies'].values()) or 1
    e_left = sum(e.get(k, (0, 0))[0] for k in root['enemies'])
    kills = sum(1 for k in root['enemies'] if e.get(k, (0, 0))[0] <= 0)
    f_top = sum(max(m, h, 1) for h, m in root['force'].values()) or 1
    f_left = sum(f.get(k, (0, 0))[0] for k in root['force'])
    deaths = sum(1 for k in root['force'] if f.get(k, (0, 0))[0] <= 0)
    lh, lm = f.get(leader, (0, 1))
    lroot = max(root['force'].get(leader, (1, 1)))
    return dict(enemy_left=e_left / e_top, kills=kills, force_left=f_left / f_top, deaths=deaths,
                leader=lh / max(lm, lroot, 1), leader_down=lh <= 0,
                won=bool(root['enemies']) and kills == len(root['enemies']))


def score(m):
    if m.get('goal'):
        return 1e6
    if m['leader_down'] or m.get('reset') or m.get('left'):
        return -1e6
    if m['won']:
        return 1e5
    return (4 * (1 - m['enemy_left']) + 1.0 * m['kills'] + 1.5 * m['force_left'] - 1.0 * m['deaths']
            + 2 * m['leader'])


def left_battle(read, job, reached):
    """Back in a town without a goal: Egress or a defeat (the battle id is 0 outside battles).

    A won battle can keep its id set through the after-battle scenes (Sc3 Flagship: map 9 battle 1),
    and the unit tables keep their last values, so a win is not seen here; --stall catches it."""
    if not job.get('root_battle') or job.get('no_left') or reached:
        return False
    return read(memory_map.lookup(job['profile'])['battle_id'], 1)[0] == 0


def save_state(r, path):
    r._ask('save ' + str(path))
    for _ in range(600):
        r.step()
        if not r._ask('saved').startswith('saved busy'):
            break
    return Path(path).exists()


def run_args(job, state=None):
    args = ['--headless', '--cue', job['cue'], '--save', job['backup'], '--settings', '-', '--clock', job['clock']]
    if state:
        args += ['--state-in', str(state)]
    return args


def _play(s, job, frames, seed, explore):
    return autoplay.play(s, job['profile'], frames, seed, walker=True, rearm=20, idle_over_turns=60,
                         pathing=True, explore=explore)


def candidate(job):
    """One branch: restore job['state'], play W (+ lookahead L). Runs in a worker process."""
    from saturnrecomp import agent
    S = st()
    out = Path(job['out'])
    out.mkdir(parents=True, exist_ok=True)
    os.environ['SF3_STATE_ID'] = job['state_id']
    res = dict(seed=job['seed'], explore=job['explore'], out=str(out))
    # round 5: each branch gets its own backup memory file, copied from its parent's (the game writes
    # its save at a goal record; candidates sharing one file made the end RAM differ from a replay)
    shutil.copyfile(job['backup'], out / 'backup.bin')
    job = dict(job, backup=str(out / 'backup.bin'))
    r = agent.start(job['saturn'], run_args(job, job['state']), str(out / 'o'))
    r._sock.settimeout(120)
    try:
        s = S.Recorder(r, job['profile'], copy.deepcopy(job['goals']), out)
        s.loaded, s.g, s.held = True, 0, ''
        while r.vblank < job['v']:
            s.step()
        units = memory_map.lookup(job['profile'])['units']
        map0 = s.read(memory_map.lookup(job['profile'])['map_id'], 1)[0]
        p = _play(s, job, job['W'], job['seed'], job['explore'])
        s.pad(())
        for _ in range(30):
            s.step()
        reached = [e['goal'] for e in s.events if e['kind'] in ('goal', 'map-goal')]
        m1 = metrics(unit_hp(s.read, units), job['root'], job['leader'])
        m1.update(goal=bool(reached), reset=bool(p['resets']), left=left_battle(s.read, job, reached))
        state = out / 'commit.state'
        if not save_state(r, state):
            raise RuntimeError('state not written')
        end = S.end_hashes(s, job['profile'])
        if job.get('progress'):
            # story progress outside battle: new map ids seen and story flag bits set
            new_maps = {e[1] for e in p['events'] if e[1] not in (-1, map0)}
            # how far the force has walked from where it stood at the search root (finds doors)
            pos = {k: (x, y) for k, x, y, f, hp in memory_map.read_units(s.read, units['force'], units.get('live'))}
            spread = max([abs(x - job['root_pos'][k][0]) + abs(y - job['root_pos'][k][1])
                          for k, (x, y) in pos.items() if k in job['root_pos']] or [0])
            m1.update(new_maps=len(new_maps), flag_bits=end.get('flag_bits', 0), spread=spread)
        res.update(actions=[a for a in s.actions if a[0] >= job['v']], v=r.vblank, end=end, state=str(state),
                   backup=job['backup'],
                   m_commit=m1, reached=reached)
        if job['L'] and not reached and score(m1) > -1e6:
            p2 = _play(s, job, job['L'], job['seed'] + 7919, 0.0)
            m2 = metrics(unit_hp(s.read, units), job['root'], job['leader'])
            r2 = [e['goal'] for e in s.events if e['kind'] in ('goal', 'map-goal')]
            m2.update(goal=bool(r2), reset=bool(p2['resets']), left=left_battle(s.read, job, r2))
        else:
            m2 = m1
        res.update(m_look=m2, score=score(m1) if m1.get('goal') or score(m1) <= -1e6 else score(m2))
        if job.get('progress') and res['score'] > -1e6:
            res['score'] += 1000 * m1['new_maps'] + 10 * m1['flag_bits'] + 2 * m1['spread']
    except Exception as e:
        res.update(error=repr(e)[:300], score=-2e6)
    finally:
        try:
            r.close()
        except Exception:
            r._proc.kill()
    return res


def search(a):
    """`sf3-story.py search`: see the module doc. Writes OUT/segment.txt (start record, pads only),
    OUT/search.json (per level: the candidates' scores) and keeps the states in OUT/states."""
    from concurrent.futures import ProcessPoolExecutor
    from saturnrecomp import agent
    from . import diff, story
    S = st()
    os.environ['SF3_STATE_ID'] = state_id = f'search-{S.sha_bin(a.saturn)}'
    mm = memory_map.lookup(a.profile)
    units = mm['units']
    ts = S.scenario_targets(a.profile, a.saves)
    start = S.find(ts, a.record)
    goals = S.goal_list(ts, start)[:a.goals or None]
    out = Path(a.out)
    (out / 'states').mkdir(parents=True, exist_ok=True)
    # root: the record's load (+ a --continue prefix), then the greedy policy until enemies are live
    r = S.start_run(a.saturn, a.cue, start, mm['scenario'], out / 'root', coverage=False, clock=a.clock)
    rs = S.Recorder(r, a.profile, copy.deepcopy(goals), out / 'root')
    h = {}
    if a.cont:
        h, prefix = story.parse_segment(Path(a.cont).read_text())
        rs.loaded = True
        S.apply_actions(rs, prefix, until=int(h['end_vblank']))
        load = int(h.get('load', 0)) or None
    else:
        load = diff.drive_to_load(rs, mm['tick'], [], 6500, start_frames=(1100, 1308))
        rs.loaded = load
    for _ in range(200):
        hp = unit_hp(rs.read, units)
        if rs.read(mm['battle_id'], 1)[0] and any(v[0] > 0 for v in hp['enemies'].values()) and hp['force']:
            break
        autoplay.play(rs, a.profile, 300, a.seed, walker=True, rearm=20, idle_over_turns=60, pathing=True)
    rs.pad(())
    for _ in range(30):
        rs.step()
    root = unit_hp(rs.read, units)
    root_pos = {k: (x, y) for k, x, y, f, hp in memory_map.read_units(rs.read, units['force'], units.get('live'))}
    root_battle = rs.read(mm['battle_id'], 1)[0]
    leader = getattr(a, 'leader', None)
    if leader is None or leader not in root['force']:
        leader = min(root['force'])
    st0 = out / 'states' / 'root.state'
    save_state(r, st0)
    base_actions, v0 = list(rs.actions), r.vblank
    root_end = S.end_hashes(rs, a.profile)
    r.close()
    shutil.copyfile(out / 'root' / 'backup.bin', out / 'states' / 'root.backup.bin')
    print(f'root at VBlank {v0}: {len(root["force"])} force, {len(root["enemies"])} enemies, leader slot {leader}', flush=True)
    common = dict(saturn=a.saturn, cue=str(a.cue), clock=a.clock,
                  profile=a.profile, goals=goals, root=root, root_battle=root_battle, no_left=getattr(a, 'no_left', False), leader=leader, state_id=state_id, W=a.window, L=a.look,
                  progress=getattr(a, 'progress', False), root_pos=root_pos)
    # levels: each a dict(state, v, actions (from the start), ranked candidates, pick index)
    levels = [dict(state=str(st0), v=v0, actions=base_actions, end=root_end, ranked=[], pick=0, score=0,
                   backup=str(out / 'states' / 'root.backup.bin'))]
    log, backs, done_goal, stalled = [], 0, False, False
    with ProcessPoolExecutor(a.jobs) as ex:
        while levels[-1]['v'] - v0 < a.frames and len(log) < a.max_levels:
            cur = levels[-1]
            n = len(log)
            jobs = [dict(common, state=cur['state'], backup=cur['backup'], v=cur['v'], seed=a.seed * 1000 + n * 37 + i,
                         explore=0.0 if i == 0 else a.explore, out=str(out / 'c' / f'{n:04d}-{i}'))
                    for i in range(a.k)]
            res = sorted(ex.map(candidate, jobs), key=lambda x: -x['score'])
            log.append([dict(seed=x['seed'], explore=x['explore'], score=round(x['score'], 3), v=x.get('v'),
                             m=x.get('m_look'), error=x.get('error')) for x in res])
            best = res[0]
            print(f"level {len(levels)} @{cur['v']}: best {best['score']:.2f} ({best.get('m_look')}) "
                  f"of {[round(x['score'], 2) for x in res]}", flush=True)
            # back up while the best here is a loss
            if best['score'] <= -1e6:
                backs += 1
                while len(levels) > 1:
                    levels.pop()
                    prev = levels[-1]
                    prev['pick'] += 1
                    if prev['pick'] < len(prev['ranked']) and prev['ranked'][prev['pick']]['score'] > -1e6:
                        c = prev['ranked'][prev['pick']]
                        levels.append(dict(state=c['state'], v=c['v'], actions=prev['actions'] + c['actions'],
                                           end=c['end'], ranked=[], pick=0, score=c['score'], backup=c['backup'],
                                           reached=c.get('reached')))
                        print(f'  back to level {len(levels) - 1}, candidate {prev["pick"]}', flush=True)
                        break
                if backs > a.max_backs or len(levels) == 1 and levels[0]['pick'] >= len(levels[0]['ranked']):
                    print('search: out of branches', flush=True)
                    break
                continue
            cur['ranked'] = res
            levels.append(dict(state=best['state'], v=best['v'], actions=cur['actions'] + best['actions'],
                               end=best['end'], ranked=[], pick=0, score=best['score'], reached=best.get('reached'),
                               backup=best['backup']))
            if getattr(a, 'resync', False):
                # restored save states do not carry every byte a straight run has, and the difference can
                # change a battle's damage rolls: replay the committed pads from the save in a fresh run and
                # continue from that run's state, so the search follows what the segment will replay
                sm = resync(a, S, start, mm, units, out, levels[-1], common, len(log))
                print(f"  sync @{levels[-1]['v']}: straight {score(sm):.2f} ({sm}) vs searched {score(best['m_commit']):.2f}", flush=True)
                best = dict(best, m_commit=sm, reached=levels[-1].get('reached'))
                if score(sm) <= -1e6:
                    levels.pop()
                    cur['ranked'], cur['pick'] = [], 0
                    backs += 1
                    if backs > a.max_backs:
                        print('search: out of branches', flush=True)
                        break
                    continue
            (out / 'search.json').write_text(json.dumps(dict(levels=log, path=[l['v'] for l in levels]), indent=0, default=str))
            write_segment(a, out, start, load, h, levels[-1], S)
            flat = 0
            while flat + 2 < len(levels) and round(levels[-2 - flat]['score'], 3) == round(levels[-1]['score'], 3):
                flat += 1
            if a.stall and flat >= a.stall and not best.get('reached'):
                # the score has not moved for --stall levels: the battle is over (a win the unit tables do
                # not show) or the policy is stuck; keep the plateau's first level and stop
                del levels[len(levels) - flat:]
                stalled = True
                print(f"search: stalled {flat} levels at {levels[-1]['score']:.2f}; segment cut at VBlank "
                      f"{levels[-1]['v']} (continue with drive --continue)", flush=True)
                break
            if best.get('reached') or best['m_commit'].get('won'):
                done_goal = True
                print(f"search: {'goal ' + ','.join(best['reached']) if best.get('reached') else 'battle won'} at VBlank {best['v']}", flush=True)
                break
    write_segment(a, out, start, load, h, levels[-1], S)
    if done_goal or stalled:
        finalize(a, out)
    return 0 if done_goal else 2 if stalled else 1


def resync(a, S, start, mm, units, out, lv, common, n):
    """Straight replay of lv['actions'] to lv['v'] from the save; lv takes that run's state, backup, end
    hashes and goals. Returns the straight run's metrics."""
    work = out / 'sync' / f'{n:04d}'
    r = S.start_run(a.saturn, a.cue, start, mm['scenario'], work, coverage=False, clock=a.clock)
    try:
        s = S.Recorder(r, a.profile, copy.deepcopy(common['goals']), work)
        s.loaded = True
        S.apply_actions(s, lv['actions'], until=lv['v'])
        while r.vblank < lv['v']:
            s.step()
        here, hv = S.end_hashes(s, a.profile), r.vblank  # hash at lv['v'], before save_state steps on
        reached = [e['goal'] for e in s.events if e['kind'] in ('goal', 'map-goal')]
        m = metrics(unit_hp(s.read, units), common['root'], common['leader'])
        m.update(goal=bool(reached), reset=False, left=left_battle(s.read, common, reached))
        st = out / 'states' / f'sync-{n:04d}.state'
        if not save_state(r, st):
            raise RuntimeError('sync state not written')
        e0 = (lv.get('end') or {}).get('ram_sha1')
        lv.update(state=str(st), v=r.vblank, end=S.end_hashes(s, a.profile), reached=reached or lv.get('reached'))
        print(f"  ram @{hv}: searched {e0} straight {here.get('ram_sha1')} "
              f"{'equal' if e0 == here.get('ram_sha1') else 'DIFFER'}", flush=True)
    finally:
        r.close()
    bk = out / 'states' / f'sync-{n:04d}.backup.bin'
    shutil.copyfile(work / 'backup.bin', bk)
    lv['backup'] = str(bk)
    shutil.rmtree(work, ignore_errors=True)
    return m


def finalize(a, out):
    """Re-derive the end hashes from a straight replay of the segment.

    The search commits through restored save states, which carry the game state but not every
    byte of work RAM a straight run would have, so the end RAM hash of the chained run can
    differ from a replay from the save even though the inputs and the reached goal are the
    same. The committed segment must describe the straight replay, so it is replayed here and
    the header takes that run's end hashes (segment-search.txt keeps the search's own)."""
    import re
    import subprocess
    from . import story
    seg = out / 'segment.txt'
    text = seg.read_text()
    (out / 'segment-search.txt').write_text(text)
    cmd = [sys.executable, str(Path(__file__).resolve().parents[1] / 'sf3-story.py'), 'replay', '--saturn', a.saturn,
           '--cue', a.cue, '--saves', *a.saves, '--out', str(out / 'verify'), str(seg)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    (out / 'verify.log').write_text(r.stdout + r.stderr)
    line = next((l for l in r.stdout.splitlines() if ' end {' in l), '')
    ram = re.search(r"'ram_sha1': '(\w+)'", line)
    flags = re.search(r"'flags_sha1': '(\w+)'", line)
    h, actions = story.parse_segment(text)
    want = [g for g in h.get('reached', '-').split(',') if g != '-']
    if not (ram and flags) or any(g not in line for g in want):
        print(f'search: straight replay did not reach {want}; segment left as searched', flush=True)
        return False
    h_old = h.get('end_ram_sha1')
    h.update(end_ram_sha1=ram.group(1), end_flags_sha1=flags.group(1))
    seg.write_text(story.segment_text(h, actions))
    print(f"search: end hashes from the straight replay (ram {ram.group(1)}, search had {h_old})", flush=True)
    return True


def write_segment(a, out, start, load, h, lv, S):
    from . import story
    seed = f"search-k{a.k}-w{a.window}-l{a.look}-s{a.seed}"
    if a.cont:
        seed = f"{h.get('seed')}+{seed}"
    header = dict(profile=a.profile, save=Path(S.start_save(a.saves, start)).name, record=start['id'], seed=seed,
                  assist='none', clock=a.clock, record_sha1=hashlib.sha1(start['record']['data']).hexdigest()[:16],
                  load=load, binary=S.sha_bin(a.saturn), end_vblank=lv['v'], end_ram_sha1=lv['end']['ram_sha1'],
                  end_flags_sha1=lv['end']['flags_sha1'], reached=','.join(lv.get('reached') or []) or '-')
    (out / 'segment.txt').write_text(story.segment_text(header, lv['actions']))
