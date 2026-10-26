"""SF3 basic-block coverage report (bring-your-own-build; outputs stay outside the repository).

A block coverage build (tools/generate.py --block-coverage) run with `saturn --coverage FILE.tsv` also
writes FILE.blocks.tsv: one row a recompiled block, "MODULE CRC BLOCK FUNCTION INSNS MASTER SLAVE",
MASTER/SLAVE 1 once that SH-2 entered the block. Modules are the build's programs (BOOT and every
overlay/scene file), identified at run time by the CRC32 of their whole loaded image, so a hit belongs
to the overlay that was really resident, not just to an address.

  python tools/sf3-block-coverage.py scenario --name sc1 --runs title='RUNS/title-*' story='RUNS/story-*' \
      [--build BUILD_ROOT --profile profiles/P.json] [--top 40] --out sc1.json
  python tools/sf3-block-coverage.py summary sc1.json sc2v2.json ...

`scenario` unions every *.blocks.tsv (or .blocks.tsv.gz) under the run directories (TAG=GLOB groups them, for the
per-group columns), and reports blocks, instructions and functions hit out of all recompiled, per
module with an area label, and the largest never-executed functions. With --build (gen/map/*.tsv and
stage/extract/<module files>) and --profile it also restricts to real code as tools/sf3-coverage.py
does (reachable, de-duplicated across overlays, more than 4 instructions; sf3test/realcov.py); the
module images are read at analysis time only. The JSON holds names, addresses and counts, no image
bytes, but it describes the user's disc: keep it outside the repository."""
import argparse
import glob
import gzip
import json
from collections import defaultdict
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

# Area labels by module name. Evidence for the X0nn ones is in docs/testing-plan.md and the project
# notes (loader call sites, strings, the scenes that load them); anything else falls to a name pattern.
NAMED = {
    'BOOT': 'core (1ST.BIN: boot, kernel, CD loader, shared engine)',
    'X002': 'scene loader', 'X003': 'town/field loop', 'X008': 'scene/event objects',
    'X009': 'title', 'X014': 'battle: spell/special effect loader',
    'X017': 'town talk/dialog', 'X021': 'town overlay init', 'X023': 'menus: shop (buy/sell/repair/deals)',
    'X024': 'menus: HQ (depot)', 'X026': 'menus: HQ depot / sprite+palette', 'X033': 'church (save, promotion, revive)',
    'X046': 'debug: effect viewer', 'X049': 'cutscene: movie/credits player (Cinepak)',
    'X1OPMOV': 'cutscene: opening movie',
}
PATTERNS = [
    (r'^X1BTL', 'battle: map script'), (r'SHOP|_SHP', 'menus: shop'), (r'CHUR|_C$', 'church'),
    (r'BAR', 'tavern/bar'), (r'END', 'cutscene: ending'), (r'OPMOV|MOV', 'cutscene: movie'),
    (r'^X3', 'battle: spell/effect animation'), (r'^EFFECT', 'battle: spell/effect animation'),
    (r'^X1', 'scene: town/event script'), (r'^X0', 'system module (unlabelled)'),
]


def label(name):
    if name in NAMED:
        return NAMED[name]
    for pat, lab in PATTERNS:
        if re.search(pat, name):
            return lab
    return 'other'


def read_blocks(path, table, hits, tag, tag_hits):
    """Adds one .blocks.tsv to table {(mod, crc, block): (func, insns)} and hits {key: [master, slave]}."""
    raw = Path(path).read_bytes()
    if str(path).endswith('.gz'):
        raw = gzip.decompress(raw)
    for line in raw.decode().splitlines():
        if line.startswith('#'):
            continue
        p = line.split()
        if len(p) != 7:
            continue
        key = (p[0], p[1], int(p[2], 16))
        table[key] = (int(p[3], 16), int(p[4]))
        h = hits.setdefault(key, [0, 0])
        if p[5] == '1':
            h[0] = 1
        if p[6] == '1':
            h[1] = 1
        if p[5] == '1' or p[6] == '1':
            tag_hits[tag].add(key)


