// SF3 recomp: the runtime side of the x86-64 backend (MIT): the service table generated code calls
// (x64_abi.h), the rare instructions with emit.py's C++ for each, and loading a module's cache with its
// unwind info. Compiled with the runtime (saturn/sh2.h) into a build that runs generated code.
#include <atomic>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>

#include "code_cache.h"
#include "loader.h"
#include "sf3_x64_bind.h"
#include "x64_abi.h"

using namespace sf3::gen;
using namespace sf3::gen::x64;

static_assert(offsetof(SH2Context, t) == kT && offsetof(SH2Context, s) == kS && offsetof(SH2Context, q) == kQ &&
              offsetof(SH2Context, m) == kM && offsetof(SH2Context, imask) == kImask && offsetof(SH2Context, gbr) == kGbr &&
              offsetof(SH2Context, vbr) == kVbr && offsetof(SH2Context, mach) == kMach && offsetof(SH2Context, macl) == kMacl &&
              offsetof(SH2Context, pr) == kPr && offsetof(SH2Context, pc) == kPc && offsetof(SH2Context, budget) == kBudget &&
              offsetof(SH2Context, cpu) == kCpu, "SH2Context layout");

namespace {

uint32_t x_ld8(uint32_t a) { return ld8(a); }
uint32_t x_ld16(uint32_t a) { return ld16(a); }
uint32_t x_ld32(uint32_t a) { return ld32(a); }
void x_st8(uint32_t a, uint32_t v) { st8(a, v); }
void x_st16(uint32_t a, uint32_t v) { st16(a, v); }
void x_st32(uint32_t a, uint32_t v) { st32(a, v); }
void x_cyc(SH2Context& c, int n, int m, int k) {
    if (k) SH2_CYC2(c, n, m, k);
    else SH2_CYC(c, n, m);
}
void x_set_sr(SH2Context& c, uint32_t v) { sh2_set_sr(c, v); }
uint32_t x_get_sr(SH2Context& c) { return sh2_get_sr(c); }

// emit.py's stmt() for each, verbatim but for the register names.
void x_rare(SH2Context& c, uint32_t kind, uint32_t n, uint32_t m, uint32_t imm) {
    uint32_t& rn = c.r[n & 15];
    uint32_t& rm = c.r[m & 15];
    switch (Rare(kind)) {
    case rSwapB: rn = (rm & 0xFFFF0000u) | (rm & 0xFFu) << 8 | (rm >> 8 & 0xFFu); break;
    case rSwapW: rn = rm << 16 | rm >> 16; break;
    case rXtrct: rn = rm << 16 | rn >> 16; break;
    case rAddc: { uint64_t s = (uint64_t)rn + rm + c.t; c.t = (uint32_t)(s >> 32); rn = (uint32_t)s; } break;
    case rAddv: { int64_t s = (int64_t)(int32_t)rn + (int32_t)rm; c.t = s > INT32_MAX || s < INT32_MIN; rn = (uint32_t)s; } break;
    case rSubv: { int64_t s = (int64_t)(int32_t)rn - (int32_t)rm; c.t = s > INT32_MAX || s < INT32_MIN; rn = (uint32_t)s; } break;
    case rSubc: { uint32_t a = rn, b = rm, t = c.t; rn = a - b - t; c.t = (uint64_t)a < (uint64_t)b + t; } break;
    case rNegc: { uint32_t b = rm, t = c.t; rn = 0u - b - t; c.t = (uint64_t)b + t != 0; } break;
    case rCmpStr: { uint32_t x = rn ^ rm; c.t = !(x & 0xFFu) || !(x & 0xFF00u) || !(x & 0xFF0000u) || !(x & 0xFF000000u); } break;
    case rRotcl: { uint32_t t = rn >> 31; rn = rn << 1 | c.t; c.t = t; } break;
    case rRotcr: { uint32_t t = rn & 1; rn = rn >> 1 | c.t << 31; c.t = t; } break;
    case rDmuls: { uint64_t p = (uint64_t)((int64_t)(int32_t)rn * (int32_t)rm); c.mach = (uint32_t)(p >> 32); c.macl = (uint32_t)p; } break;
    case rDmulu: { uint64_t p = (uint64_t)rn * rm; c.mach = (uint32_t)(p >> 32); c.macl = (uint32_t)p; } break;
    case rMacW: sh2_mac_w(c, int(n), int(m)); break;
    case rMacL: sh2_mac_l(c, int(n), int(m)); break;
    case rDiv0s: c.q = rn >> 31; c.m = rm >> 31; c.t = c.q != c.m; break;
    case rDiv1: sh2_div1(c, rn, rm); break;
    case rAndB: { uint32_t a = c.gbr + c.r[0]; st8(a, ld8(a) & imm); } break;
    case rOrB: { uint32_t a = c.gbr + c.r[0]; st8(a, ld8(a) | imm); } break;
    case rXorB: { uint32_t a = c.gbr + c.r[0]; st8(a, ld8(a) ^ imm); } break;
    case rTstB: c.t = (ld8(c.gbr + c.r[0]) & imm) == 0; break;
    case rTasB: { uint32_t a = rn, v = ld8(a); c.t = v == 0; st8(a, v | 0x80u); } break;
    case rTrapa: sh2_trapa(c, imm, n); break;
    case rSleep: sh2_sleep(c, n); break;
    default: std::fprintf(stderr, "x64: bad rare op %u\n", kind); std::abort();
    }
}

void* const g_table[kSvcSlots] = {
    (void*)&sh2_call, (void*)&sh2_poll, (void*)&x_ld8, (void*)&x_ld16, (void*)&x_ld32, (void*)&x_st8, (void*)&x_st16,
    (void*)&x_st32, (void*)&x_cyc, (void*)&state_native_point, (void*)&g_state_requested, (void*)&sh2_bad_return,
    (void*)&sh2_hook, (void*)&x_set_sr, (void*)&x_get_sr, (void*)&x_rare,
    (void*)g_wram_h, (void*)&g_sh2_bus, (void*)&g_sh2_mem_q, (void*)&g_sh2_watch_len,
};
static_assert(sRare / 8 == 15 && sWatchLen / 8 == 19 && kSvcSlots == 20, "table order is x64_abi.h's");

// One CIE + one FDE over all of the code: at every call site CFA = rsp+64, ra at CFA-8,
// rbx at CFA-16, r12 at CFA-24 (x64_abi.h). __register_frame takes the section (libgcc).
extern "C" void __register_frame(void*);
void put32(std::vector<uint8_t>& o, uint32_t v) { for (int i = 0; i < 4; ++i) o.push_back(uint8_t(v >> (8 * i))); }
void put64(std::vector<uint8_t>& o, uint64_t v) { for (int i = 0; i < 8; ++i) o.push_back(uint8_t(v >> (8 * i))); }
void register_unwind(void* base, size_t size) {
    auto* o = new std::vector<uint8_t>;          // lives for the process
    std::vector<uint8_t> cie = {0, 0, 0, 0, 1, 'z', 'R', 0, 1, 0x78, 16, 1, 0x00,    // id 0, v1, "zR", caf 1, daf -8, ra 16, absptr
                                0x0c, 7, 64, 0x90, 1, 0x83, 2, 0x8c, 3};             // def_cfa rsp+64; ra, rbx, r12
    while ((cie.size() + 4) % 8) cie.push_back(0);
    put32(*o, uint32_t(cie.size()));
    o->insert(o->end(), cie.begin(), cie.end());
    size_t fde = o->size();
    std::vector<uint8_t> f;
    put32(f, uint32_t(fde + 4));                 // CIE pointer: from this field back to the CIE
    put64(f, reinterpret_cast<uint64_t>(base));
    put64(f, size);
    f.push_back(0);                              // augmentation data length
    while ((f.size() + 4) % 8) f.push_back(0);
    put32(*o, uint32_t(f.size()));
    o->insert(o->end(), f.begin(), f.end());
    put32(*o, 0);                                // terminator
    __register_frame(o->data());
}

[[noreturn]] void fail(const char* name, const std::string& why) {
    std::fprintf(stderr, "x64: module %s: %s\n", name, why.c_str());
    std::exit(70);
}

}  // namespace

bool sf3_x64_bind(const char* name, const uint32_t* addrs, SH2Func* fn, uint32_t n, uint8_t* ran) {
    const char* dir = std::getenv("SF3_X64_DIR");
    if (!dir) fail(name, "SF3_X64_DIR is not set");
    std::string path = std::string(dir) + "/" + name + ".sf3c";
    std::ifstream in(path, std::ios::binary);
    if (!in) fail(name, "cannot read " + path);
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(in)), {});
    Cache c;
    std::string why;
    if (!cache_parse(bytes.data(), bytes.size(), c, why)) fail(name, why);
    if (c.h.backend != 2) fail(name, "not x86-64 code");
    if (c.funcs.size() != n) fail(name, "entry count differs");
    for (uint32_t i = 0; i < n; ++i) if (c.funcs[i].addr != addrs[i]) fail(name, "entries differ");
    ServiceTable svc{};
    svc[size_t(Service::Table)] = (void*)g_table;
    svc[size_t(Service::ModuleRan)] = ran;
    LoadedCode l;
    if (!load_cache(c, svc, l, why)) fail(name, why);
    register_unwind(l.base, l.size);
    for (uint32_t i = 0; i < n; ++i) fn[i] = l.funcs[i].fn;
    return true;
}
