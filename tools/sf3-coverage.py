"""SF3 coverage over real code (bring-your-own-build; outputs stay outside the repository).

  python tools/sf3-coverage.py --build BUILD_ROOT --profile profiles/P.json --runs 'SWEEP/*/runs/*' ... \
      [--out report.json] [--top 25] [--min-bytes 4096]

BUILD_ROOT is the profile build's root (gen/map/*.tsv, stage/extract/<module files>). Prints the
emitted-function coverage beside the byte-weighted coverage of reachable, unique code (see
sf3test/realcov.py), per module and in total, and the large modules that never ran."""
import argparse
import glob
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from sf3test import realcov  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', required=True)
    ap.add_argument('--profile', required=True)
    ap.add_argument('--runs', nargs='+', required=True, help='run directories (globs) holding coverage.tsv')
    ap.add_argument('--out')
    ap.add_argument('--top', type=int, default=25)
    ap.add_argument('--min-bytes', type=int, default=4096)
    a = ap.parse_args()
    b = Path(a.build)
    mods = [realcov.parse_map(p.read_text()) for p in sorted((b / 'gen' / 'map').glob('*.tsv'))]
    images = {}
    for m in mods:
        p = b / 'stage' / 'extract' / m['file']
        images[m['name']] = p.read_bytes() if p.exists() else b''
    prof = json.loads(Path(a.profile).read_text())
    seeds = {m['name']: [int(s, 16) for s in m.get('seeds', [])] for m in prof.get('modules', [])}
    files = [f for g in a.runs for d in glob.glob(g) for f in [Path(d) / 'coverage.tsv'] if f.exists()]
    ran = realcov.ran_set(f.read_text() for f in files)
    rows_cov = [l.split() for l in files[0].read_text().splitlines() if len(l.split()) == 4] if files else []
    stubs = sum(1 for p in rows_cov if p[2] == '0')
    print(f"coverage.tsv rows {len(rows_cov)}: {stubs} are entry stubs with no instructions of their own "
          f"(mid-function and resume entries), {len(rows_cov) - stubs} are function bodies")
    rows, tot = realcov.analyze(mods, images, seeds, ran)
    print(f"{len(files)} runs; emitted functions {tot['functions']}, ran {tot['ran']} "
          f"({100 * tot['ran'] / max(tot['functions'], 1):.2f}%)")
    print(f"  tiny (<= {realcov.TINY} insns) {tot['tiny']}, statically unreachable {tot['unreachable']}, "
          f"overlay duplicates {tot['duplicate']}; real {tot['real']} functions, {tot['real_bytes']} code bytes")
    print(f"  byte-weighted coverage of real code: {tot['pct']:.2f}%; modules run {tot['modules_run']}/{tot['modules']}")
    print('  never-run modules by real code bytes:')
    for r in realcov.never_run(rows, a.min_bytes)[:a.top]:
        print(f"    {r['module']:10s} {r['file']:14s} {r['base']:08X} real {r['real']:5d} fns {r['real_bytes']:7d} B")
    if a.out:
        Path(a.out).write_text(json.dumps(dict(runs=len(files), coverage_rows=len(rows_cov), entry_stubs=stubs, total=tot, modules=rows), indent=1) + '\n')


if __name__ == '__main__':
    main()
