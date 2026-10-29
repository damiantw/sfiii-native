"""Run tools/generate.py (saturn-recomp framework) and also dump what discovery decided, for the
C++ generator port (native/recomp/gen/emit_cpp.*) to re-emit byte-identically (MIT).

    python3 tools/ps5/gen-dump-discovery.py --recomp SATURN_RECOMP_SRC --dump OUT.txt -- GENERATE.PY ARGS...

SATURN_RECOMP_SRC is saturn-recomp's src/ (the pinned revision plus tools/runtime-diagnostics.patch).
The dump is game-derived (function layout and image paths): keep it outside the repository.

Format, one record per line, hexadecimal addresses:
    G native_states tasks0 tasks1 n_task_switches [5 values each] runtime_dir
    M name base path runtime_literals callable_entry unwind_returns block_coverage
    K hook... / S stack_return_call...           (the module's hooks / stack-return calls)
    P code...                                     (every discovered instruction, prog.code)
    F entry code...                               (one per function, in prog.funcs order)
    T entry site how candidate...                 (Body._resolve, how with spaces as '_')
    Q name base seed...                           (generate()'s specs, before any M record: discovery input)
"""
import os
import runpy
import sys

args = sys.argv[1:]
recomp = args[args.index('--recomp') + 1]
dump = args[args.index('--dump') + 1]
rest = args[args.index('--') + 1:]
sys.path.insert(0, recomp)
import saturnrecomp.recomp.__main__ as M   # noqa: E402
import saturnrecomp.recomp.emit as E        # noqa: E402

out = open(dump, 'w')
h = lambda v: '%X' % v
cur = {}
orig_init, orig_gen, orig_generate = E.Body.__init__, M.Module.generate, M.generate


def body_init(self, prog, f, *a, **k):
    orig_init(self, prog, f, *a, **k)
    for site in sorted(self._targets):
        cands, how = self._targets[site]
        out.write('T %s %s %s %s\n' % (h(f.entry), h(site), how.replace(' ', '_'), ' '.join(map(h, cands))))


def module_generate(self, *a, **k):
    out.write('M %s %s %s %d %d %d %d\n' % (self.name, h(self.base), os.path.abspath(self.path), self.runtime_literals,
                                           self.callable_entry, self.unwind_returns, self.block_coverage))
    out.write('K %s\n' % ' '.join(map(h, sorted(self.hooks))))
    out.write('S %s\n' % ' '.join(map(h, sorted(self.stack_return_calls))))
    out.write('P %s\n' % ' '.join(map(h, sorted(self.prog.code))))
    for e, fn in self.prog.funcs.items():
        out.write('F %s %s\n' % (h(e), ' '.join(map(h, sorted(fn.code)))))
    return orig_gen(self, *a, **k)


def generate(specs, out_dir, **k):
    tasks = k.get('tasks') or (0, 0)
    ts = list(k.get('task_switches', ()))
    out.write('G %d %s %s %d %s %s\n' % (bool(k.get('native_states')), h(tasks[0]), h(tasks[1]), len(ts),
                                       ' '.join(h(v) for s in ts for v in s), M.RUNTIME.replace('\\', '/')))
    for name, _path, base, seeds in specs:
        out.write('Q %s %s %s\n' % (name, h(base), ' '.join(map(h, seeds))))
    for key in ('hooks', 'unwind_returns', 'optest'):
        if k.get(key):
            raise SystemExit('gen-dump-discovery: %s is not covered by the C++ port yet' % key)
    return orig_generate(specs, out_dir, **k)


E.Body.__init__, M.Module.generate, M.generate = body_init, module_generate, generate
sys.argv = rest
sys.path.insert(0, os.path.dirname(os.path.abspath(rest[0])))
runpy.run_path(rest[0], run_name='__main__')
out.close()
