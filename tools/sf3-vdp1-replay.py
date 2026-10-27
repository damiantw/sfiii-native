#!/usr/bin/env python3
"""VDP1 replay: our rasterizer against a reference framebuffer for the same VRAM, with no game timing.

  snap    drives the reference core (a libretro build, used as a black box) from boot through the
          Continue menu to a save's load with no input, and at each requested frame keeps what its
          own save-state interface reports for VDP1: VRAM, the draw/erase registers and the draw
          framebuffer, paired two ways (a state is taken at one point of the frame, the draw runs
          at another): 'same' is the frame's end VRAM with that frame's draw, 'next' the VRAM
          just before the next frame change with the draw after it. One .npz a frame, outside the
          repository.
  replay  feeds each snapshot's VRAM and registers to runtime/tests' vdp1_replay (our vdp1.cpp,
          nothing else), and compares its framebuffer with the reference's draw framebuffer dot for
          dot, for both pairings ('all' is the better one, the other pairing being timing):
          exact-match over 320x224 and inside named regions, the commands owning most of the
          mismatches, and optionally a picture (reference | ours | mismatches in red).
  replay2 the same for the whole picture: snap also keeps, one frame either side of each snapshot,
          VDP2's VRAM, CRAM and registers, both VDP1 framebuffers with the display/draw registers,
          and the core's output picture (<snap>-vdp2.npz). runtime/tests' vdp2_replay loads VDP2
          state and the shown framebuffer (the one not being drawn) into our VDP2 compositor and
          composes one frame, compared with the core's picture (320x224, centred in its output).
          VDP2 registers can change during a frame and our compositor uses one set, so the four
          before/after pairings are tried and the best counts ('all'; '5bit' compares 5-bit
          channels).

  sf3-vdp1-replay.py snap --cue sc1.cue --profile scenario1-v25_1 --save SFORCE31_01.BUP \\
      --record 01 --frames 400,1000 --pre 3000 --out /tmp/snaps/sc1-church
  sf3-vdp1-replay.py replay --bin build/runtime-tests/vdp1_replay /tmp/snaps/sc1-church/load1000.npz
  sf3-vdp1-replay.py replay2 --bin build/runtime-tests/vdp2_replay /tmp/snaps/sc1-church/load1000-vdp2.npz

This replaces the round-1 scripts that compared whole frames from two separately timed runs.

The state is read by the section/entry names in the save-state stream (a container of named blobs):
section VDP1, entries VRAM, &FB[0][0], FBDrawWhich, VDP1_TVMR, VDP1_FBCR, EWDR, EWLR, EWRR, with
16-bit words in host (little-endian) order; section VDP2, entries VRAM, CRAM, RawRegs.
"""
import argparse, ctypes, json, os, shutil, struct, subprocess, sys, tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REGS = ('VDP1_TVMR', 'VDP1_FBCR', 'EWDR', 'EWLR', 'EWRR')
W, H = 320, 224


def state_sections(d, want=('VDP1',)):
    """{section: {entry: bytes}} of a save-state stream (32-byte header; per section a 32-byte name
    and u32 size; per entry a length-prefixed name, u32 size, data)."""
    out, p = {}, 32
    while p + 36 <= len(d):
        name = d[p:p + 32].rstrip(b'\0').decode('latin1')
        size = struct.unpack('<I', d[p + 32:p + 36])[0]
        if not name:
            break
        q, end = p + 36, p + 36 + size
        if name in want:
            ent = {}
            while q < end:
                n = d[q]
                key = d[q + 1:q + 1 + n].decode('latin1')
                es = struct.unpack('<I', d[q + 1 + n:q + 5 + n])[0]
                ent[key] = d[q + 5 + n:q + 5 + n + es]
                q += 5 + n + es
            out[name] = ent
        p = end
    return out


def core_state(core, want=('VDP1',)):
    """Sections of the core's save state, as {section: {entry: bytes}}."""
    lib = core.lib
    lib.retro_serialize_size.restype = ctypes.c_size_t
    lib.retro_serialize.restype = ctypes.c_bool
    n = lib.retro_serialize_size()
    buf = (ctypes.c_ubyte * n)()
    if not lib.retro_serialize(buf, n):
        raise SystemExit('serialize failed')
    return state_sections(bytes(buf), want)


def vdp1_state(core):
    return core_state(core)['VDP1']


