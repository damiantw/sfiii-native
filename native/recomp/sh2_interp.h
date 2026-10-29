// SF3 recomp: SH-2 interpreter fallback (MIT).
//
// Runs guest code the static recompiler did not cover, with the calling
// convention of a recompiled function (saturn/sh2.h): sh2_interp_call(c, a)
// behaves like f_<a>(c). It returns when the code at this depth runs rts/rte
// and leaves c.pc where that went. Callers check it with SH2_RET, exactly as
// for recompiled code.
//
// Semantics are saturn-recomp's src/saturnrecomp/recomp/emit.py, instruction
// for instruction, including where SH2_POLL safe points fall:
//   * backward branches and jumps (target <= the branch),
//   * before a call (bsr, jsr, bsrf), after its delay slot,
//   * after ldc/ldc.l to SR.
// Known differences from recompiled code, by design:
//   * pc-relative literals are read from memory when they run. The generator
//     folds them as constants when it compiles.
//   * the generator turns "falling past the function end" into a tail call. The
//     interpreter just keeps going. The guest-visible result is the same.
//   * build hooks (sh2_hook) and native state points are not honoured inside
//     interpreted code. g_sf3_interp_active counts the interpreted frames so
//     the state code can refuse a snapshot while any are live.
#pragma once
#include <cstdint>
#include "saturn/sh2.h"
#include "sh2_decode_table.h"

namespace sf3 {

// Builds the 64 Ki-entry decode table. Called once at startup; sh2_decode and sh2_interp_call call it if it was not.
void sh2_interp_init();
Sh2Op sh2_decode(uint16_t word);
bool sh2_is_delayed(Sh2Op op);

// Runs the guest from `entry` as a call (see above).
void sh2_interp_call(SH2Context& c, uint32_t entry);

// If set, a jmp/braf to an address this returns a function for leaves the
// interpreter as a tail call into that function (like emit.py's tail calls).
// The runtime points it at sh2_lookup. Null: stay in the interpreter.
extern SH2Func (*g_sf3_interp_compiled)(uint32_t addr);

// Called for an instruction the interpreter can't run: an undefined word, or
// a branch in a delay slot. The default prints the fault and aborts.
extern void (*g_sf3_interp_fault)(SH2Context& c, uint32_t pc, uint16_t word, const char* why);

struct Sh2InterpStats { uint64_t insns = 0, calls = 0, polls = 0; };
extern Sh2InterpStats g_sf3_interp_stats;
extern thread_local int g_sf3_interp_active;

}  // namespace sf3
