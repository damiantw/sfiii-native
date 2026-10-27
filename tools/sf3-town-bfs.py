"""SF3 town walk by breadth-first search over native states (bring-your-own build, disc and saves;
states and pictures stay outside the repository, and each state is deleted once expanded).

  SF3_STATE_ID=any python tools/sf3-town-bfs.py --saturn BUILD/saturn --cue DISC.cue \
      --profile scenario1-v25_1 --save SAVES.bin --record 03 --state START.state --out /private/bfs

START.state is a native state (agent `save PATH`) taken in a town with the player free to walk.
Each frontier tile is restored with --state-in, a direction is held until the tile changes, and the
new (scene, tile) is kept once. The player object is the one the tile-event lookup 06056DF0 is
called with (SF3_CALL_TRACE, caller 06056C1C passes it in r3); its tile is memory_map.player_tile.
A scene change is a goal: its picture and a state in the new scene are kept. OUT/result.json.
--coverage: every restore also runs with --coverage, and the union of the functions that ran is
written to OUT/coverage/coverage.tsv (a run directory sf3-coverage.py reads).
Each goal names the overlay file actually resident at 0605F000 (memory_map.overlay_file), and the
direction path from START that reached it.
--diagonal adds the four two-button moves (UP+LEFT, ...); --hold is how many frames a move is held
waiting for the tile to change (doors and stairs that only open on a diagonal or after a long walk).
Other scenarios: --fid ADDR keys the scene on the loaded scene-file id at ADDR instead of the Sc1
state block; --trace/--caller name their tile-event lookup and its caller; --obj fixes the player
object; --goal-scene N stops at the first goal in scene N."""
import argparse
import itertools
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / '.local' / 'saturn-recomp' / 'src'))
from sf3test import diff, memory_map, saves, sweep  # noqa: E402

DIRS = ('UP', 'DOWN', 'LEFT', 'RIGHT')
DIAGONALS = ('UP+LEFT', 'UP+RIGHT', 'DOWN+LEFT', 'DOWN+RIGHT')
LOOKUP_CALLER = 0x06056C20
SCENE_FID = memory_map.SC1_SCENES['fid_loaded']


def u32(s, a):
    return int.from_bytes(s.read(a, 4), 'big')


def u16(s, a):
    return int.from_bytes(s.read(a, 2), 'big')


def buttons(b):
    """'UP+LEFT' -> ('UP', 'LEFT'); '' -> ()."""
    return tuple(x for x in b.split('+') if x) if b else ()


def hold(s, b, n, rest):
    s.pad(buttons(b))
    for _ in range(n):
        s.step()
    s.pad(())
    for _ in range(rest):
        s.step()


def player_obj(log, default, caller=LOOKUP_CALLER):
    objs = []
    for line in open(log):
        if line.startswith('trace '):
            f = dict(kv.split('=') for kv in line.split()[2:])
            if int(f['pr'], 16) == caller:
                objs.append(int(f['r3'], 16))
    return objs[-1] if objs else default


def save_state(s, path):
    s.r._ask('save ' + path)
    for _ in range(120):
        s.step()
        if not s.r._ask('saved').startswith('saved busy'):
            break
    return path if os.path.exists(path) else None