def core_picture(core):
    """The core's last picture, (h, w, 3) uint8 (XRGB8888 or RGB565/0RGB1555 decoded)."""
    raw, w, h, pitch, fmt = core._raw
    a = np.frombuffer(raw, np.uint8)[:pitch * h].reshape(h, pitch)
    if fmt == 1:
        px = a[:, :4 * w].reshape(h, w, 4)
        return np.ascontiguousarray(px[:, :, 2::-1])
    p = a[:, :2 * w].copy().view('<u2').astype(np.uint32)
    if fmt == 2:
        r, g, b = (p >> 11) << 3, ((p >> 5) & 63) << 2, (p & 31) << 3
        r, g, b = r | r >> 5, g | g >> 6, b | b >> 5
    else:
        r, g, b = ((p >> 10) & 31) << 3, ((p >> 5) & 31) << 3, (p & 31) << 3
        r, g, b = r | r >> 5, g | g >> 5, b | b >> 5
    return np.stack([r, g, b], -1).astype(np.uint8)


def keep_vdp2(side, path):
    """What VDP2 shows for the next frame: VDP2 VRAM, colour RAM and registers, and VDP1's two
    framebuffers and display registers, from the states before and after the frame, with the
    picture the core outputs for it."""
    def part(st):
        v1, v2 = st['VDP1'], st['VDP2']
        return dict(vram=np.frombuffer(v2['VRAM'], '<u2'), cram=np.frombuffer(v2['CRAM'], '<u2'),
                    regs=np.frombuffer(v2['RawRegs'], '<u2'),
                    fb=np.frombuffer(v1['&FB[0][0]'], '<u2').reshape(2, 256, 512),
                    v1=np.array([v1['FBDrawWhich'][0], v1['VDP1_TVMR'][0], v1['VDP1_FBCR'][0]]))
    a = part(core_state(side.c, ('VDP1', 'VDP2')))
    side.step()
    b = part(core_state(side.c, ('VDP1', 'VDP2')))
    np.savez_compressed(path, pic=core_picture(side.c),
                        **{k: np.stack([a[k], b[k]]) for k in a})


def keep(side, path, limit=4):
    """Two pairings of VRAM with the framebuffer drawn from it, since a save state is taken at one
    point of the frame and the draw runs at another:
      same  VRAM and registers at the end of this frame, with this frame's draw framebuffer;
      next  VRAM and registers at the end of the last frame before the next frame change (a game
            drawing at 30 Hz swaps every other frame), with the framebuffer drawn after it, taken
            at the last frame before the change after that: the reference's draw can take more
            than one frame, so the framebuffer right after the first change can be part-drawn."""
    def part(st, fb_of):
        fb = np.frombuffer(fb_of['&FB[0][0]'], '<u2').reshape(2, 256, 512)[fb_of['FBDrawWhich'][0] & 1]
        return (np.frombuffer(st['VRAM'], '<u2').astype('>u2'),
                np.array([int.from_bytes(st[k], 'little') for k in REGS]), fb)

    def to_change(prev):
        for _ in range(limit):
            side.step()
            cur = vdp1_state(side.c)
            if cur['FBDrawWhich'] != prev['FBDrawWhich']:
                return prev, cur
            prev = cur
        return prev, None
    first = vdp1_state(side.c)
    prev, cur = to_change(first)
    if cur is None:
        raise SystemExit('no frame change')
    drawn, after = to_change(cur)
    pairs = [part(first, first), part(prev, drawn if after is not None else cur)]
    np.savez_compressed(path, vram=np.stack([p[0] for p in pairs]), regs=np.stack([p[1] for p in pairs]),
                        ref=np.stack([p[2] for p in pairs]))


def snap(a):
    sys.path.insert(0, str(Path(a.runtime) / 'src'))
    from sf3test import diff, memory_map, saves
    from saturnrecomp import reference as R
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='vdp1snap-'))
    try:
        (work / 'core-save').mkdir(); (work / 'core-system').mkdir()
        recs = [r for r in saves.load_any(Path(a.save).read_bytes()) if r['name'].endswith('_' + a.record)]
        if not recs:
            raise SystemExit(f'no record _{a.record} in {a.save}')
        diff.prepare_beetle(work, a.cue, recs[0], a.bios)
        core = R.Core(a.core, str(work / 'core-system'), a.cue, options=dict(R.OPTIONS, **diff.BEETLE_OPTIONS),
                      save_dir=str(work / 'core-save'))
        side = diff.CoreSide(core)
        pre = set(int(x) for x in a.pre.split(',') if x)
        step = side.step

        def step_keeping():
            step()
            if side.frames + 1 in pre:
                side.step = step
                f = side.frames + 1
                keep_vdp2(side, out / f'pre{f}-vdp2.npz')
                keep(side, out / f'pre{f}.npz')
                side.step = step_keeping
        side.step = step_keeping
        load = diff.drive_to_load(side, memory_map.lookup(a.profile)['tick'], [], 20000, alternate=True)
        side.step = step
        if load is None:
            raise SystemExit('no load')
        side.pad([])
        frames = sorted(int(x) for x in a.frames.split(',') if x)
        start = side.frames
        for f in frames:
            while side.frames - start < f - 1:
                side.step()
            keep_vdp2(side, out / f'load{f}-vdp2.npz')
            keep(side, out / f'load{f}.npz')
        print(json.dumps({'load': load, 'kept': frames, 'pre': sorted(pre)}))
    finally:
        shutil.rmtree(work, ignore_errors=True)


