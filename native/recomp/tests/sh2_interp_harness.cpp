// Test harness for the SH-2 interpreter (MIT): flat work RAMs, stub runtime services.
// stdin:  "mem ADDR HEXBYTES" | "reg NAME VALUE" | "run ENTRY"
// stdout: the registers after the call, then crc32 of each work RAM window it was asked for ("crc ADDR LEN").
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include "../sh2_interp.h"

uint8_t g_wram_l[0x100000];
uint8_t g_wram_h[0x100000];
std::atomic<bool> g_state_requested{false};
const bool g_sh2_native_states = false;
uint32_t g_sh2_watch_lo, g_sh2_watch_len;
static uint64_t g_polls;

void sh2_call(SH2Context& c, uint32_t a) { sf3::sh2_interp_call(c, a); }
void sh2_poll(SH2Context& c) { ++g_polls; c.budget = 1000; }
void sh2_sleep(SH2Context&, uint32_t pc) { std::printf("error sleep %08X\n", pc); std::exit(2); }
void sh2_trapa(SH2Context&, uint32_t, uint32_t pc) { std::printf("error trapa %08X\n", pc); std::exit(2); }
void sh2_hook(SH2Context&, uint32_t) {}
void sh2_bad_return(SH2Context& c, uint32_t e) { std::printf("error bad_return %08X expected %08X\n", c.pc, e); std::exit(2); }
uint32_t sh2_io_read(uint32_t a, int s) { std::printf("error io_read %08X/%d\n", a, s); std::exit(2); }
void sh2_io_write(uint32_t a, uint32_t, int s) { std::printf("error io_write %08X/%d\n", a, s); std::exit(2); }
void state_native_point(SH2Context&, uint32_t) {}
void sh2_watch_store(uint32_t, uint32_t, int) {}

static uint8_t* host(uint32_t a) {
    a &= 0x1FFFFFFFu;
    if (SH2_IS_WRAM_H(a)) return g_wram_h + (a & 0xFFFFF);
    if (SH2_IS_WRAM_L(a)) return g_wram_l + (a & 0xFFFFF);
    std::printf("error unmapped %08X\n", a); std::exit(2);
}
static uint32_t crc32(const uint8_t* p, size_t n) {
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; ++i) { c ^= p[i]; for (int k = 0; k < 8; ++k) c = c >> 1 ^ (0xEDB88320u & (0u - (c & 1))); }
    return ~c;
}

// the patched runtime (tools/runtime-diagnostics.patch) declares this; the harness has no bus model
__attribute__((weak)) void sh2_bus_access(uint32_t, int, bool) {}

int main() {
    SH2Context c{};
    c.imask = 15; c.budget = 1000;
    static char line[1 << 20];
    std::string crcs;
    while (std::fgets(line, sizeof line, stdin)) {
        char kind[16] = {}, name[16] = {};
        unsigned long a = 0, v = 0;
        if (std::sscanf(line, "%15s", kind) != 1) continue;
        if (!std::strcmp(kind, "mem")) {
            char* p = line + 4; a = std::strtoul(p, &p, 16); while (*p == ' ') ++p;
            for (; p[0] && p[1] && p[0] != '\n'; p += 2) { char b[3] = {p[0], p[1], 0}; *host((uint32_t)a++) = (uint8_t)std::strtoul(b, nullptr, 16); }
        } else if (!std::strcmp(kind, "reg")) {
            std::sscanf(line, "%*s %15s %lx", name, &v);
            uint32_t x = (uint32_t)v;
            if (name[0] == 'r') c.r[std::atoi(name + 1)] = x;
            else if (!std::strcmp(name, "sr")) sh2_set_sr(c, x);
            else if (!std::strcmp(name, "gbr")) c.gbr = x;
            else if (!std::strcmp(name, "vbr")) c.vbr = x;
            else if (!std::strcmp(name, "mach")) c.mach = x;
            else if (!std::strcmp(name, "macl")) c.macl = x;
            else if (!std::strcmp(name, "pr")) c.pr = x;
        } else if (!std::strcmp(kind, "crc")) {
            crcs += line;
        } else if (!std::strcmp(kind, "run")) {
            std::sscanf(line, "%*s %lx", &a);
            sf3::sh2_interp_call(c, (uint32_t)a);
            for (int i = 0; i < 16; ++i) std::printf("r%d %08X\n", i, c.r[i]);
            std::printf("sr %08X\ngbr %08X\nvbr %08X\nmach %08X\nmacl %08X\npr %08X\npc %08X\n",
                        sh2_get_sr(c), c.gbr, c.vbr, c.mach, c.macl, c.pr, c.pc);
            const char* p = crcs.c_str();
            unsigned long lo, len;
            int used;
            while (std::sscanf(p, "crc %lx %lx\n%n", &lo, &len, &used) == 2) {
                std::printf("crc %08lX %08X\n", lo, crc32(host((uint32_t)lo), len));
                p += used;
            }
            std::printf("insns %llu polls %llu\n", (unsigned long long)sf3::g_sf3_interp_stats.insns, (unsigned long long)g_polls);
            return 0;
        }
    }
    return 1;
}
