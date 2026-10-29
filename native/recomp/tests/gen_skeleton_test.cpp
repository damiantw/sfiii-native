// Generator skeleton test (MIT): discover an invented program, build a thunk-backend cache,
// round-trip it through the file format, load it RW -> RX like the PS5 path and run it.
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "../gen/backend.h"
#include "../gen/loader.h"
#include "../sh2_interp.h"

uint8_t g_wram_l[0x100000];
uint8_t g_wram_h[0x100000];
std::atomic<bool> g_state_requested{false};
const bool g_sh2_native_states = false;
uint32_t g_sh2_watch_lo, g_sh2_watch_len;
void sh2_call(SH2Context& c, uint32_t a) { sf3::sh2_interp_call(c, a); }
void sh2_poll(SH2Context& c) { c.budget = 1000; }
void sh2_sleep(SH2Context&, uint32_t) { std::abort(); }
void sh2_trapa(SH2Context&, uint32_t, uint32_t) { std::abort(); }
void sh2_hook(SH2Context&, uint32_t) {}
void sh2_bad_return(SH2Context&, uint32_t) { std::abort(); }
uint32_t sh2_io_read(uint32_t, int) { std::abort(); }
void sh2_io_write(uint32_t, uint32_t, int) { std::abort(); }
void state_native_point(SH2Context&, uint32_t) {}
void sh2_watch_store(uint32_t, uint32_t, int) {}
__attribute__((weak)) void sh2_bus_access(uint32_t, int, bool) {}

#define CHECK(x) do { if (!(x)) { std::printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #x); return 1; } } while (0)

int main() {
    using namespace sf3::gen;
    // invented code at 0x06004000:
    //   main: sts.l pr,@-r15 ; mov #5,r0 ; bsr sub ; nop ; add #1,r0 ; lds.l @r15+,pr ; rts ; nop
    //   sub:  add r0,r0 ; rts ; nop
    const uint16_t prog[] = {0x4F22, 0xE005, 0xB004, 0x0009, 0x7001, 0x4F26, 0x000B, 0x0009, 0x300C, 0x000B, 0x0009};
    Image img;
    img.base = 0x06004000;
    for (uint16_t w : prog) img.bytes.push_back(uint8_t(w >> 8)), img.bytes.push_back(uint8_t(w));
    std::memcpy(g_wram_h + 0x4000, img.bytes.data(), img.bytes.size());

    Program p = discover(img, {0x06004000});
    CHECK(p.funcs.size() == 2 && p.funcs.count(0x06004010));
    CHECK(p.funcs[0x06004000].calls.count(0x06004010) && !p.funcs[0x06004000].bad);

    X64ThunkBackend be;
    Cache c = build_cache(img, {0x06004000}, be);
    auto bytes = cache_serialize(c);
    Cache back;
    std::string why;
    CHECK(cache_parse(bytes.data(), bytes.size(), back, why));
    bytes[bytes.size() - 1] ^= 0;  // unchanged
    auto bad = bytes; bad[0] ^= 1;
    Cache tmp;
    CHECK(!cache_parse(bad.data(), bad.size(), tmp, why) && why == "not a code cache");

    ServiceTable svc{};
    svc[size_t(Service::InterpCall)] = reinterpret_cast<void*>(&sf3::sh2_interp_call);
    LoadedCode lc;
    CHECK(load_cache(back, svc, lc, why));
    CHECK(lc.funcs.size() == 2 && lc.funcs[0].addr == 0x06004000);

    SH2Context a{}, b{};
    a.r[15] = b.r[15] = 0x060FF000, a.pr = b.pr = 0x06000000, a.budget = b.budget = 1000;
    lc.funcs[0].fn(a);                                  // through the loaded RX thunk
    sf3::sh2_interp_call(b, 0x06004000);                // straight into the interpreter
    CHECK(a.r[0] == 11 && b.r[0] == 11 && a.pc == b.pc && a.pc == 0x06000000);
    unload(lc);
    std::printf("gen skeleton: discover 2 funcs, cache %zu bytes, loaded RX thunks ran: ok\n", bytes.size());
    return 0;
}
