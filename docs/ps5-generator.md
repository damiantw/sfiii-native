# On-console generator (PS5 port, route B1)

The PS5 port can't ship recompiled game code: it is derived from the discs. So the console builds it
itself, from the user's disc, on first launch.

The desktop pipeline is: Python discovery → C++ → clang++. Too heavy for the console.

The on-console pipeline is:
1. Discovery in C++ (`native/recomp/gen/discover.*`, a port of saturn-recomp's `discover.py`).
2. A backend emits x86-64 straight into a code cache (`gen/backend*.cpp`, `gen/code_cache.*`).
3. A loader maps the cache read-write, applies relocations, and flips it to read-execute (`gen/loader*.cpp`).
4. The loaded functions become an `SH2Module` table, just like the clang-built ones.

Code the generator missed runs in the SH-2 interpreter (`native/recomp/sh2_interp.*`).

## Pieces and status
| piece | file | status |
|---|---|---|
| decode table | `sh2_decode_table.h` (generated from `sh2.py`) | done |
| interpreter fallback | `sh2_interp.cpp` | done; differential fuzz against `sh2emu.py`, 3000 cases, 0 failures |
| discovery | `gen/discover.cpp` | core walk done. It follows branches, delay slots and bsr entries, notes literals and stops at indirect jumps. Still to port: switch tables, literal-pool jsr targets, data marking, scene data-table entries, bounds and rejection rules |
| cache format | `gen/code_cache.*` | v1: header, sorted entries, relocations to runtime services, then code. No host addresses stored |
| backend | `gen/backend_x64_thunk.cpp` | baseline only: each function is a 16-byte-aligned thunk into the interpreter |
| real x86-64 backend | — | next (PLAN P1). Must match `emit.py`: registers in `SH2Context`, ld/st through services, `SH2_POLL` at the same safe points, folded literals |
| loader | `gen/loader_posix.cpp` | mmap RW → relocate → mprotect RX (the PS5 order, PROBE.md). The PS5 version uses sceKernel* calls behind the same API. Executable memory on fw 13.x still needs a console test |

## Exit criteria
- Discovery: function sets and entries match the Python on every profile (dump both tables and diff them).
- Backend: sweeps and differential runs match the clang builds.

## Test
`tools/tests/test_gen_skeleton.py` builds `native/recomp/tests/gen_skeleton_test.cpp`. The test:
1. Discovers an invented two-function program.
2. Builds a cache and round-trips it through the file format.
3. Loads it RX and checks that a call through the loaded thunk matches the interpreter.