PAIRS = ('same', 'next')


def replay_one(binary, s, tmp):
    """Our framebuffer from one pairing's VRAM and registers."""
    vram = tmp / 'vram.bin'; ours = tmp / 'ours.bin'
    vram.write_bytes(s['vram'].astype('>u2').tobytes())
    subprocess.run([binary, str(vram), str(ours)] + ['%x' % r for r in s['regs']], check=True)
    return np.fromfile(ours, '>u2').reshape(256, 512).astype(np.uint16)


def walk(vram):
    """(address, ctrl) of each command drawn, in order: jumps and calls followed, skips left out."""
    w = lambda a: int(vram[(a >> 1) & 0x3FFFF])
    a, ret, out = 0, None, []
    for _ in range(20000):
        ctrl = w(a)
        if ctrl & 0x8000:
            break
        jp = ctrl >> 12 & 7
        if not ctrl & 0x4000:
            out.append((a, ctrl))
        link = w(a + 2) * 8
        if jp in (0, 4): a += 32
        elif jp in (1, 5): a = link
        elif jp in (2, 6): ret = a + 32; a = link
        else: a = ret if ret is not None else a + 32; ret = None
    return out


def owners(binary, s, tmp, mask):
    """For the mismatched dots, the command that last changed each (replays of the list cut short)."""
    cmds = walk(s['vram'])
    own = np.full((256, 512), -1, np.int32)
    prev = None
    base = s['vram'].copy()
    for i in range(len(cmds) + 1):
        v = base.copy()
        if i < len(cmds):
            v[cmds[i][0] >> 1] = 0x8000
        (tmp / 'vram.bin').write_bytes(v.astype('>u2').tobytes())
        subprocess.run([binary, str(tmp / 'vram.bin'), str(tmp / 'o.bin')] + ['%x' % r for r in s['regs']], check=True)
        o = np.fromfile(tmp / 'o.bin', '>u2').reshape(256, 512)
        if prev is not None:
            own[o != prev] = i - 1
        prev = o
    return cmds, own


