"""SF3 scene/battle reachability sweep (bring-your-own-disc; outputs stay outside the repository).

  python tools/sf3-sweep.py --saturn BUILD/saturn --cue DISC.cue --profile scenario1-usa-v25_1 \
      --out /private/sweep/sc1 --saves A.bin B.bkr ... [--maps 0-255 --map-base SAVE:NN] --jobs 6

Each target is one save record (or a church save with its map id edited), loaded through the
title's Continue menu, then driven by seeded button mashing. Results: OUT/report.json, matrix.md."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from sf3test import memory_map, saves, sweep  # noqa: E402


def ranges(spec):
    out = []
    for part in spec.split(','):
        lo, _, hi = part.partition('-')
        out += list(range(int(lo, 0), int(hi or lo, 0) + 1))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--saturn', required=True)
    ap.add_argument('--cue', required=True)
    ap.add_argument('--profile', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--saves', nargs='*', default=[])
    ap.add_argument('--maps', help='map ids to visit by editing --map-base, e.g. 0-255')
    ap.add_argument('--map-base', help='FILE:NN, the save record whose map id is edited')
    ap.add_argument('--vblanks', type=int, default=8000)
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--only', help='comma-separated target ids')
    ap.add_argument('--seed', type=int, default=1)
    a = ap.parse_args()
    out = sweep.external(a.out, ROOT)
    for p in [a.cue, *a.saves]:
        sweep.external(p, ROOT)
    mm = memory_map.lookup(a.profile)
    sc = mm['scenario']
    targets = sweep.targets_from_saves(a.saves, sc)
    if a.maps:
        path, _, nn = a.map_base.rpartition(':')
        base = [r for r in saves.load_any(Path(path).read_bytes()) if r['name'].endswith('_' + nn)][0]
        bad = memory_map.INVALID_MAPS.get(sc, {})
        for m in sorted(set(ranges(a.maps)) & set(bad)):
            print(f'map:{m:02X} skipped: invalid ({bad[m]})')
        targets += sweep.targets_from_maps(base, [m for m in ranges(a.maps) if m not in bad])
    if a.only:
        keep = set(a.only.split(','))
        targets = [t for t in targets if t['id'] in keep]
    out.mkdir(parents=True, exist_ok=True)

    def one(i_t):
        i, t = i_t
        work = out / 'runs' / t['id'].replace(':', '_')
        r = sweep.run_target(a.saturn, a.cue, sweep.backup_for(t, sc), work, a.vblanks, mm, a.seed * 1000 + i,
                             expect=(t['map'], t['battle']))
        r.update(id=t['id'], kind=t['kind'], map=t['map'], battle=t['battle'])
        print(f"{t['id']:40s} {r['status']:8s} maps={' '.join(f'{m:02X}' for m in r['maps'][:6])} "
              f"{(r['fatal'] or [''])[0][:90]}", flush=True)
        return r

    with ThreadPoolExecutor(a.jobs) as ex:
        results = list(ex.map(one, enumerate(targets)))
    report = dict(profile=mm['profile'], cue=str(a.cue), vblanks=a.vblanks, seed=a.seed, results=results,
                  coverage=sweep.coverage_union(
                      (Path(r['work']) / 'coverage.tsv').read_text() for r in results
                      if (Path(r['work']) / 'coverage.tsv').exists()))
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'matrix.md').write_text(sweep.matrix(report))
    counts = {s: sum(1 for r in results if r['status'] == s) for s in sweep.STATUSES}
    print(json.dumps(counts))


if __name__ == '__main__':
    main()
