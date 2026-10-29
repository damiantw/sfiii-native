// SF3 recomp: the SH-2 interpreter as the runtime's fallback for code the recompiler missed (MIT).
//
// Linked into a game build, this registers sat_set_unknown_call_hook (tools/runtime-diagnostics.patch):
// a call to an address that is no entry of an active module runs in sh2_interp_call instead of
// stopping the game. Jumps from interpreted code to a recompiled entry leave the interpreter as
// tail calls (g_sf3_interp_compiled = sh2_lookup). Each new address is noted once, so a log
// shows what a profile's seeds should gain. The host calls sf3_interp_fallback_install() before
// saturn_main; SF3_INTERP_FALLBACK=0 leaves it off (the old fatal).
#include "sh2_interp.h"
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <unordered_set>

void sat_set_unknown_call_hook(bool (*hook)(SH2Context& c, uint32_t addr));   // runtime (saturn.h)
[[noreturn]] void sat_fatal(const char* fmt, ...);
void sat_note(const char* fmt, ...);

namespace {

std::mutex g_mu;
std::unordered_set<uint32_t> g_seen;

[[noreturn]] void fault(SH2Context& c, uint32_t pc, uint16_t word, const char* why) {
    sat_fatal("interpreter (cpu %d): %s at %08X (word %04X)", c.cpu, why, pc, word);
}

bool run(SH2Context& c, uint32_t addr) {
    {
        std::lock_guard<std::mutex> lock(g_mu);
        if (g_seen.insert(addr).second)
            sat_note("interpreting %08X (cpu %d, from pr %08X): no recompiled entry", addr, c.cpu, c.pr);
    }
    sf3::sh2_interp_call(c, addr);
    return true;
}

}  // namespace

void sf3_interp_fallback_install() {
    const char* e = std::getenv("SF3_INTERP_FALLBACK");
    if (e && e[0] == '0') return;
    sf3::sh2_interp_init();
    sf3::g_sf3_interp_compiled = sh2_lookup;
    sf3::g_sf3_interp_fault = fault;
    sat_set_unknown_call_hook(run);
}