def real_functions(build, profile):
    """{(module, function)} of real code (sf3test/realcov.py), or None without a build."""
    if not build:
        return None
    from sf3test import realcov
    b = Path(build)
    mods = [realcov.parse_map(p.read_text()) for p in sorted((b / 'gen' / 'map').glob('*.tsv'))]
    if not mods:
        mods = [realcov.parse_map(p.read_text()) for p in sorted((b / 'map').glob('*.tsv'))]
    images = {}
    for m in mods:
        p = b / 'stage' / 'extract' / m['file']
        images[m['name']] = p.read_bytes() if p.exists() else b''
    prof = json.loads(Path(profile).read_text()) if profile else {}
    seeds = {m['name']: [int(s, 16) for s in m.get('seeds', [])] for m in prof.get('modules', [])}
    # realcov.analyze() keeps these sets internal; the same predicate, per function
    by_addr = defaultdict(list)
    for m in mods:
        for f in m['funcs']:
            by_addr[f].append(m['name'])
    edges, roots = {}, set()
    for m in mods:
        img = images.get(m['name'], b'')
        refs, data = realcov.references(m, img)
        own = set(m['funcs'])
        res = lambda v, m=m, own=own: [(m['name'], v)] if v in own else [(n, v) for n in by_addr.get(v, ())]
        for f, out in refs.items():
            edges[(m['name'], f)] = [t for v in out for t in res(v)]
        for v in [m['base'], *seeds.get(m['name'], ())]:
            roots.update(t for t in res(v) if t[0] == m['name'])
        roots.update((m['name'], v) for v in data if v in own)
    seen, stack = set(), list(roots)
    while stack:
        n = stack.pop()
        if n not in seen:
            seen.add(n)
            stack.extend(edges.get(n, ()))
    first, real = {}, set()
    for m in mods:
        img = images.get(m['name'], b'')
        for f, insns in m['funcs'].items():
            k = (f, realcov.fn_hash(m, img, f))
            if k in first:
                continue
            first[k] = m['name']
            if (m['name'], f) in seen and len(insns) > realcov.TINY:
                real.add((m['name'], f))
    return real


def scenario(a):
    table, hits, tag_hits, nruns = {}, {}, defaultdict(set), defaultdict(int)
    for spec in a.runs:
        tag, _, pat = spec.rpartition('=')
        tag = tag or 'runs'
        for d in sorted(glob.glob(pat)):
            files = ([Path(d)] if d.endswith(('.blocks.tsv', '.blocks.tsv.gz')) else
                     sorted(list(Path(d).rglob('*.blocks.tsv')) + list(Path(d).rglob('*.blocks.tsv.gz'))))
            for f in files:
                read_blocks(f, table, hits, tag, tag_hits)
                nruns[tag] += 1
    if not table:
        raise SystemExit('no .blocks.tsv found (is it a block coverage build, run with --coverage?)')
    real = real_functions(a.build, a.profile)
    if real is not None:
        real_names = {m for m, _ in real}
        # a ran function is real whatever the static walk says (realcov's rule)
        real |= {(k[0], table[k][0]) for k, h in hits.items() if any(h) and k[0] in real_names}
    mods = defaultdict(lambda: dict(blocks=0, hit=0, master=0, slave=0, insns=0, insns_hit=0, funcs=set(), funcs_hit=set(),
                                    real_blocks=0, real_hit=0, real_insns=0, real_insns_hit=0, crc=None))
    fsize, fhit = defaultdict(int), set()
    for key, (func, n) in table.items():
        m = mods[key[0]]
        m['crc'] = key[1]
        h = hits.get(key, [0, 0])
        hit = bool(h[0] or h[1])
        m['blocks'] += 1; m['insns'] += n; m['funcs'].add(func)
        m['hit'] += hit; m['master'] += bool(h[0]); m['slave'] += bool(h[1]); m['insns_hit'] += n * hit
        fsize[(key[0], func)] += n
        if hit:
            m['funcs_hit'].add(func); fhit.add((key[0], func))
        if real is None or (key[0], func) in real:
            m['real_blocks'] += 1; m['real_hit'] += hit; m['real_insns'] += n; m['real_insns_hit'] += n * hit
    rows = []
    for name, m in sorted(mods.items()):
        rows.append(dict(module=name, crc=m['crc'], label=label(name), blocks=m['blocks'], hit=m['hit'], master=m['master'],
                         slave=m['slave'], insns=m['insns'], insns_hit=m['insns_hit'], functions=len(m['funcs']),
                         functions_hit=len(m['funcs_hit']), real_blocks=m['real_blocks'], real_hit=m['real_hit'],
                         real_insns=m['real_insns'], real_insns_hit=m['real_insns_hit']))
    tot = {k: sum(r[k] for r in rows) for k in ('blocks', 'hit', 'master', 'slave', 'insns', 'insns_hit', 'functions',
                                               'functions_hit', 'real_blocks', 'real_hit', 'real_insns', 'real_insns_hit')}
    tot['modules'] = len(rows)
    tot['modules_hit'] = sum(1 for r in rows if r['hit'])
    tot['real'] = real is not None
    keep = (lambda k: k in real) if real is not None else (lambda k: True)
    loaded = {r['module'] for r in rows if r['hit']}
    cold = sorted(((k, n) for k, n in fsize.items() if k not in fhit and keep(k)), key=lambda x: -x[1])
    fn_cold = lambda only: [dict(module=k[0], function='%08X' % k[1], insns=n, label=label(k[0]),
                                  module_ran=k[0] in loaded) for k, n in cold if only(k)][:a.top]
    areas = defaultdict(lambda: [0, 0])
    for r in rows:
        areas[r['label']][0] += r['real_insns']; areas[r['label']][1] += r['real_insns_hit']
    groups = {t: dict(runs=nruns[t], blocks=len(s),
                      only=len(s - set().union(*[v for u, v in tag_hits.items() if u != t]))) for t, s in tag_hits.items()}
    out = dict(name=a.name, runs=dict(nruns), total=tot, groups=groups,
               areas={k: dict(insns=v[0], hit=v[1]) for k, v in sorted(areas.items(), key=lambda x: -x[1][0])},
               modules=rows, cold_in_ran_modules=fn_cold(lambda k: k[0] in loaded),
               cold_modules=sorted(({'module': r['module'], 'label': r['label'], 'insns': r['real_insns'],
                                     'functions': r['functions']} for r in rows if not r['hit']), key=lambda r: -r['insns'])[:a.top])
    pct = lambda x, y: 100.0 * x / y if y else 0.0
    print(f"{a.name}: {sum(nruns.values())} runs ({', '.join(f'{t} {n}' for t, n in nruns.items())})")
    print(f"  blocks {tot['hit']}/{tot['blocks']} ({pct(tot['hit'], tot['blocks']):.2f}%), master {tot['master']}, "
          f"slave {tot['slave']}; instructions {pct(tot['insns_hit'], tot['insns']):.2f}%; functions "
          f"{tot['functions_hit']}/{tot['functions']} ({pct(tot['functions_hit'], tot['functions']):.2f}%); modules {tot['modules_hit']}/{tot['modules']}")
    if real is not None:
        print(f"  real code: blocks {tot['real_hit']}/{tot['real_blocks']} ({pct(tot['real_hit'], tot['real_blocks']):.2f}%), "
              f"instructions {tot['real_insns_hit']}/{tot['real_insns']} ({pct(tot['real_insns_hit'], tot['real_insns']):.2f}%)")
    for t, g in groups.items():
        print(f"  group {t}: {g['runs']} runs, {g['blocks']} blocks, {g['only']} only here")
    print('  areas (real instructions hit/total):')
    for k, v in out['areas'].items():
        print(f"    {k:45s} {v['hit']:7d}/{v['insns']:7d} {pct(v['hit'], v['insns']):6.2f}%")
    print('  largest never-run modules:')
    for r in out['cold_modules'][:15]:
        print(f"    {r['module']:10s} {r['insns']:6d} insns  {r['label']}")
    print('  largest never-run functions in modules that ran:')
    for r in out['cold_in_ran_modules'][:15]:
        print(f"    {r['module']:10s} {r['function']} {r['insns']:5d} insns  {r['label']}")
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1) + '\n')


