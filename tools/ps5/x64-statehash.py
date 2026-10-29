#!/usr/bin/env python3
# (MIT) Reference (clang C++) vs x86-64 code caches: statehash at the same vblanks.
import os, socket, subprocess, sys, time
from pathlib import Path
#   x64-statehash.py REF_SATURN X64_SATURN X64_CACHE_DIR CUE RUNDIR [VBLANK...]
REF, XS, XD, CUE, W = sys.argv[1:6]; W = Path(W); W.mkdir(parents=True, exist_ok=True)
class R:
    def __init__(s, name, sat, env):
        a, b = socket.socketpair(); bak = W / f'{name}.bin'
        if bak.exists(): bak.unlink()
        s.p = subprocess.Popen([sat, '--headless', '--cue', CUE, '--save', str(bak), '--settings', '-', '--clock', '1998-01-01T12:00:00',
            '--out', str(W / name), '--agent', str(b.fileno())], pass_fds=[b.fileno()], env={**os.environ, **env},
            stdin=subprocess.DEVNULL, stdout=open(W / f'{name}.log', 'w'), stderr=subprocess.STDOUT)
        b.close(); s.s = a; s.f = a.makefile('rb'); s.v = s.line()
    def line(s):
        l = s.f.readline().decode().strip()
        if not l: raise SystemExit('runtime closed the socket')
        return l
    def ask(s, c): s.s.sendall((c + '\n').encode()); return s.line()
    def step(s, n): s.s.sendall(f'step {n}\n'.encode()); s.v = s.line(); return int(s.v.split()[1])
    def quit(s):
        try: s.s.sendall(b'quit\n')
        except OSError: pass
        s.p.wait(30)
pts = [int(x) for x in (sys.argv[6:] or ['300', '1500', '4000', '6000'])]
ref = R('ref', REF, {}); x = R('x64', XS, {'SF3_X64_DIR': XD})
ok = True; tr = tx = 0
for p in pts:
    t = time.time(); vr = ref.step(p - int(ref.v.split()[1])); tr += time.time() - t
    t = time.time(); vx = x.step(p - int(x.v.split()[1])); tx += time.time() - t
    hr, hx = ref.ask('statehash'), x.ask('statehash')
    for _ in range(120):
        if 'machine=busy' not in hr + hx: break
        ref.step(1); x.step(1); hr, hx = ref.ask('statehash'), x.ask('statehash')
    same = hr == hx; ok &= same
    print(p, vr, vx, 'SAME' if same else 'DIFF', f'ref {tr:.1f}s x64 {tx:.1f}s', flush=True)
    if not same:
        a = dict(k.split(':', 1) if ':' in k else (k, '') for k in hr.split()[1:]); b = dict(k.split(':', 1) if ':' in k else (k, '') for k in hx.split()[1:])
        print(' parts:', [k for k in set(a) | set(b) if a.get(k) != b.get(k)]); print(' ref', hr[:300]); print(' x64', hx[:300]); break
ref.quit(); x.quit(); print('PASS' if ok else 'FAIL'); sys.exit(0 if ok else 1)