def expand(job):
    from saturnrecomp import agent
    a, src, d, n = job
    out, work = Path(a['out']), Path(a['out']) / f'w{n}'
    try:
        work.mkdir(parents=True, exist_ok=True)
        (work / 'backup.bin').write_bytes(saves.native_backup([a['record']]))
        args = ['--headless', '--cue', a['cue'], '--save', str(work / 'backup.bin'), '--settings', '-', '--state-in', src]
        if a.get('coverage'):
            args += ['--coverage', str(work / 'coverage.tsv')]
        with agent.start(a['saturn'], args, str(work / 'ours')) as r:
            s = diff.OurSide(r)
            if a.get('fid'):
                scn = lambda: u32(s, a['fid'])
            else:
                state = u32(s, u32(s, a['state_ptr']))
                scn = lambda: u16(s, state + 16)
            scene0 = scn()
            hold(s, 'B', 6, 12)
            hold(s, d, 1, 14)
            obj = a.get('fixed_obj') or player_obj(work / 'ours' / 'log.txt', a['obj'], a.get('caller', LOOKUP_CALLER))
            tile = lambda: memory_map.player_tile(u32(s, obj + 12), u32(s, obj + 20))
            at = tile()
            s.pad(buttons(d))
            for _ in range(a.get('hold', 24)):
                s.step()
                if tile() != at:
                    break
            s.pad(())
            for _ in range(a.get('wait', 90)):
                s.step()
                if scn() != scene0:
                    break
            res = dict(src=src, d=d, frm=at, obj=obj, scene0=scene0, state=None)
            if scn() != scene0:
                for _ in range(500):
                    s.step()
                for _ in range(6):
                    hold(s, 'C', 6, 30)
                for _ in range(3):
                    hold(s, 'B', 6, 20)
                s.frame().save_png(str(out / f'goal-{scn()}-{n}.png'))
                res['state'] = save_state(s, str(out / f'g{n}.state'))
            elif tile() != at:
                res['state'] = save_state(s, str(out / f's{n}.state'))
            res.update(scene=scn(), fid=u32(s, a.get('fid') or SCENE_FID), tile=tile())
            if res['scene'] != scene0 and a.get('build'):
                res['overlay'] = memory_map.overlay_file(s.read(memory_map.SC1_SCENES['overlay_base'], 0x10000), a['build'])
        cov = work / 'coverage.tsv'
        if cov.exists():
            res['ran'] = [ln for ln in cov.read_text().splitlines() if ln.endswith(' 1')]
        return res
    except Exception as e:
        return dict(src=src, d=d, error=repr(e)[:200])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--saturn', required=True)
    p.add_argument('--cue', required=True)
    p.add_argument('--profile', required=True)
    p.add_argument('--save', required=True)
    p.add_argument('--record', required=True, help='record number in the save, e.g. 03')
    p.add_argument('--state', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--budget', type=int, default=3000, help='restores at most')
    p.add_argument('--jobs', type=int, default=6)
    p.add_argument('--coverage', action='store_true', help='union coverage of all restores in OUT/coverage')
    p.add_argument('--build', help='profile build root (stage/extract) to name the resident overlay of each goal')
    p.add_argument('--diagonal', action='store_true', help='also try UP+LEFT, UP+RIGHT, DOWN+LEFT, DOWN+RIGHT')
    p.add_argument('--hold', type=int, default=24, help='frames a move is held waiting for the tile to change')
    p.add_argument('--wait', type=int, default=90, help='frames waited after a move for a scene change')
    hexa = lambda v: int(v, 16)
    p.add_argument('--fid', type=hexa, help='hex address of the loaded scene-file id (scene key; default Sc1 state block)')
    p.add_argument('--trace', default='06056DF0', help='hex tile-event lookup traced to find the player object')
    p.add_argument('--caller', type=hexa, default=LOOKUP_CALLER, help='hex return address of that lookup call')
    p.add_argument('--obj', type=hexa, help='hex player object (skips the trace)')
    p.add_argument('--goal-scene', type=int, help='stop at the first goal in this scene')
    o = p.parse_args()
    os.environ['SF3_CALL_TRACE'] = o.trace
    os.environ.setdefault('SF3_STATE_ID', 'sf3-town-bfs')  # must match the id START.state was saved with
    mm = memory_map.lookup(o.profile)
    target = [t for t in sweep.targets_from_saves([o.save], mm['scenario']) if t['id'].endswith(':' + o.record)][0]
    a = dict(saturn=o.saturn, cue=o.cue, out=o.out, obj=memory_map.SC1_PLAYER['obj'], state_ptr=0x0602AE64,
             record=dict(target['record'], name=f"SFORCE3{mm['scenario']}_01"), coverage=o.coverage, build=o.build,
             hold=o.hold, wait=o.wait, fid=o.fid, caller=o.caller, fixed_obj=o.obj)
    dirs = DIRS + (DIAGONALS if o.diagonal else ())
    Path(o.out).mkdir(parents=True, exist_ok=True)
    seen, goals, frontier, count, used, ran = set(), [], [o.state], itertools.count(), 0, set()
    paths, done = {o.state: []}, False
    with ProcessPoolExecutor(o.jobs) as ex:
        while frontier and used < o.budget and not done:
            jobs = [(a, src, d, next(count)) for src in frontier for d in dirs]
            used += len(jobs)
            new = []
            for res in ex.map(expand, jobs):
                ran.update(res.pop('ran', ()))
                if 'error' in res:
                    print('error', res, flush=True)
                    continue
                res['path'] = paths.get(res['src'], []) + [res['d']]
                if res['state']:
                    paths[res['state']] = res['path']
                key = (res['scene'], tuple(res['tile']))
                fresh = key not in seen
                seen.add(key)
                if res['scene'] != res['scene0'] and fresh:
                    goals.append(res)
                    print('goal', res, flush=True)
                    done = done or res['scene'] == o.goal_scene
                elif res['scene'] == res['scene0'] and fresh and res['state']:
                    new.append(res['state'])
                elif res['state']:
                    os.remove(res['state'])
            for src in frontier:
                if src != o.state and os.path.exists(src):
                    os.remove(src)
            frontier = new
            print(f'restores {used} tiles {len(seen)} frontier {len(frontier)} goals {len(goals)}', flush=True)
    for src in frontier:
        if os.path.exists(src):
            os.remove(src)
    if o.coverage and ran:
        (Path(o.out) / 'coverage').mkdir(exist_ok=True)
        (Path(o.out) / 'coverage' / 'coverage.tsv').write_text(''.join(ln + '\n' for ln in sorted(ran)))
    json.dump(dict(tiles=sorted(map(list, seen)), goals=goals), open(Path(o.out) / 'result.json', 'w'), indent=1, default=str)


if __name__ == '__main__':
    main()
