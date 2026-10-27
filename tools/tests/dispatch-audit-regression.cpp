// Synthetic regression for SF3_DISPATCH_AUDIT=1: a call through a register that the active modules
// resolve to a recompiled entry whose bytes in memory are not the module image's is logged, and the
// call still runs (log, never abort). No game data: two invented 64-byte images share one base; the
// first has no callable_entry, so nothing in the dispatch looks at its header before trusting it.
#include "saturn.h"
#include "test.h"
#include <cstdlib>
#include <cstring>

static int g_ran;
static void entry_a(SH2Context&) { g_ran = 1; }
static void inner_a(SH2Context&) { g_ran = 3; }

static const uint32_t kBase = 0x06088000, kSize = 64;
static uint8_t g_image_a[kSize], g_image_b[kSize];
static const SH2FuncEntry kFuncsA[] = {{kBase + 4, entry_a}, {kBase + 0x20, inner_a}};
static SH2Module g_a{"SYNTH_A", kBase, kSize, 0, kFuncsA, 2, nullptr, nullptr, false};
static SH2Module g_b{"SYNTH_B", kBase, kSize, 0, nullptr, 0, nullptr, nullptr, false};

// C: entries that end in an unconditional branch, then a literal pool holding a variable (the
// shape of hand-written code: mova SLOT,r0; rts; mov.w r4,@r0). The window stops after the
// branch's delay slot, so a store into the pool is not reported; a change in the code still is.
static void entry_c(SH2Context&) { g_ran = 5; }
static const uint32_t kBaseC = 0x0608A010, kSizeC = 80;    // entries past the base (a call to a base is a program start)
static const uint8_t kImageC[kSizeC] = {
    0x00, 0x09, 0x00, 0x0B, 0x00, 0x09, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // header
    0x90, 0x03, 0xAF, 0xF0, 0x64, 0x03, 0x00, 0x00, 0xFF, 0xE0, 0xFF, 0xE0, 0x06, 0x01, 0x6C, 0xF4,  // mov.w; bra; mov; pool
    0xC7, 0x04, 0x00, 0x0B, 0x20, 0x41, 0x00, 0x00, 0xFF, 0xE0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // mova; rts; mov.w r4,@r0; pool
    0xD0, 0x01, 0x40, 0x2B, 0x00, 0x09, 0x00, 0x00, 0x06, 0x01, 0x23, 0x45, 0x00, 0x00, 0x00, 0x00,  // mov.l; jmp @r0; nop; pool
    0x00, 0x09, 0x00, 0x09, 0x00, 0x09, 0x00, 0x09, 0x00, 0x09, 0x00, 0x09, 0x00, 0x09, 0x00, 0x09,  // straight line: all compared
};
static const SH2FuncEntry kFuncsC[] = {{kBaseC, entry_c}, {kBaseC + 0x10, entry_c}, {kBaseC + 0x20, entry_c}, {kBaseC + 0x30, entry_c}};
static const uint16_t kSizesC[] = {8, 8, 8, 8};
static SH2Module g_c{"SYNTH_C", kBaseC - 16, kSizeC, 0, kFuncsC, 4, nullptr, kSizesC, false};

extern const SH2Module* const g_sh2_modules[] = {&g_a, &g_b, &g_c};
extern const int g_sh2_nmodules = 3;
extern const uint32_t g_sh2_tasks[2] = {0, 0};
extern const SH2TaskSwitch g_sh2_task_switches[] = {{0, 0, 0, 0, 0}};
extern const int g_sh2_ntask_switches = 0;

static void load_image(const uint8_t* image) { std::memcpy(g_wram_h + (kBase - 0x06000000), image, kSize); }

static int call(uint32_t addr) {
    g_ran = 0;
    SH2Context c{};
    c.pr = 0x06010004;
    sh2_call(c, addr);
    return g_ran;
}

static void setup() {
    setenv("SF3_DISPATCH_AUDIT", "1", 1);
    for (uint32_t i = 0; i < kSize; ++i) { g_image_a[i] = uint8_t(i * 7 + 1); g_image_b[i] = uint8_t(i * 13 + 5); }
    g_a.crc = sh2_crc32(g_image_a, kSize);
    g_b.crc = sh2_crc32(g_image_b, kSize);
    for (int i = 0; i < sh2_active_slots(); ++i) sh2_set_active_slot(i, nullptr);
    load_image(g_image_a);
    sh2_activate(&g_a);
}

