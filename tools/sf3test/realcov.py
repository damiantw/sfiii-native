"""A coverage measure over the code that is really there, not over every function the recompiler
emitted. Each build's gen/map/<module>.tsv lists the instructions it translated, by function; the
recompiler translates conservatively (every seed, call target and heuristic entry), so its function
count holds data decoded as code, overlay copies of the same code and small fragments. Here:

  - reachable: functions reached from the module's roots (its base, the profile's seeds, and words in
    the module's data that hold a function's address: pointer tables) through bsr targets and
    mov.l literals that hold a function's address (the jsr @rn idiom), across modules by address;
    functions that ran are reachable whatever the static walk says.
  - unique: one copy of a function whose instruction bytes and address equal another module's.
  - tiny: 4 instructions or fewer.
Coverage is then byte-weighted (2 bytes an instruction) per module over reachable unique code.
Reads the module images (disc files) at analysis time only; writes only counts and addresses."""
import hashlib
import re
from collections import defaultdict

HEADER = re.compile(r'^# (\S+): (\S+) at ([0-9A-Fa-f]{8}), (\d+) bytes')
TINY = 4


def parse_map(text):
    """gen/map/<module>.tsv -> dict(name, file, base, size, funcs={start: [insn addrs]})."""
    lines = text.splitlines()
    m = HEADER.match(lines[0])
    if not m:
        raise ValueError('not a module map')
    funcs = defaultdict(list)
    for line in lines[1:]:
        if line.startswith('#'):
            continue
        p = line.split('\t')
        if len(p) >= 3:
            funcs[int(p[1], 16)].append(int(p[0], 16))
    return dict(name=m.group(1), file=m.group(2), base=int(m.group(3), 16), size=int(m.group(4)),
                funcs={f: sorted(a) for f, a in funcs.items()})


def _w16(img, base, a):
    o = a - base
    return int.from_bytes(img[o:o + 2], 'big') if 0 <= o <= len(img) - 2 else None


def _w32(img, base, a):
    o = a - base
    return int.from_bytes(img[o:o + 4], 'big') if 0 <= o <= len(img) - 4 else None


def references(mod, img):
    """{function: set(target addresses)} from bsr and mov.l @(disp,PC) literals; and the set of
    32-bit words outside the translated instructions (data, pools included) as possible pointers."""
    base, refs, code = mod['base'], {}, set()
    for f, insns in mod['funcs'].items():
        out = set()
        for a in insns:
            code.add(a)
            op = _w16(img, base, a)
            if op is None:
                continue
            if op >> 12 == 0xB:                              # bsr disp12
                d = op & 0xFFF
                out.add(a + 4 + ((d - 0x1000) if d & 0x800 else d) * 2)
            elif op >> 12 == 0xD:                            # mov.l @(disp,PC),Rn
                v = _w32(img, base, (a & ~3) + 4 + (op & 0xFF) * 4)
                if v is not None:
                    out.add(v - 0x20000000 if v >> 24 == 0x26 else v)   # cache-through alias
        refs[f] = out
    data = set()
    for o in range(0, len(img) - 3, 4):
        a = base + o
        if a in code or a + 2 in code:
            continue
        data.add(int.from_bytes(img[o:o + 4], 'big'))
    return refs, data


def fn_hash(mod, img, f):
    h = hashlib.sha1()
    for a in mod['funcs'][f]:
        o = a - mod['base']
        h.update(img[o:o + 2])
    return h.hexdigest()


def analyze(mods, images, seeds, ran):
    """mods: [parse_map()], images: {name: bytes}, seeds: {name: [addr]}, ran: {(name, addr)}.
    Returns per-module rows and totals."""
    by_addr = defaultdict(list)                              # address -> [(module, function)]
    for m in mods:
        for f in m['funcs']:
            by_addr[f].append(m['name'])
    names = {m['name']: m for m in mods}
    edges, roots = {}, set()
    for m in mods:
        img = images.get(m['name'], b'')
        refs, data = references(m, img)
        own = set(m['funcs'])

        def resolve(v, m=m, own=own):
            if v in own:
                return [(m['name'], v)]
            return [(n, v) for n in by_addr.get(v, ())]
        for f, out in refs.items():
            edges[(m['name'], f)] = [t for v in out for t in resolve(v)]
        for v in [m['base'], *seeds.get(m['name'], ())]:
            roots.update(t for t in resolve(v) if t[0] == m['name'])
        roots.update((m['name'], v) for v in data if v in own)
    roots |= {r for r in ran if r[0] in names and r[1] in names[r[0]]['funcs']}
    seen, stack = set(), list(roots)
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(edges.get(n, ()))
    # one copy per (address, instruction bytes) across modules
    first = {}
    dup = set()
    for m in mods:
        img = images.get(m['name'], b'')
        for f in m['funcs']:
            k = (f, fn_hash(m, img, f))
            if k in first:
                dup.add((m['name'], f))
            else:
                first[k] = m['name']
    rows = []
    for m in mods:
        r = dict(module=m['name'], file=m['file'], base=m['base'], size=m['size'], functions=len(m['funcs']))
        cnt = {f: len(a) for f, a in m['funcs'].items()}
        key = lambda f: (m['name'], f)
        reach = [f for f in m['funcs'] if key(f) in seen]
        real = [f for f in reach if key(f) not in dup]
        r.update(insns=sum(cnt.values()), tiny=sum(1 for f in cnt if cnt[f] <= TINY),
                 unreachable=len(m['funcs']) - len(reach), duplicate=sum(1 for f in m['funcs'] if key(f) in dup),
                 real=len(real), real_bytes=2 * sum(cnt[f] for f in real),
                 ran=sum(1 for f in m['funcs'] if key(f) in ran),
                 ran_bytes=2 * sum(cnt[f] for f in real if key(f) in ran))
        r['pct'] = 100.0 * r['ran_bytes'] / r['real_bytes'] if r['real_bytes'] else 0.0
        rows.append(r)
    tot = {k: sum(r[k] for r in rows) for k in ('functions', 'insns', 'tiny', 'unreachable', 'duplicate', 'real',
                                               'real_bytes', 'ran', 'ran_bytes')}
    tot['pct'] = 100.0 * tot['ran_bytes'] / tot['real_bytes'] if tot['real_bytes'] else 0.0
    tot['modules_run'] = sum(1 for r in rows if r['ran'])
    tot['modules'] = len(rows)
    return rows, tot


def never_run(rows, min_bytes=4096):
    return sorted((r for r in rows if not r['ran'] and r['real_bytes'] >= min_bytes), key=lambda r: -r['real_bytes'])


def ran_set(texts):
    """--coverage files' text -> {(module, address)} of the functions that ran in any of them."""
    out = set()
    for text in texts:
        for line in text.splitlines():
            p = line.split()
            if len(p) == 4 and p[3] == '1':
                out.add((p[0], int(p[1], 16)))
    return out
