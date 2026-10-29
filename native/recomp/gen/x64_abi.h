// SF3 recomp, on-console generator: the ABI between x86-64 code made by emit_x64 and the runtime (MIT).
//
// Generated code keeps the SH-2 state in SH2Context (rbx) and reaches the runtime through one table of
// pointers (r12), loaded from a relocation in every entry's prologue. Frame at every call site:
//   push rbx; push r12; sub rsp,40     (CFA = rsp+64, rbx at CFA-16, r12 at CFA-24, scratch [rsp..rsp+40))
// The loader registers one unwind FDE with exactly that rule over the whole code, so C++ exceptions the
// runtime throws (task unwinds, state loads, run stops) pass through generated frames.
#pragma once
#include <cstdint>

namespace sf3::gen::x64 {

// SH2Context field offsets (saturn/sh2.h); x64_rt.cpp static_asserts them.
enum Ctx : int8_t {
    kT = 64, kS = 68, kQ = 72, kM = 76, kImask = 80, kGbr = 84, kVbr = 88, kMach = 92, kMacl = 96,
    kPr = 100, kPc = 104, kBudget = 108, kCpu = 112,
};

// Slots of the service table, in bytes from its start (8 each).
enum Svc : int8_t {
    sCall = 0,        // void sh2_call(SH2Context&, uint32_t)
    sPoll = 8,        // void sh2_poll(SH2Context&)
    sLd8 = 16, sLd16 = 24, sLd32 = 32,      // uint32_t ldN(uint32_t a)
    sSt8 = 40, sSt16 = 48, sSt32 = 56,      // void stN(uint32_t a, uint32_t v)
    sCyc = 64,        // void cyc(SH2Context&, int n, int m, int k): SH2_CYC / SH2_CYC2
    sStatePoint = 72, // void state_native_point(SH2Context&, uint32_t pc)
    sStateReq = 80,   // const std::atomic<bool>* (data): g_state_requested
    sBadReturn = 88,  // void sh2_bad_return(SH2Context&, uint32_t expected)
    sHook = 96,       // void sh2_hook(SH2Context&, uint32_t addr)
    sSetSr = 104,     // void set_sr(SH2Context&, uint32_t v)
    sGetSr = 112,     // uint32_t get_sr(SH2Context&)
    sRare = 120,      // void rare(SH2Context&, uint32_t kind, uint32_t n, uint32_t m, uint32_t imm)
    kSvcSlots = 16,
};

// Instructions run by the rare service, with emit.py's C++ for each (x64_rt.cpp).
enum Rare : uint32_t {
    rSwapB, rSwapW, rXtrct, rAddc, rAddv, rSubv, rSubc, rNegc, rCmpStr, rRotcl, rRotcr, rDmuls, rDmulu,
    rMacW, rMacL, rDiv0s, rDiv1, rAndB, rOrB, rXorB, rTstB, rTasB, rTrapa, rSleep,
};

}  // namespace sf3::gen::x64
