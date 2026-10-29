// SF3 recomp: SH-2 interpreter fallback (MIT). See sh2_interp.h.
#include "sh2_interp.h"

#include <cstdio>
#include <cstdlib>

namespace sf3 {

static Sh2Op g_lut[65536];
static bool g_delayed[OP_COUNT];
static bool g_ready;

SH2Func (*g_sf3_interp_compiled)(uint32_t) = nullptr;
static void default_fault(SH2Context&, uint32_t pc, uint16_t word, const char* why) {
    std::fprintf(stderr, "sf3-interp: FATAL %s at %08X (word %04X)\n", why, pc, word);
    std::abort();
}
void (*g_sf3_interp_fault)(SH2Context&, uint32_t, uint16_t, const char*) = default_fault;
Sh2InterpStats g_sf3_interp_stats;
thread_local int g_sf3_interp_active;

void sh2_interp_init() {
    if (g_ready) return;
    for (uint32_t w = 0; w < 65536; ++w) {
        g_lut[w] = OP_INVALID;
        for (const Sh2Pattern& p : kSh2Patterns)
            if ((w & p.mask) == p.value) { g_lut[w] = p.op; break; }
    }
    for (const Sh2Pattern& p : kSh2Patterns) g_delayed[p.op] = p.delay;
    g_ready = true;
}

Sh2Op sh2_decode(uint16_t w) { if (!g_ready) sh2_interp_init(); return g_lut[w]; }
bool sh2_is_delayed(Sh2Op op) { if (!g_ready) sh2_interp_init(); return g_delayed[op]; }

static inline uint32_t sx8(uint32_t v) { return (uint32_t)(int32_t)(int8_t)v; }
static inline uint32_t sx16(uint32_t v) { return (uint32_t)(int32_t)(int16_t)v; }

// One instruction that does not branch. Returns false if `op` is a branch or undefined.
static bool exec(SH2Context& c, Sh2Op op, uint16_t w, uint32_t pc) {
    const Sh2Fields& f = kSh2Fields[op];
    const int n = f.n_shift == 255 ? 0 : (w >> f.n_shift) & 15;
    const int m = f.m_shift == 255 ? 0 : (w >> f.m_shift) & 15;
    uint32_t* r = c.r;
    uint32_t& R0 = r[0];
    uint32_t& Rn = r[n];
    const uint32_t d4 = w & 15, d8 = w & 0xFF;
    const uint32_t s8 = sx8(d8);
    switch (op) {
    case OP_NOP: break;
    // ----- moves
    case OP_MOV_RM_RN: Rn = r[m]; break;
    case OP_MOV_IMM_RN: Rn = s8; break;
    case OP_MOV_B_RM_AT_RN: st8(Rn, r[m]); break;
    case OP_MOV_W_RM_AT_RN: st16(Rn, r[m]); break;
    case OP_MOV_L_RM_AT_RN: st32(Rn, r[m]); break;
    case OP_MOV_B_AT_RM_RN: Rn = sx8(ld8(r[m])); break;
    case OP_MOV_W_AT_RM_RN: Rn = sx16(ld16(r[m])); break;
    case OP_MOV_L_AT_RM_RN: Rn = ld32(r[m]); break;
    case OP_MOV_B_RM_PRE_RN: { uint32_t v = r[m]; Rn -= 1; st8(Rn, v); break; }
    case OP_MOV_W_RM_PRE_RN: { uint32_t v = r[m]; Rn -= 2; st16(Rn, v); break; }
    case OP_MOV_L_RM_PRE_RN: { uint32_t v = r[m]; Rn -= 4; st32(Rn, v); break; }
    case OP_MOV_B_AT_RM_POST_RN: { uint32_t a = r[m]; if (n != m) r[m] += 1; Rn = sx8(ld8(a)); break; }
    case OP_MOV_W_AT_RM_POST_RN: { uint32_t a = r[m]; if (n != m) r[m] += 2; Rn = sx16(ld16(a)); break; }
    case OP_MOV_L_AT_RM_POST_RN: { uint32_t a = r[m]; if (n != m) r[m] += 4; Rn = ld32(a); break; }
    case OP_MOV_B_RM_AT_R0_RN: st8(R0 + Rn, r[m]); break;
    case OP_MOV_W_RM_AT_R0_RN: st16(R0 + Rn, r[m]); break;
    case OP_MOV_L_RM_AT_R0_RN: st32(R0 + Rn, r[m]); break;
    case OP_MOV_B_AT_R0_RM_RN: Rn = sx8(ld8(R0 + r[m])); break;
    case OP_MOV_W_AT_R0_RM_RN: Rn = sx16(ld16(R0 + r[m])); break;
    case OP_MOV_L_AT_R0_RM_RN: Rn = ld32(R0 + r[m]); break;
    case OP_MOV_B_R0_AT_DISP_RN: st8(Rn + d4, R0); break;
    case OP_MOV_W_R0_AT_DISP_RN: st16(Rn + d4 * 2, R0); break;
    case OP_MOV_L_RM_AT_DISP_RN: st32(Rn + d4 * 4, r[m]); break;
    case OP_MOV_B_AT_DISP_RM_R0: R0 = sx8(ld8(r[m] + d4)); break;
    case OP_MOV_W_AT_DISP_RM_R0: R0 = sx16(ld16(r[m] + d4 * 2)); break;
    case OP_MOV_L_AT_DISP_RM_RN: Rn = ld32(r[m] + d4 * 4); break;
    case OP_MOV_B_R0_AT_DISP_GBR: st8(c.gbr + d8, R0); break;
    case OP_MOV_W_R0_AT_DISP_GBR: st16(c.gbr + d8 * 2, R0); break;
    case OP_MOV_L_R0_AT_DISP_GBR: st32(c.gbr + d8 * 4, R0); break;
    case OP_MOV_B_AT_DISP_GBR_R0: R0 = sx8(ld8(c.gbr + d8)); break;
    case OP_MOV_W_AT_DISP_GBR_R0: R0 = sx16(ld16(c.gbr + d8 * 2)); break;
    case OP_MOV_L_AT_DISP_GBR_R0: R0 = ld32(c.gbr + d8 * 4); break;
    case OP_MOVA_PC_R0: R0 = (pc & ~3u) + 4 + d8 * 4; break;
    case OP_MOV_W_PC_RN: Rn = sx16(ld16(pc + 4 + d8 * 2)); break;
    case OP_MOV_L_PC_RN: Rn = ld32((pc & ~3u) + 4 + d8 * 4); break;
    case OP_MOVT_RN: Rn = c.t; break;
    case OP_SWAP_B_RM_RN: { uint32_t v = r[m]; Rn = (v & 0xFFFF0000u) | (v & 0xFFu) << 8 | (v >> 8 & 0xFFu); break; }
    case OP_SWAP_W_RM_RN: { uint32_t v = r[m]; Rn = v << 16 | v >> 16; break; }
    case OP_XTRCT_RM_RN: Rn = r[m] << 16 | Rn >> 16; break;
    // ----- arithmetic
    case OP_ADD_RM_RN: Rn += r[m]; break;
    case OP_ADD_IMM_RN: Rn += s8; break;
    case OP_ADDC_RM_RN: { uint64_t s = (uint64_t)Rn + r[m] + c.t; c.t = (uint32_t)(s >> 32); Rn = (uint32_t)s; break; }
    case OP_ADDV_RM_RN: { int64_t s = (int64_t)(int32_t)Rn + (int32_t)r[m]; c.t = s > INT32_MAX || s < INT32_MIN; Rn = (uint32_t)s; break; }
    case OP_SUB_RM_RN: Rn -= r[m]; break;
    case OP_SUBC_RM_RN: { uint32_t a = Rn, b = r[m], t = c.t; Rn = a - b - t; c.t = (uint64_t)a < (uint64_t)b + t; break; }
    case OP_SUBV_RM_RN: { int64_t s = (int64_t)(int32_t)Rn - (int32_t)r[m]; c.t = s > INT32_MAX || s < INT32_MIN; Rn = (uint32_t)s; break; }
    case OP_NEG_RM_RN: Rn = 0u - r[m]; break;
    case OP_NEGC_RM_RN: { uint32_t b = r[m], t = c.t; Rn = 0u - b - t; c.t = (uint64_t)b + t != 0; break; }
    case OP_DT_RN: Rn -= 1; c.t = Rn == 0; break;
    case OP_EXTS_B_RM_RN: Rn = sx8(r[m]); break;
    case OP_EXTS_W_RM_RN: Rn = sx16(r[m]); break;
    case OP_EXTU_B_RM_RN: Rn = r[m] & 0xFFu; break;
    case OP_EXTU_W_RM_RN: Rn = r[m] & 0xFFFFu; break;
    // ----- compare
    case OP_CMP_EQ_RM_RN: c.t = Rn == r[m]; break;
    case OP_CMP_EQ_IMM_R0: c.t = R0 == s8; break;
    case OP_CMP_HS_RM_RN: c.t = Rn >= r[m]; break;
    case OP_CMP_HI_RM_RN: c.t = Rn > r[m]; break;
    case OP_CMP_GE_RM_RN: c.t = (int32_t)Rn >= (int32_t)r[m]; break;
    case OP_CMP_GT_RM_RN: c.t = (int32_t)Rn > (int32_t)r[m]; break;
    case OP_CMP_PZ_RN: c.t = (int32_t)Rn >= 0; break;
    case OP_CMP_PL_RN: c.t = (int32_t)Rn > 0; break;
    case OP_CMP_STR_RM_RN: { uint32_t x = Rn ^ r[m]; c.t = !(x & 0xFFu) || !(x & 0xFF00u) || !(x & 0xFF0000u) || !(x & 0xFF000000u); break; }
    // ----- logic
    case OP_AND_RM_RN: Rn &= r[m]; break;
    case OP_OR_RM_RN: Rn |= r[m]; break;
    case OP_XOR_RM_RN: Rn ^= r[m]; break;
    case OP_TST_RM_RN: c.t = (Rn & r[m]) == 0; break;
    case OP_AND_IMM_R0: R0 &= d8; break;
    case OP_OR_IMM_R0: R0 |= d8; break;
    case OP_XOR_IMM_R0: R0 ^= d8; break;
    case OP_TST_IMM_R0: c.t = (R0 & d8) == 0; break;
    case OP_AND_B_IMM_AT_R0_GBR: { uint32_t a = c.gbr + R0; st8(a, ld8(a) & d8); break; }
    case OP_OR_B_IMM_AT_R0_GBR: { uint32_t a = c.gbr + R0; st8(a, ld8(a) | d8); break; }
    case OP_XOR_B_IMM_AT_R0_GBR: { uint32_t a = c.gbr + R0; st8(a, ld8(a) ^ d8); break; }
    case OP_TST_B_IMM_AT_R0_GBR: c.t = (ld8(c.gbr + R0) & d8) == 0; break;
    case OP_NOT_RM_RN: Rn = ~r[m]; break;
    case OP_TAS_B_AT_RN: { uint32_t a = Rn, v = ld8(a); c.t = v == 0; st8(a, v | 0x80u); break; }
    // ----- shifts and rotates
    case OP_SHLL_RN: case OP_SHAL_RN: c.t = Rn >> 31; Rn <<= 1; break;
    case OP_SHLR_RN: c.t = Rn & 1; Rn >>= 1; break;
    case OP_SHAR_RN: c.t = Rn & 1; Rn = (uint32_t)((int32_t)Rn >> 1); break;
    case OP_SHLL2_RN: Rn <<= 2; break;
    case OP_SHLL8_RN: Rn <<= 8; break;
    case OP_SHLL16_RN: Rn <<= 16; break;
    case OP_SHLR2_RN: Rn >>= 2; break;
    case OP_SHLR8_RN: Rn >>= 8; break;
    case OP_SHLR16_RN: Rn >>= 16; break;
    case OP_ROTL_RN: c.t = Rn >> 31; Rn = Rn << 1 | c.t; break;
    case OP_ROTR_RN: c.t = Rn & 1; Rn = Rn >> 1 | c.t << 31; break;
    case OP_ROTCL_RN: { uint32_t t = Rn >> 31; Rn = Rn << 1 | c.t; c.t = t; break; }
    case OP_ROTCR_RN: { uint32_t t = Rn & 1; Rn = Rn >> 1 | c.t << 31; c.t = t; break; }
    // ----- multiply and divide
    case OP_MUL_L_RM_RN: c.macl = Rn * r[m]; break;
    case OP_MULS_W_RM_RN: c.macl = (uint32_t)((int32_t)(int16_t)Rn * (int16_t)r[m]); break;
    case OP_MULU_W_RM_RN: c.macl = (Rn & 0xFFFFu) * (r[m] & 0xFFFFu); break;
    case OP_DMULS_L_RM_RN: { uint64_t p = (uint64_t)((int64_t)(int32_t)Rn * (int32_t)r[m]); c.mach = (uint32_t)(p >> 32); c.macl = (uint32_t)p; break; }
    case OP_DMULU_L_RM_RN: { uint64_t p = (uint64_t)Rn * r[m]; c.mach = (uint32_t)(p >> 32); c.macl = (uint32_t)p; break; }
    case OP_MAC_W_AT_RM_POST_AT_RN_POST: sh2_mac_w(c, n, m); break;
    case OP_MAC_L_AT_RM_POST_AT_RN_POST: sh2_mac_l(c, n, m); break;
    case OP_CLRMAC: c.mach = c.macl = 0; break;
    case OP_DIV0U: c.m = c.q = c.t = 0; break;
    case OP_DIV0S_RM_RN: c.q = Rn >> 31; c.m = r[m] >> 31; c.t = c.q != c.m; break;
    case OP_DIV1_RM_RN: sh2_div1(c, Rn, r[m]); break;
    // ----- T and the system registers
    case OP_CLRT: c.t = 0; break;
    case OP_SETT: c.t = 1; break;
    case OP_LDC_RM_SR: sh2_set_sr(c, r[m] & 0x3F3u); SH2_POLL(c); break;
    case OP_LDC_RM_GBR: c.gbr = r[m]; break;
    case OP_LDC_RM_VBR: c.vbr = r[m]; break;
    case OP_LDS_RM_MACH: c.mach = r[m]; break;
    case OP_LDS_RM_MACL: c.macl = r[m]; break;
    case OP_LDS_RM_PR: c.pr = r[m]; break;
    case OP_LDC_L_AT_RM_POST_SR: { uint32_t v = ld32(r[m]); r[m] += 4; sh2_set_sr(c, v & 0x3F3u); SH2_POLL(c); break; }
    case OP_LDC_L_AT_RM_POST_GBR: { uint32_t v = ld32(r[m]); r[m] += 4; c.gbr = v; break; }
    case OP_LDC_L_AT_RM_POST_VBR: { uint32_t v = ld32(r[m]); r[m] += 4; c.vbr = v; break; }
    case OP_LDS_L_AT_RM_POST_MACH: { uint32_t v = ld32(r[m]); r[m] += 4; c.mach = v; break; }
    case OP_LDS_L_AT_RM_POST_MACL: { uint32_t v = ld32(r[m]); r[m] += 4; c.macl = v; break; }
    case OP_LDS_L_AT_RM_POST_PR: { uint32_t v = ld32(r[m]); r[m] += 4; c.pr = v; break; }
    case OP_STC_SR_RN: Rn = sh2_get_sr(c); break;
    case OP_STC_GBR_RN: Rn = c.gbr; break;
    case OP_STC_VBR_RN: Rn = c.vbr; break;
    case OP_STS_MACH_RN: Rn = c.mach; break;
    case OP_STS_MACL_RN: Rn = c.macl; break;
    case OP_STS_PR_RN: Rn = c.pr; break;
    case OP_STC_L_SR_PRE_RN: Rn -= 4; st32(Rn, sh2_get_sr(c)); break;
    case OP_STC_L_GBR_PRE_RN: Rn -= 4; st32(Rn, c.gbr); break;
    case OP_STC_L_VBR_PRE_RN: Rn -= 4; st32(Rn, c.vbr); break;
    case OP_STS_L_MACH_PRE_RN: Rn -= 4; st32(Rn, c.mach); break;
    case OP_STS_L_MACL_PRE_RN: Rn -= 4; st32(Rn, c.macl); break;
    case OP_STS_L_PR_PRE_RN: Rn -= 4; st32(Rn, c.pr); break;
    case OP_TRAPA_IMM: sh2_trapa(c, d8, pc + 2); break;
    case OP_SLEEP: sh2_sleep(c, pc); break;
    default: return false;
    }
    return true;
}

static inline void poll_if_back(SH2Context& c, uint32_t target, uint32_t at) {
    if (target <= at) { ++g_sf3_interp_stats.polls; SH2_POLL(c); }
}

void sh2_interp_call(SH2Context& c, uint32_t entry) {
    if (!g_ready) sh2_interp_init();
    struct Active { Active() { ++g_sf3_interp_active; } ~Active() { --g_sf3_interp_active; } } active;
    ++g_sf3_interp_stats.calls;
    uint32_t pc = entry;
    uint32_t local_return = 1;            // odd: none. Set by "mova L,r0; lds r0,pr" (emit.py's local returns)
    Sh2Op prev = OP_INVALID;
    for (;;) {
        const uint16_t w = (uint16_t)ld16(pc);
        const Sh2Op op = g_lut[w];
        ++g_sf3_interp_stats.insns;
        if (!g_delayed[op] && op != OP_BT_PC && op != OP_BF_PC) {
            if (op == OP_LDS_RM_PR && prev == OP_MOVA_PC_R0 && ((w >> 8) & 15) == 0)
                local_return = c.r[0];
            if (!exec(c, op, w, pc)) { g_sf3_interp_fault(c, pc, w, "undefined instruction"); return; }
            prev = op;
            pc += 2;
            continue;
        }
        prev = op;
        const uint32_t b8 = pc + 4 + (uint32_t)((int32_t)(int8_t)(w & 0xFF) * 2);
        const uint32_t b12 = pc + 4 + (uint32_t)((((int32_t)(w & 0xFFF) ^ 0x800) - 0x800) * 2);
        const int n = (w >> 8) & 15;
        if (op == OP_BT_PC || op == OP_BF_PC) {
            if ((op == OP_BT_PC) == (c.t != 0)) { poll_if_back(c, b8, pc); pc = b8; }
            else pc += 2;
            continue;
        }
        // A delayed branch: read what it needs, run the slot, then go.
        auto slot = [&]() -> bool {
            const uint16_t sw = (uint16_t)ld16(pc + 2);
            const Sh2Op so = g_lut[sw];
            ++g_sf3_interp_stats.insns;
            if (g_delayed[so] || so == OP_BT_PC || so == OP_BF_PC) { g_sf3_interp_fault(c, pc + 2, sw, "branch in a delay slot"); return false; }
            if (!exec(c, so, sw, pc + 2)) { g_sf3_interp_fault(c, pc + 2, sw, "undefined instruction"); return false; }
            return true;
        };
        const uint32_t ret = pc + 4;
        switch (op) {
        case OP_BT_S_PC: case OP_BF_S_PC: {
            const bool k = (op == OP_BT_S_PC) == (c.t != 0);
            if (!slot()) return;
            if (k) { poll_if_back(c, b8, pc); pc = b8; } else pc = ret;
            break;
        }
        case OP_BRA_PC:
            if (!slot()) return;
            poll_if_back(c, b12, pc); pc = b12;
            break;
        case OP_BSR_PC: case OP_JSR_AT_RN: case OP_BSRF_RN: {
            const uint32_t x = op == OP_BSR_PC ? b12 : op == OP_JSR_AT_RN ? c.r[n] : ret + c.r[n];
            c.pr = ret;
            if (!slot()) return;
            ++g_sf3_interp_stats.polls;
            SH2_POLL(c);
            sh2_call(c, x);
            SH2_RET(c, ret);
            if (c.pc != ret) return;          // sh2_bad_return accepted another return: leave like recompiled code
            pc = ret;
            break;
        }
        case OP_JMP_AT_RN: case OP_BRAF_RN: {
            const uint32_t x = op == OP_JMP_AT_RN ? c.r[n] : ret + c.r[n];
            if (!slot()) return;
            poll_if_back(c, x, pc);
            if (g_sf3_interp_compiled && g_sf3_interp_compiled(x)) { sh2_call(c, x); return; }
            pc = x;
            break;
        }
        case OP_RTS: {
            const uint32_t x = c.pr;
            if (!slot()) return;
            if (x == local_return) { ++g_sf3_interp_stats.polls; SH2_POLL(c); pc = x; break; }
            c.pc = x;
            return;
        }
        case OP_RTE: {
            const uint32_t x = ld32(c.r[15]); c.r[15] += 4;
            sh2_set_sr(c, ld32(c.r[15]) & 0x3F3u); c.r[15] += 4;
            if (!slot()) return;
            c.pc = x;
            return;
        }
        default:
            g_sf3_interp_fault(c, pc, w, "undefined instruction");
            return;
        }
    }
}

}  // namespace sf3
