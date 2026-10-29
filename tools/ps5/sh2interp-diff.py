#!/usr/bin/env python3
"""Differential fuzz: the C++ SH-2 interpreter against saturn-recomp's sh2emu.py.

Random synthetic programs (invented instructions, no game code): straight-line
code over every non-branch format, forward bt/bf, a dt loop with bf or bf/s,
bsr and jsr calls into a subroutine, and delay slots. Both sides run the same
program on the same random work RAM. The registers, both work RAMs (crc32)
and the instruction count must match.

    python3 tools/ps5/sh2interp-diff.py --harness build/sh2_interp_harness --count 2000
"""
import argparse
import os
import random
import subprocess
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.environ.get("SATURN_RECOMP", os.path.join(ROOT, ".local/saturn-recomp")), "src"))
from saturnrecomp import sh2, sh2emu  # noqa: E402

CODE, SUB = 0x06004000, 0x06006000
D = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11]
P = [12, 13]
SKIP = {"trapa #imm", "sleep", "rte", "rts", "ldc.l @Rm+,gbr", "jmp @Rn", "jsr @Rn", "braf Rn", "bsrf Rn",
        "bt @T", "bf @T", "bt/s @T", "bf/s @T", "bra @T", "bsr @T",
        "lds Rm,pr", "lds.l @Rm+,pr"}  # a PR write would send rts anywhere
FORMATS = [f for f in sh2.formats() if f not in SKIP]


def pick(rng, fmt):
    """[(fmt, n, m, low)] for one random instance of fmt, with a setup move when it needs r0 as an index."""
    pre = []
    n, m = rng.choice(D), rng.randrange(16)
    low = rng.randrange(256)
    if "@(r0," in fmt:
        pre = [("mov #imm,Rn", 0, 0, rng.randrange(-16, 16) * 4 & 0xFF)]
    mem_n = any(s in fmt for s in ("@Rn", "@-Rn", "@(disp,Rn)", "@(r0,Rn)", "@Rn+"))
    mem_m = any(s in fmt for s in ("@Rm", "@(disp,Rm)", "@(r0,Rm)"))
    if mem_n:
        n = rng.choice(P)
    if mem_m:
        m = rng.choice(P)
        if "Rn" in fmt and not mem_n and n == m:
            n = rng.choice(D)
    if fmt == "ldc Rm,gbr":
        m = rng.choice(P)
    if "@Rm+,Rn" in fmt and n == m:
        n = rng.choice(D)
    return pre + [(fmt, n, m, low)]


def straight(rng, k):
    out = []
    for _ in range(k):
        out += pick(rng, rng.choice(FORMATS))
    return out


def slot_insn(rng):
    while True:
        s = pick(rng, rng.choice(FORMATS))
        if len(s) == 1:
            return s


def assemble(items, base):
    """items: (fmt, n, m, low) or ('label', name) or ('br', fmt, label, n). Two passes for branch offsets."""
    labels, pc = {}, base
    for it in items:
        if it[0] == "label":
            labels[it[1]] = pc
        else:
            pc += 2
    words, pc = [], base
    for it in items:
        if it[0] == "label":
            continue
        if it[0] == "br":
            _, fmt, lab, n = it
            off = (labels[lab] - (pc + 4)) // 2
            words.append(sh2.encode(fmt, n=n, low=off & (0xFFF if fmt in ("bra @T", "bsr @T") else 0xFF)))
        else:
            fmt, n, m, low = it
            words.append(sh2.encode(fmt, n=n, m=m, low=low))
        pc += 2
    return b"".join(w.to_bytes(2, "big") for w in words)