def picture(ref, ours, path):
    from PIL import Image
    def rgb(x):
        x = x.astype(np.uint32)
        return (np.stack([x & 31, x >> 5 & 31, x >> 10 & 31], -1) * 255 // 31).astype(np.uint8)
    d = np.zeros((H, W, 3), np.uint8); d[ref != ours] = (255, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.concatenate([rgb(ref), rgb(ours), d], 1)).resize((W * 6, H * 2), Image.NEAREST).save(path)


def replay(a):
    regions = json.loads(a.regions) if a.regions else {}
    tmp = Path(tempfile.mkdtemp(prefix='vdp1replay-'))
    rows = []
    try:
        for p in a.snaps:
            z = np.load(p)
            row = {'snap': str(p)}
            best = None
            for i, name in enumerate(PAIRS):
                s = {'vram': z['vram'][i], 'regs': z['regs'][i]}
                o = replay_one(a.bin, s, tmp)
                ref = z['ref'][i][:H, :W]; ours = o[:H, :W]
                row[name] = float((ref == ours).mean())
                if best is None or row[name] > best[0]:
                    best = (row[name], name, s, ref, ours)
            row['all'], row['pair'], s, ref, ours = best
            for name, (x0, y0, x1, y1) in regions.items():
                row[name] = float((ref[y0:y1, x0:x1] == ours[y0:y1, x0:x1]).mean())
            if a.owners:
                cmds, own = owners(a.bin, s, tmp, ref != ours)
                bad = own[:H, :W][ref != ours]
                ids, n = np.unique(bad[bad >= 0], return_counts=True)
                top = sorted(zip(n, ids), reverse=True)[:a.owners]
                v = s['vram']
                row['owners'] = [{'n': int(c), 'cmd': int(i), 'addr': '%05X' % cmds[i][0],
                                  'ctrl': '%04X' % cmds[i][1], 'pmod': '%04X' % v[(cmds[i][0] >> 1) + 2],
                                  'size': '%04X' % v[(cmds[i][0] >> 1) + 5],
                                  'xy': [int(((int(v[(cmds[i][0] >> 1) + 6 + j]) & 0x1FFF) ^ 0x1000) - 0x1000) for j in range(8)]}
                                 for c, i in top]
            if a.png:
                picture(ref, ours, Path(a.png) / (Path(p).parent.name + '-' + Path(p).stem + '.png'))
            rows.append(row)
            print(json.dumps(row), flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return rows


def compose(binary, z, i, j, tmp):
    """Our VDP2 picture from state i's VDP2 memory and the framebuffer state j shows."""
    shown = z['fb'][j][(int(z['v1'][j][0]) & 1) ^ 1]
    blob = (z['vram'][i].astype('>u2').tobytes() + z['cram'][i].astype('>u2').tobytes()
            + z['regs'][i].astype('>u2').tobytes() + shown.astype('>u2').tobytes()
            + np.array([z['v1'][j][1], z['v1'][j][2]], '>u2').tobytes())
    (tmp / 's.bin').write_bytes(blob)
    subprocess.run([binary, str(tmp / 's.bin'), str(tmp / 'o.bin')], check=True)
    d = np.fromfile(tmp / 'o.bin', '<u4')
    w, h = int(d[0]), int(d[1])
    px = d[2:2 + w * h].reshape(h, w)
    return np.stack([px >> 16 & 255, px >> 8 & 255, px & 255], -1).astype(np.uint8)


def replay2(a):
    """VDP2 snapshots (*-vdp2.npz): our composed picture against the core's, centred in it."""
    tmp = Path(tempfile.mkdtemp(prefix='vdp2replay-'))
    try:
        for p in a.snaps:
            z = np.load(p)
            ref = z['pic']
            row, best = {'snap': str(p)}, None
            for i in (0, 1):
                for j in (0, 1):
                    ours = compose(a.bin, z, i, j, tmp)
                    h, w = ours.shape[:2]
                    dy, dx = (ref.shape[0] - h) // 2, (ref.shape[1] - w) // 2
                    r = ref[dy:dy + h, dx:dx + w]
                    exact = float((r == ours).all(-1).mean())
                    near = float(((r >> 3) == (ours >> 3)).all(-1).mean())
                    row[f'{i}{j}'] = exact
                    if best is None or exact > best[0]:
                        best = (exact, near, f'{i}{j}', r, ours)
            row['all'], row['5bit'], row['pair'], r, ours = best
            if a.png:
                bad = (r != ours).any(-1)
                m = (r // 3).copy(); m[bad] = (255, 0, 0)
                pic = np.concatenate([r, ours, m], 1)
                out = Path(a.png) / (Path(p).parent.name + '-' + Path(p).stem + '.png')
                out.parent.mkdir(parents=True, exist_ok=True)
                write_png(out, pic)
            print(json.dumps(row), flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_png(path, rgb):
    from PIL import Image
    Image.fromarray(rgb).save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('snap')
    s.add_argument('--cue', required=True); s.add_argument('--profile', required=True)
    s.add_argument('--save', required=True); s.add_argument('--record', required=True)
    s.add_argument('--frames', default='', help='frames after the load, comma-separated')
    s.add_argument('--pre', default='', help='frames from boot (title, Continue menu), comma-separated')
    s.add_argument('--out', required=True)
    s.add_argument('--core', default=os.environ.get('SF3_REFERENCE_CORE', '/tmp/beetle/mednafen_saturn_libretro.so'))
    s.add_argument('--bios', default=os.environ.get('SF3_BIOS', '/workspace/discs/bios'))
    s.add_argument('--runtime', default=str(HERE.parent / '.local' / 'saturn-recomp'))
    r = sub.add_parser('replay')
    r.add_argument('--bin', required=True, help='runtime/tests vdp1_replay')
    r.add_argument('--regions', default='', help='JSON {"name": [x0, y0, x1, y1]}')
    r.add_argument('--owners', type=int, default=0, help='list the N commands owning most mismatches')
    r.add_argument('--png', default='', help='directory for reference|ours|mismatch pictures')
    r.add_argument('snaps', nargs='+')
    r2 = sub.add_parser('replay2')
    r2.add_argument('--bin', required=True, help='runtime/tests vdp2_replay')
    r2.add_argument('--png', default='', help='directory for reference|ours|mismatch pictures')
    r2.add_argument('snaps', nargs='+')
    a = ap.parse_args()
    {'snap': snap, 'replay': replay, 'replay2': replay2}[a.cmd](a)


if __name__ == '__main__':
    main()
