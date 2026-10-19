// Synthetic modules only: no Saturn game code or data.
#include "saturn/sh2.h"
#include <cstdio>
#include <cstdlib>
#include <initializer_list>

static SH2Module modules[14];
static SH2FuncEntry entries[14][2];
extern const SH2Module* const g_sh2_modules[] = {
    &modules[0], &modules[1], &modules[2], &modules[3], &modules[4], &modules[5],
    &modules[6], &modules[7], &modules[8], &modules[9], &modules[10], &modules[11], &modules[12], &modules[13]};
extern const int g_sh2_nmodules = 14;
static int calls, starts;
static void entry(SH2Context&) { ++calls; }
static void replacement(SH2Context&) { calls += 100; }
static void check(bool yes, const char* why) { if (!yes) { std::fprintf(stderr, "%s\n", why); std::exit(1); } }
void sh2_program_start(SH2Context&, uint32_t) { ++starts; }
void sh2_call_unknown(SH2Context&, uint32_t) { check(false, "unknown call"); }
uint32_t sh2_mmio_read(uint32_t, int) { return 0; }
void sh2_mmio_write(uint32_t, uint32_t, int) {}

int main() {
    // Work RAM aliases must agree on byte order and remain independent.
    for(uint32_t base : {0x00200000u,0x06000000u}) {
        for(uint32_t offset : {0u,0x1234u,0xFFFFCu}) {
            st32(base+offset,0x12345678);
            check(ld8(base+offset)==0x12 && ld16(base+offset+2)==0x5678,"big-endian RAM widths");
            check(ld32((base|0x20000000)+offset)==0x12345678,"cache-through alias reads same RAM");
            st16((base|0x20000000)+offset,0xABCD);
            check(ld32(base+offset)==0xABCD5678,"cache-through stores share underlying RAM");
        }
    }
    st32(0x00200000,0x13572468);st32(0x06000000,0x24681357);
    check(ld32(0x00200000)==0x13572468 && ld32(0x06000000)==0x24681357,"high and low work RAM must be independent");
    st32(0x061FFFFC,0xF1E2D3C4);
    check(ld32(0x060FFFFC)==0xF1E2D3C4 && ld32(0x27FFFFFC)==0xF1E2D3C4,"high RAM mirrors agree at final aligned word");
    uint8_t across[8]={1,2,3,4,5,6,7,8},readback[8]{};
    check(sh2_mem_write(0x060FFFFC,across,8) && sh2_mem_read(0x260FFFFC,readback,8),"bulk RAM access across physical high-RAM mirror");
    for(int i=0;i<8;++i) check(readback[i]==across[i],"bulk mirror must retain every byte");
    check(!sh2_mem_read(0x00100000,readback,1),"unmapped bulk read rejected");
    for (unsigned i = 0; i < 12; ++i) {
        auto base = 0x06010000u + i * 0x100;
        uint8_t data[16];
        for (unsigned j = 0; j < sizeof data; ++j) data[j] = static_cast<uint8_t>(i + j);
        check(sh2_mem_write(base, data, sizeof data), "write RAM");
        entries[i][0] = {base, entry};
        entries[i][1] = {base + 8, entry};
        modules[i] = {"synthetic", base, sizeof data, sh2_crc32(data, sizeof data), entries[i], 2, nullptr, nullptr, true};
    }
    uint8_t newer[8] = {90,91,92,93,94,95,96,97};
    entries[12][0] = {modules[0].base + 8, replacement};
    modules[12] = {"replacement", modules[0].base + 8, 8, sh2_crc32(newer, 8), entries[12], 1, nullptr, nullptr, true};
    uint8_t alternate[16]={42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57};
    entries[13][0]={modules[1].base+8,replacement};
    modules[13]={"same-base-alternate",modules[1].base,16,sh2_crc32(alternate,16),entries[13],1,nullptr,nullptr,true};
    for (unsigned i = 0; i < 12; ++i) {
        auto& m = modules[i];
        check(sh2_identify(m.base) == &m, "exact image identification");
        sh2_activate(&m);
    }
    for (unsigned i = 0; i < 12; ++i) check(sh2_lookup(modules[i].base) == entry, "more than eight resident modules");
    uint8_t changed = 0xFF;
    check(sh2_mem_write(modules[0].base + 15, &changed, 1), "mutate synthetic data");
    check(sh2_identify(modules[0].base) == nullptr, "whole-image CRC must notice mutation");
    SH2Context cpu{};
    sh2_call(cpu, modules[0].base);
    check(calls == 1 && starts == 0, "active returning module must not become a program restart after data mutation");
    check(sh2_mem_write(modules[12].base, newer, 8), "load overlapping replacement");
    sh2_call(cpu, modules[12].base);
    check(calls == 101 && starts == 0, "exact replacement must take priority over an old interior entry");
    check(sh2_lookup(modules[0].base) == nullptr, "overlapping resident must deactivate");
    check(sh2_mem_write(modules[13].base,alternate,sizeof alternate),"replace overlay at same base");
    sh2_call(cpu,modules[13].base+8);
    check(calls==201 && starts==0,"interior call must identify replacement even when old overlay has that entry");
    check(sh2_lookup(modules[1].base)==nullptr,"same-base stale entry must deactivate");
    check(sh2_lookup(modules[13].base+8+0x20000000)==replacement,"native lookup through cache-through alias");
    for(int i=0;i<64;++i) {
        uint8_t original[16];for(unsigned j=0;j<16;++j) original[j]=uint8_t(1+j);
        check(sh2_mem_write(modules[1].base,original,16),"restore original overlay");
        sh2_call(cpu,modules[1].base+8);
        check(sh2_lookup(modules[1].base+8)==entry,"repeated original overlay activation");
        check(sh2_mem_write(modules[13].base,alternate,16),"restore alternate overlay");
        sh2_call(cpu,modules[13].base+8+0x20000000);
        check(sh2_lookup(modules[13].base+8)==replacement,"repeated alternate overlay activation");
    }
    check(sh2_lookup(0x060F1234)==nullptr,"unmapped function must not resolve spuriously");
    std::puts("PASS: 12 residents, data mutation, overlapping replacement, interior overlay switch and stale-entry invalidation");
}