TEST(entry_over_its_own_image_is_not_reported) {
    setup();
    uint64_t before = sh2_dispatch_audit_reports();
    CHECK_EQ(call(kBase + 0x20), 3);
    CHECK_EQ(call(kBase + 4), 1);
    CHECK_EQ(sh2_dispatch_audit_reports(), before);
}

// Another image over A, A still active: the interior entry runs A's code over B's bytes. Logged
// once for that entry, and the call goes on.
TEST(entry_over_other_bytes_is_reported_once_and_still_runs) {
    setup();
    CHECK_EQ(call(kBase + 4), 1);
    uint64_t before = sh2_dispatch_audit_reports();
    load_image(g_image_b);
    CHECK_EQ(call(kBase + 0x20), 3);
    CHECK_EQ(sh2_dispatch_audit_reports(), before + 1);
    CHECK_EQ(call(kBase + 0x20), 3);
    CHECK_EQ(sh2_dispatch_audit_reports(), before + 1);
}

TEST(window_stops_after_the_delay_slot_of_an_unconditional_branch) {
    auto w = [](uint16_t a, uint16_t b, uint16_t c, uint16_t d) {
        uint8_t x[8] = {uint8_t(a >> 8), uint8_t(a), uint8_t(b >> 8), uint8_t(b), uint8_t(c >> 8), uint8_t(c), uint8_t(d >> 8), uint8_t(d)};
        return sh2_audit_window(x, 8);
    };
    CHECK_EQ(w(0x9003, 0xAFF0, 0x6403, 0x0000), 6u);    // bra
    CHECK_EQ(w(0x000B, 0x0009, 0xFFFF, 0xFFFF), 4u);    // rts
    CHECK_EQ(w(0x002B, 0x0009, 0xFFFF, 0xFFFF), 4u);    // rte
    CHECK_EQ(w(0x0009, 0x0323, 0x0009, 0xFFFF), 6u);    // braf r3
    CHECK_EQ(w(0x0009, 0x0009, 0x412B, 0x0009), 8u);    // jmp @r1, its slot the last word
    CHECK_EQ(w(0x0009, 0x0009, 0x0009, 0x412B), 8u);    // branch in the last word: no slot past n
    CHECK_EQ(w(0x8B01, 0x8901, 0x430B, 0x0009), 8u);    // bf, bt, jsr: not unconditional ends
    CHECK_EQ(w(0x0009, 0x0009, 0x0009, 0x0009), 8u);
}

static uint8_t* wram(uint32_t a) { return g_wram_h + (a - 0x06000000); }

TEST(pool_variable_after_the_branch_is_not_reported_code_is) {
    setenv("SF3_DISPATCH_AUDIT", "1", 1);                         // read once, at the first audited call
    for (int i = 0; i < sh2_active_slots(); ++i) sh2_set_active_slot(i, nullptr);
    g_c.crc = sh2_crc32(kImageC, kSizeC);
    std::memcpy(wram(kBaseC - 16), kImageC, kSizeC);
    sh2_activate(&g_c);
    uint64_t before = sh2_dispatch_audit_reports();
    wram(kBaseC + 8)[0] = 0xFE; wram(kBaseC + 8)[1] = 0x20;        // the bra entry's pool variable
    wram(kBaseC + 0x18)[1] = 0x20;                                // the rts entry's
    wram(kBaseC + 0x2A)[1] = 0x99;                                // the jmp entry's literal
    CHECK_EQ(call(kBaseC), 5);
    CHECK_EQ(call(kBaseC + 0x10), 5);
    CHECK_EQ(call(kBaseC + 0x20), 5);
    CHECK_EQ(sh2_dispatch_audit_reports(), before);
    wram(kBaseC + 4)[1] = 0x13;                                   // bra's delay slot: code
    CHECK_EQ(call(kBaseC), 5);
    CHECK_EQ(sh2_dispatch_audit_reports(), before + 1);
    wram(kBaseC + 0x3E)[1] = 0x19;                                // straight line, last compared word
    CHECK_EQ(call(kBaseC + 0x30), 5);
    CHECK_EQ(sh2_dispatch_audit_reports(), before + 2);
}