def program(rng):
    # save PR: the calls below overwrite it
    it = [("sts.l pr,@-Rn", 15, 0, 0)] + straight(rng, rng.randrange(0, 12))
    it += [("label", "loop")] + straight(rng, rng.randrange(1, 8))
    if rng.random() < 0.5:
        it += [("br", "bt @T", "skip", 0)] + straight(rng, rng.randrange(1, 5)) + [("label", "skip")]
    else:
        it += [("br", "bf @T", "skip", 0)] + straight(rng, rng.randrange(1, 5)) + [("label", "skip")]
    if rng.random() < 0.6:
        it += [("br", "bsr @T", "sub", 0)] + slot_insn(rng)
    if rng.random() < 0.4:
        it += [("jsr @Rn", 14, 0, 0)] + slot_insn(rng)
    it += [("dt Rn", 9, 0, 0)]
    if rng.random() < 0.5:
        it += [("br", "bf/s @T", "loop", 0)] + slot_insn(rng)
    else:
        it += [("br", "bf @T", "loop", 0)]
    it += straight(rng, rng.randrange(0, 6))
    it += [("lds.l @Rm+,pr", 0, 15, 0), ("rts", 0, 0, 0)] + slot_insn(rng)
    sub = [("label", "sub")] + straight(rng, rng.randrange(0, 10)) + [("rts", 0, 0, 0)] + slot_insn(rng)
    # the subroutine is assembled with the main body so bsr can reach it
    return assemble(it + sub, CODE), it, sub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--harness", required=True)
    ap.add_argument("--count", type=int, default=500)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    fails = skipped = 0
    for case in range(a.count):
        rng = random.Random(a.seed * 1_000_003 + case)
        code, it, sub = program(rng)
        sub_addr = CODE + 2 * sum(1 for x in it if x[0] != "label")
        lowram, highram = bytearray(0x100000), bytearray(0x100000)
        for buf, lo in ((highram, 0x80000), (lowram, 0x40000), (highram, 0xF0000)):
            buf[lo:lo + 0x10000] = rng.randbytes(0x10000)
        highram[CODE - 0x06000000:CODE - 0x06000000 + len(code)] = code
        regs = {"r%d" % i: rng.getrandbits(32) for i in range(16)}
        regs.update(r12=0x06088000, r13=0x00248000, r14=sub_addr, r15=0x060FF000, r9=rng.randrange(1, 5))
        extra = {"sr": rng.getrandbits(10) & 0x3F3, "gbr": 0x06090000, "mach": rng.getrandbits(32),
                 "macl": rng.getrandbits(32), "vbr": rng.getrandbits(32), "pr": sh2emu.RETURN_SENTINEL}

        mem = sh2emu.Memory()
        lo_buf = mem.add(0x00200000, 0x100000, bytes(lowram))
        hi_buf = mem.add(0x06000000, 0x100000, bytes(highram))
        cpu = sh2emu.CPU(mem)
        cpu.sr = extra["sr"]
        cpu.gbr, cpu.mach, cpu.macl, cpu.vbr = extra["gbr"], extra["mach"], extra["macl"], extra["vbr"]
        try:
            cpu.call(CODE, max_steps=200_000, **regs)
            ref = {"r%d" % i: cpu.r[i] for i in range(16)}
            ref.update(sr=cpu.sr, gbr=cpu.gbr, vbr=cpu.vbr, mach=cpu.mach, macl=cpu.macl, pr=cpu.pr,
                       pc=sh2emu.RETURN_SENTINEL, crc_lo=zlib.crc32(lo_buf), crc_hi=zlib.crc32(hi_buf), insns=cpu.steps)
        except Exception as e:  # the reference refused (e.g. an access outside the RAMs): not a comparison
            skipped += 1
            if skipped <= 5:
                print("case %d: reference error %s (skipped)" % (case, e))
            continue

        lines = []
        for base, buf in ((0x00200000, lowram), (0x06000000, highram)):
            for off in range(0, 0x100000, 0x8000):
                chunk = buf[off:off + 0x8000]
                if any(chunk):
                    lines.append("mem %08X %s" % (base + off, chunk.hex()))
        for k, v in {**regs, **extra}.items():
            lines.append("reg %s %X" % (k, v & 0xFFFFFFFF))
        lines += ["crc 00200000 100000", "crc 06000000 100000", "run %08X" % CODE]
        out = subprocess.run([a.harness], input="\n".join(lines) + "\n", capture_output=True, text=True).stdout
        got = {}
        for ln in out.splitlines():
            p = ln.split()
            if p[0] == "crc":
                got["crc_lo" if p[1] == "00200000" else "crc_hi"] = int(p[2], 16)
            elif p[0] == "insns":
                got["insns"] = int(p[1])
            elif p[0] == "error":
                got["error"] = ln
            else:
                got[p[0]] = int(p[1], 16)
        diff = {k: (ref[k], got.get(k)) for k in ref if got.get(k) != ref[k]}
        if diff or "error" in got:
            fails += 1
            print("case %d FAIL %s %s" % (case, got.get("error", ""), {k: ("%X" % v[0], v[1] if v[1] is None else "%X" % v[1]) for k, v in diff.items()}))
            if fails >= 10:
                break
    print("%d cases, %d skipped, %d failures" % (a.count, skipped, fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
