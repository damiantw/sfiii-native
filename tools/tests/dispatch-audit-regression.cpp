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

extern const SH2Module* const g_sh2_modules[] = {&g_a, &g_b};
extern const int g_sh2_nmodules = 2;
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