def summary(a):
    pct = lambda x, y: 100.0 * x / y if y else 0.0
    print(f"{'scenario':10s} {'runs':>5s} {'blocks hit/total':>20s} {'%':>6s} {'fns hit/total':>16s} {'%':>6s} "
          f"{'real insns %':>12s} {'modules':>9s}")
    for p in a.reports:
        r = json.loads(Path(p).read_text())
        t = r['total']
        print(f"{r['name']:10s} {sum(r['runs'].values()):5d} {t['hit']:9d}/{t['blocks']:<10d} {pct(t['hit'], t['blocks']):6.2f} "
              f"{t['functions_hit']:7d}/{t['functions']:<8d} {pct(t['functions_hit'], t['functions']):6.2f} "
              f"{pct(t['real_insns_hit'], t['real_insns']):12.2f} {t['modules_hit']:4d}/{t['modules']:<4d}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('scenario')
    s.add_argument('--name', required=True)
    s.add_argument('--runs', nargs='+', required=True, help='[TAG=]GLOB of run directories or .blocks.tsv files')
    s.add_argument('--build', help='build root (gen/map, stage/extract) for the real-code restriction')
    s.add_argument('--profile')
    s.add_argument('--top', type=int, default=40)
    s.add_argument('--out')
    m = sub.add_parser('summary')
    m.add_argument('reports', nargs='+')
    a = ap.parse_args()
    if getattr(a, 'out', None) and (ROOT in Path(a.out).resolve().parents):
        raise SystemExit('reports describe the disc: write them outside the repository')
    (scenario if a.cmd == 'scenario' else summary)(a)


if __name__ == '__main__':
    main()
