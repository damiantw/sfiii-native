// SF3 recomp, on-console generator (route B1), step 1: function discovery in C++ (MIT).
//
// This is a port, started here, of saturn-recomp's src/saturnrecomp/recomp/discover.py. Today it
// has only the core walk:
//   * Begin at the seed entries.
//   * Follow conditional and unconditional branches, including delay slots.
//   * Turn bsr targets into new entries, and stop at rts/rte/jmp.
//   * Record the pc-relative literal loads a function makes.
// Still to port, next to the Python (diff the tables on every profile, PLAN P0 exit criterion):
// switch tables (braf/jmp through tables), literal-pool calls (jsr through a mov.l literal), data
// marking, the scene/X1 data-table entries, bounds and rejection rules.
#pragma once
#include <cstdint>
#include <functional>
#include <map>
#include <set>
#include <vector>

namespace sf3::gen {

struct Image {                          // a program as loaded: bytes at base (guest big-endian)
    uint32_t base = 0;
    std::vector<uint8_t> bytes;
    bool inside(uint32_t a) const { return a >= base && a + 2 <= base + bytes.size() && !(a & 1); }
    uint16_t word(uint32_t a) const { size_t o = a - base; return uint16_t(bytes[o] << 8 | bytes[o + 1]); }
    uint32_t end() const { return base + uint32_t(bytes.size()); }
};

struct Function {
    uint32_t entry = 0;
    std::set<uint32_t> code;            // instruction addresses reached (delay slots included)
    std::set<uint32_t> calls;           // bsr targets (and later: resolved jsr literals)
    std::set<uint32_t> tails;           // bra/jmp into another entry
    std::set<uint32_t> literals;        // pc-relative literal addresses read
    std::vector<uint32_t> unresolved;   // indirect jmp/jsr/braf/bsrf sites
    const char* bad = nullptr;          // the first problem met
    uint32_t bad_at = 0;
};

struct Program {
    std::map<uint32_t, Function> funcs;
};

// Walks every function reachable from seeds through direct calls.
Program discover(const Image& img, const std::vector<uint32_t>& seeds);

}  // namespace sf3::gen
