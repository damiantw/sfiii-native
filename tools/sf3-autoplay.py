"""SF3 autoplay sweep: each target (a save record) is loaded through the Continue menu over the
port's --agent socket, then played by the closed-loop driver in sf3test/autoplay.py. Outputs stay
outside the repository, as the sweep's do (coverage.tsv, progress.tsv, run.log, shots,
input.txt with the whole run's presses, result.json with the autoplay script's hash).

  python tools/sf3-autoplay.py --saturn BUILD/saturn --cue DISC.cue --profile P --out DIR \
      --saves A.bin ... [--every 3] [--play 6000] [--jobs 3] [--seed 1]"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
for p in (ROOT / '.local' / 'saturn-recomp' / 'src',):
    if p.exists():
        sys.path.insert(0, str(p))
from sf3test import autoplay, diff, frames, memory_map, sweep  # noqa: E402

LOAD_LIMIT = 6500


def run_one(saturn, cue, profile, target, work, play, seed, shots_every=600):
    from saturnrecomp import agent
    mm = memory_map.lookup(profile)
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    for p in list(work.glob('shot-*.png')) + [work / 'progress.tsv', work / 'backup.bin.cartridge']:
        if p.exists():
            p.unlink()
    (work / 'backup.bin').write_bytes(sweep.backup_for(target, mm['scenario']))
    total = LOAD_LIMIT + play
    shots = list(range(shots_every, total + 1, shots_every))
    args = ['--headless', '--cue', str(cue), '--save', str(work / 'backup.bin'), '--settings', '-',
            '--vblanks', str(total), '--shot', ','.join(map(str, shots)), '--log', str(work / 'run.log'),
            '--coverage', str(work / 'coverage.tsv'), '--checkpoint', '30', '--progress', str(work / 'progress.tsv'),
            '--progress-keep', f"{mm['map_id']:08X}:1,{mm['battle_id']:08X}:1"]
    os.environ.setdefault('SDL_VIDEO_DRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIO_DRIVER', 'dummy')
    t0, rc, load, res = time.time(), 'ok', None, None
    r = agent.start(str(saturn), args, str(work))
    r._sock.settimeout(90)                     # a hang inside a step: no reply for 90 s
    try:
        side = diff.OurSide(r)
        load = diff.drive_to_load(side, mm['tick'], [], LOAD_LIMIT, start_frames=(1100, 1308))
        if load is None:
            rc = 'no-load'
        else:
            res = autoplay.play(side, profile, total - side.frames - 2, seed, reload=lambda sd: autoplay.reload_menu(
                sd, profile, max(1, min(LOAD_LIMIT, total - 2 - sd.frames))))
            while True:
                side.step()
    except (agent.RunEnded, agent.AgentError, BrokenPipeError, ConnectionResetError):
        pass
    except socket.timeout:
        rc = 'timeout'
        r._proc.kill()
    finally:
        (work / 'input.txt').write_text(','.join(r.presses) + '\n')
        try:
            r.close()
        except Exception:
            r._proc.kill()
    log = ''
    for name in ('run.log', 'log.txt'):
        if (work / name).exists():
            log += (work / name).read_text(errors='replace')
    prog = sweep.parse_progress((work / 'progress.tsv').read_text()) if (work / 'progress.tsv').exists() else []
    stats = [(v, frames.stats((work / f'shot-{v}.png').read_bytes())) for v in shots if (work / f'shot-{v}.png').exists()]
    result = sweep.analyze(log, prog, stats, total, (target['map'], target['battle']), loaded_after=load or sweep.LOAD_END)
    if rc == 'timeout':
        result['status'] = 'hang'
    elif rc == 'no-load' and result['status'] == 'ok':
        result['status'] = 'no-load'
    result.update(id=target['id'], load=load, seconds=round(time.time() - t0, 1), work=str(work), seed=seed,
                  autoplay_sha1=res and res['sha1'], autoplay_events=res and res['events'][:100],
                  autoplay_presses=res and len(res['presses']), resets=res and res['resets'], maps_seen=sorted({e[1] for e in (res or {}).get('events', []) if e[1] >= 0}),
                  battles_seen=sorted({e[2] for e in (res or {}).get('events', []) if e[2] > 0}))
    if res:
        (work / 'autoplay.txt').write_text(autoplay.script_text(res['presses']) + '\n')
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--saturn', required=True)
    ap.add_argument('--cue', required=True)
    ap.add_argument('--profile', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--saves', nargs='+', required=True)
    ap.add_argument('--every', type=int, default=1, help='take every Nth record')
    ap.add_argument('--play', type=int, default=6000, help='frames of autoplay after the load')
    ap.add_argument('--jobs', type=int, default=3)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--only', help='comma-separated target ids')
    a = ap.parse_args()
    for p in [a.cue, *a.saves, a.out]:
        sweep.external(p, ROOT)
    mm = memory_map.lookup(a.profile)
    targets = sweep.targets_from_saves(a.saves, mm['scenario'])[::a.every]
    if a.only:
        targets = [t for t in targets if t['id'] in set(a.only.split(','))]
    out = Path(a.out)

    def one(i_t):
        i, t = i_t
        r = run_one(a.saturn, a.cue, a.profile, t, out / t['id'].replace(':', '_'), a.play, a.seed * 1000 + i)
        print(f"{t['id']:40s} {r['status']:8s} maps={' '.join(f'{m:02X}' for m in r['maps'][:8])} "
              f"battles={' '.join(f'{b:02X}' for b in r['battles'][:4])} ap={r['autoplay_sha1']} "
              f"{r['seconds']}s {'; '.join(r['fatal'][:1])}", flush=True)
        return r
    with ThreadPoolExecutor(a.jobs) as ex:
        results = list(ex.map(one, enumerate(targets)))
    (out / 'report.json').write_text(json.dumps(results, indent=2) + '\n')
    counts = {}
    for r in results:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    print('summary', counts)


if __name__ == '__main__':
    main()
