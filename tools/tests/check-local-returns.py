"""Compile and execute synthetic MOVA/LDS PR local-return cases."""
import argparse
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser(__doc__)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
repo = Path(__file__).resolve().parents[2]
out = a.out.resolve()
if out == repo or repo in out.parents:
    raise SystemExit('Test outputs must stay outside the source repository')
out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(repo / '.local/saturn-recomp/src'))
from saturnrecomp.sh2 import Image
from saturnrecomp.recomp.discover import Program
from saturnrecomp.recomp.emit import Body

base = 0x06010000
data = bytearray(0x48)
words = {0: 0x4F22, 2: 0xC703, 4: 0x402A, 6: 0xD104,
         8: 0x412B, 10: 0xE205, 16: 0xE307, 18: 0x4F26,
         20: 0x000B, 22: 0x7201, 64: 0x7209, 66: 0x000B, 68: 0xE404}
for offset, word in words.items():
    data[offset:offset + 2] = word.to_bytes(2, 'big')
data[24:28] = (base + 64).to_bytes(4, 'big')
image = Image(bytes(data), base)
program = Program(image, seeds=[base, base + 64])
program.run()
assert base + 16 in program.funcs[base].code, 'Local continuation not discovered'
parts = ['#include "saturn/sh2.h"', '#include <cstdio>', '#include <cstdlib>',
         'alignas(64) uint8_t g_wram_l[0x100008], g_wram_h[0x100008];',
         'uint32_t g_sh2_watch_lo, g_sh2_watch_len;',
         'void sh2_watch_store(uint32_t, uint32_t, int) {}',
         'void sh2_poll(SH2Context& c) { c.budget = 10000; }',
         'uint32_t sh2_io_read(uint32_t, int) { std::abort(); }',
         'void sh2_io_write(uint32_t, uint32_t, int) { std::abort(); }',
         'void sh2_call(SH2Context& c, uint32_t addr) { if (addr != 0x06010040) std::abort(); c.r[2] += 9; c.r[4] = 4; c.pc = c.pr; }']
for mode in ('external', 'dynamic', 'internal'):
    function = program.funcs[base]
    saved_code = set(function.code)
    if mode == 'internal':
        function.code.update(program.funcs[base + 64].code)
    entries = {base, base + 64} if mode != 'dynamic' else {base}
    volatile = {base + 24} if mode == 'dynamic' else set()
    parts += [f'namespace {mode} {{', 'void f_06010040(SH2Context&);']
    parts += Body(program, function, entries, volatile=volatile).emit()
    if mode == 'external':
        parts += Body(program, program.funcs[base + 64], entries).emit()
    parts += ['}']
    function.code = saved_code
parts += ['int main() {', 'st32(0x06010018, 0x06010040);']
for mode in ('external', 'dynamic', 'internal'):
    parts += ['{ SH2Context c{}; c.pr = 0x12345678; c.r[15] = 0x060F0000; c.budget = 10000;',
              f'{mode}::f_06010000(c);',
              'if (c.pc != 0x12345678 || c.r[2] != 15 || c.r[3] != 7 || c.r[4] != 4 || c.r[15] != 0x060F0000) return 1;',
              f'std::puts("PASS: {mode} local return and both delay slots"); }}']
parts += ['}']
source = out / 'local-return.cpp'
source.write_text('\n'.join(parts) + '\n', encoding='utf-8')
binary = out / ('local-return.exe' if sys.platform == 'win32' else 'local-return')
subprocess.run(['clang++', '-std=c++20', '-O2', '-I', str(repo / '.local/saturn-recomp/runtime/include'),
                str(source), '-o', str(binary)], check=True)
subprocess.run([str(binary)], check=True)
