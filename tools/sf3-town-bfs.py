"""SF3 town walk by breadth-first search over native states (bring-your-own build, disc and saves;
states and pictures stay outside the repository, and each state is deleted once expanded).

  SF3_STATE_ID=any python tools/sf3-town-bfs.py --saturn BUILD/saturn --cue DISC.cue \
      --profile scenario1-usa-v25_1 --save SAVES.bin --record 03 --state START.state --out /private/bfs

START.state is a native state (agent `save PATH`) taken in a town with the player free to walk.
Each frontier tile is restored with --state-in, a direction is held until the tile changes, and the
new (scene, tile) is kept once. The player object is the one the tile-event lookup 06056DF0 is
called with (SF3_CALL_TRACE, caller 06056C1C passes it in r3); its tile is memory_map.player_tile.
A scene change is a goal: its picture and a state in the new scene are kept. OUT/result.json."""
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
LOOKUP_CALLER = 0x06056C20
SCENE_FID = memory_map.SC1_SCENES['fid_loaded']


def u32(s, a):
    return int.from_bytes(s.read(a, 4), 'big')


def u16(s, a):
    return int.from_bytes(s.read(a, 2), 'big')


def hold(s, b, n, rest):
    s.pad((b,) if b else ())
    for _ in range(n):
        s.step()
    s.pad(())
    for _ in range(rest):
        s.step()


def player_obj(log, default):
    objs = []
    for line in open(log):
        if line.startswith('trace '):
            f = dict(kv.split('=') for kv in line.split()[2:])
            if int(f['pr'], 16) == LOOKUP_CALLER:
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
        with agent.start(a['saturn'], args, str(work / 'ours')) as r:
            s = diff.OurSide(r)
            state = u32(s, u32(s, a['state_ptr']))
            scene0 = u16(s, state + 16)
            hold(s, 'B', 6, 12)
            hold(s, d, 1, 14)
            obj = player_obj(work / 'ours' / 'log.txt', a['obj'])
            tile = lambda: memory_map.player_tile(u32(s, obj + 12), u32(s, obj + 20))
            at = tile()
            s.pad((d,))
            for _ in range(24):
                s.step()
                if tile() != at:
                    break
            s.pad(())
            for _ in range(90):
                s.step()
                if u16(s, state + 16) != scene0:
                    break
            res = dict(src=src, d=d, frm=at, obj=obj, scene0=scene0, state=None)
            if u16(s, state + 16) != scene0:
                for _ in range(500):
                    s.step()
                for _ in range(6):
                    hold(s, 'C', 6, 30)
                for _ in range(3):
                    hold(s, 'B', 6, 20)
                s.frame().save_png(str(out / f'goal-{u16(s, state + 16)}-{n}.png'))
                res['state'] = save_state(s, str(out / f'g{n}.state'))
            elif tile() != at:
                res['state'] = save_state(s, str(out / f's{n}.state'))
            res.update(scene=u16(s, state + 16), fid=u32(s, SCENE_FID), tile=tile())
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
    o = p.parse_args()
    os.environ['SF3_CALL_TRACE'] = '06056DF0'
    os.environ.setdefault('SF3_STATE_ID', 'sf3-town-bfs')  # must match the id START.state was saved with
    mm = memory_map.lookup(o.profile)
    target = [t for t in sweep.targets_from_saves([o.save], mm['scenario']) if t['id'].endswith(':' + o.record)][0]
    a = dict(saturn=o.saturn, cue=o.cue, out=o.out, obj=memory_map.SC1_PLAYER['obj'], state_ptr=0x0602AE64,
             record=dict(target['record'], name=f"SFORCE3{mm['scenario']}_01"))
    Path(o.out).mkdir(parents=True, exist_ok=True)
    seen, goals, frontier, count, used = set(), [], [o.state], itertools.count(), 0
    with ProcessPoolExecutor(o.jobs) as ex:
        while frontier and used < o.budget:
            jobs = [(a, src, d, next(count)) for src in frontier for d in DIRS]
            used += len(jobs)
            new = []
            for res in ex.map(expand, jobs):
                if 'error' in res:
                    print('error', res, flush=True)
                    continue
                key = (res['scene'], tuple(res['tile']))
                fresh = key not in seen
                seen.add(key)
                if res['scene'] != res['scene0'] and fresh:
                    goals.append(res)
                    print('goal', res, flush=True)
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
    json.dump(dict(tiles=sorted(map(list, seen)), goals=goals), open(Path(o.out) / 'result.json', 'w'), indent=1, default=str)


if __name__ == '__main__':
    main()
