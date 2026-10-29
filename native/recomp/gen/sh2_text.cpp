// SF3 recomp, on-console generator: SH-2 decoding with saturn-recomp's text (MIT). See sh2_text.h.
#include "sh2_text.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <mutex>

namespace sf3::gen {
namespace {

struct Entry {
    uint16_t mask = 0, val = 0;
    const char* op;
    std::string fmt, kind;
    int nsh = -1, msh = -1;
    int bits = 0;
};

std::vector<Entry> g_table;

void t(const char* pattern, const char* op, std::string fmt, std::string kind = "") {
    Entry e{0, 0, op, std::move(fmt), std::move(kind)};
    int len = int(strlen(pattern));
    for (int i = 0; i < len; ++i) {
        e.mask = uint16_t(e.mask << 1);
        e.val = uint16_t(e.val << 1);
        if (pattern[i] == '0' || pattern[i] == '1') {
            e.mask |= 1;
            e.val |= pattern[i] == '1';
        }
    }
    const char* rn = strrchr(pattern, 'n');
    const char* rm = strrchr(pattern, 'm');
    if (rn) e.nsh = 15 - int(rn - pattern);
    if (rm) e.msh = 15 - int(rm - pattern);
    e.bits = __builtin_popcount(e.mask);
    g_table.push_back(std::move(e));
}

std::string bin4(int code) {
    std::string s;
    for (int b = 3; b >= 0; --b) s += char('0' + (code >> b & 1));
    return s;
}

void build() {
    t("0000000000001001", "nop", "nop");
    t("0000000000001011", "rts", "rts", "delay");
    t("0000000000101011", "rte", "rte", "delay");
    t("0000000000001000", "clrt", "clrt");
    t("0000000000011000", "sett", "sett");
    t("0000000000101000", "clrmac", "clrmac");
    t("0000000000011001", "div0u", "div0u");
    t("0000000000011011", "sleep", "sleep");
    t("0000nnnn00101001", "movt", "movt Rn", "n");
    t("0100nnnn00010001", "cmp/pz", "cmp/pz Rn", "n");
    t("0100nnnn00010101", "cmp/pl", "cmp/pl Rn", "n");
    t("0100nnnn00010000", "dt", "dt Rn", "n");
    t("0100nnnn00000100", "rotl", "rotl Rn", "n");
    t("0100nnnn00000101", "rotr", "rotr Rn", "n");
    t("0100nnnn00100100", "rotcl", "rotcl Rn", "n");
    t("0100nnnn00100101", "rotcr", "rotcr Rn", "n");
    t("0100nnnn00100000", "shal", "shal Rn", "n");
    t("0100nnnn00100001", "shar", "shar Rn", "n");
    t("0100nnnn00000000", "shll", "shll Rn", "n");
    t("0100nnnn00000001", "shlr", "shlr Rn", "n");
    t("0100nnnn00001000", "shll2", "shll2 Rn", "n");
    t("0100nnnn00001001", "shlr2", "shlr2 Rn", "n");
    t("0100nnnn00011000", "shll8", "shll8 Rn", "n");
    t("0100nnnn00011001", "shlr8", "shlr8 Rn", "n");
    t("0100nnnn00101000", "shll16", "shll16 Rn", "n");
    t("0100nnnn00101001", "shlr16", "shlr16 Rn", "n");
    t("0100nnnn00011011", "tas.b", "tas.b @Rn", "n");
    t("0100nnnn00101011", "jmp", "jmp @Rn", "n delay");
    t("0100nnnn00001011", "jsr", "jsr @Rn", "n delay");
    t("0000nnnn00100011", "braf", "braf Rn", "n delay");
    t("0000nnnn00000011", "bsrf", "bsrf Rn", "n delay");
    static const char* cregs[] = {"sr", "gbr", "vbr"};
    for (int code = 0; code < 3; ++code) {
        std::string r = cregs[code], c = bin4(code);
        t(("0100mmmm" + c + "1110").c_str(), "ldc", "ldc Rm," + r);
        t(("0100mmmm" + c + "0111").c_str(), "ldc.l", "ldc.l @Rm+," + r);
        t(("0000nnnn" + c + "0010").c_str(), "stc", "stc " + r + ",Rn");
        t(("0100nnnn" + c + "0011").c_str(), "stc.l", "stc.l " + r + ",@-Rn");
    }
    static const char* sregs[] = {"mach", "macl", "pr"};
    for (int code = 0; code < 3; ++code) {
        std::string r = sregs[code], c = bin4(code);
        t(("0100mmmm" + c + "1010").c_str(), "lds", "lds Rm," + r);
        t(("0100mmmm" + c + "0110").c_str(), "lds.l", "lds.l @Rm+," + r);
        t(("0000nnnn" + c + "1010").c_str(), "sts", "sts " + r + ",Rn");
        t(("0100nnnn" + c + "0010").c_str(), "sts.l", "sts.l " + r + ",@-Rn");
    }
    static const char* nm[][3] = {
        {"0110nnnnmmmm0011", "mov", "mov Rm,Rn"},
        {"0010nnnnmmmm0000", "mov.b", "mov.b Rm,@Rn"},
        {"0010nnnnmmmm0001", "mov.w", "mov.w Rm,@Rn"},
        {"0010nnnnmmmm0010", "mov.l", "mov.l Rm,@Rn"},
        {"0110nnnnmmmm0000", "mov.b", "mov.b @Rm,Rn"},
        {"0110nnnnmmmm0001", "mov.w", "mov.w @Rm,Rn"},
        {"0110nnnnmmmm0010", "mov.l", "mov.l @Rm,Rn"},
        {"0010nnnnmmmm0100", "mov.b", "mov.b Rm,@-Rn"},
        {"0010nnnnmmmm0101", "mov.w", "mov.w Rm,@-Rn"},
        {"0010nnnnmmmm0110", "mov.l", "mov.l Rm,@-Rn"},
        {"0110nnnnmmmm0100", "mov.b", "mov.b @Rm+,Rn"},
        {"0110nnnnmmmm0101", "mov.w", "mov.w @Rm+,Rn"},
        {"0110nnnnmmmm0110", "mov.l", "mov.l @Rm+,Rn"},
        {"0000nnnnmmmm0100", "mov.b", "mov.b Rm,@(r0,Rn)"},
        {"0000nnnnmmmm0101", "mov.w", "mov.w Rm,@(r0,Rn)"},
        {"0000nnnnmmmm0110", "mov.l", "mov.l Rm,@(r0,Rn)"},
        {"0000nnnnmmmm1100", "mov.b", "mov.b @(r0,Rm),Rn"},
        {"0000nnnnmmmm1101", "mov.w", "mov.w @(r0,Rm),Rn"},
        {"0000nnnnmmmm1110", "mov.l", "mov.l @(r0,Rm),Rn"},
        {"0110nnnnmmmm1000", "swap.b", "swap.b Rm,Rn"},
        {"0110nnnnmmmm1001", "swap.w", "swap.w Rm,Rn"},
        {"0010nnnnmmmm1101", "xtrct", "xtrct Rm,Rn"},
        {"0011nnnnmmmm1100", "add", "add Rm,Rn"},
        {"0011nnnnmmmm1110", "addc", "addc Rm,Rn"},
        {"0011nnnnmmmm1111", "addv", "addv Rm,Rn"},
        {"0011nnnnmmmm0000", "cmp/eq", "cmp/eq Rm,Rn"},
        {"0011nnnnmmmm0010", "cmp/hs", "cmp/hs Rm,Rn"},
        {"0011nnnnmmmm0011", "cmp/ge", "cmp/ge Rm,Rn"},
        {"0011nnnnmmmm0110", "cmp/hi", "cmp/hi Rm,Rn"},
        {"0011nnnnmmmm0111", "cmp/gt", "cmp/gt Rm,Rn"},
        {"0010nnnnmmmm1100", "cmp/str", "cmp/str Rm,Rn"},
        {"0011nnnnmmmm0100", "div1", "div1 Rm,Rn"},
        {"0010nnnnmmmm0111", "div0s", "div0s Rm,Rn"},
        {"0011nnnnmmmm1101", "dmuls.l", "dmuls.l Rm,Rn"},
        {"0011nnnnmmmm0101", "dmulu.l", "dmulu.l Rm,Rn"},
        {"0110nnnnmmmm1110", "exts.b", "exts.b Rm,Rn"},
        {"0110nnnnmmmm1111", "exts.w", "exts.w Rm,Rn"},
        {"0110nnnnmmmm1100", "extu.b", "extu.b Rm,Rn"},
        {"0110nnnnmmmm1101", "extu.w", "extu.w Rm,Rn"},
        {"0000nnnnmmmm1111", "mac.l", "mac.l @Rm+,@Rn+"},
        {"0100nnnnmmmm1111", "mac.w", "mac.w @Rm+,@Rn+"},
        {"0000nnnnmmmm0111", "mul.l", "mul.l Rm,Rn"},
        {"0010nnnnmmmm1111", "muls.w", "muls.w Rm,Rn"},
        {"0010nnnnmmmm1110", "mulu.w", "mulu.w Rm,Rn"},
        {"0110nnnnmmmm1011", "neg", "neg Rm,Rn"},
        {"0110nnnnmmmm1010", "negc", "negc Rm,Rn"},
        {"0011nnnnmmmm1000", "sub", "sub Rm,Rn"},
        {"0011nnnnmmmm1010", "subc", "subc Rm,Rn"},
        {"0011nnnnmmmm1011", "subv", "subv Rm,Rn"},
        {"0010nnnnmmmm1001", "and", "and Rm,Rn"},
        {"0110nnnnmmmm0111", "not", "not Rm,Rn"},
        {"0010nnnnmmmm1011", "or", "or Rm,Rn"},
        {"0010nnnnmmmm1000", "tst", "tst Rm,Rn"},
        {"0010nnnnmmmm1010", "xor", "xor Rm,Rn"},
    };
    for (auto& e : nm) t(e[0], e[1], e[2], "n m");
    t("10000000nnnndddd", "mov.b", "mov.b r0,@(disp,Rn)", "d4");
    t("10000001nnnndddd", "mov.w", "mov.w r0,@(disp,Rn)", "d4w");
    t("0001nnnnmmmmdddd", "mov.l", "mov.l Rm,@(disp,Rn)", "n m d4l");
    t("10000100mmmmdddd", "mov.b", "mov.b @(disp,Rm),r0", "m d4");
    t("10000101mmmmdddd", "mov.w", "mov.w @(disp,Rm),r0", "m d4w");
    t("0101nnnnmmmmdddd", "mov.l", "mov.l @(disp,Rm),Rn", "n m d4l");
    t("11000000dddddddd", "mov.b", "mov.b r0,@(disp,gbr)", "d8");
    t("11000001dddddddd", "mov.w", "mov.w r0,@(disp,gbr)", "d8w");
    t("11000010dddddddd", "mov.l", "mov.l r0,@(disp,gbr)", "d8l");
    t("11000100dddddddd", "mov.b", "mov.b @(disp,gbr),r0", "d8");
    t("11000101dddddddd", "mov.w", "mov.w @(disp,gbr),r0", "d8w");
    t("11000110dddddddd", "mov.l", "mov.l @(disp,gbr),r0", "d8l");
    t("11000111dddddddd", "mova", "mova @T,r0", "pcl");
    t("1001nnnndddddddd", "mov.w", "mov.w @T,Rn", "n pcw");
    t("1101nnnndddddddd", "mov.l", "mov.l @T,Rn", "n pcl");
    t("1110nnnniiiiiiii", "mov", "mov #imm,Rn", "n s8");
    t("0111nnnniiiiiiii", "add", "add #imm,Rn", "n s8");
    t("10001000iiiiiiii", "cmp/eq", "cmp/eq #imm,r0", "s8");
    t("11001001iiiiiiii", "and", "and #imm,r0", "u8");
    t("11001011iiiiiiii", "or", "or #imm,r0", "u8");
    t("11001000iiiiiiii", "tst", "tst #imm,r0", "u8");
    t("11001010iiiiiiii", "xor", "xor #imm,r0", "u8");
    t("11001101iiiiiiii", "and.b", "and.b #imm,@(r0,gbr)", "u8");
    t("11001111iiiiiiii", "or.b", "or.b #imm,@(r0,gbr)", "u8");
    t("11001100iiiiiiii", "tst.b", "tst.b #imm,@(r0,gbr)", "u8");
    t("11001110iiiiiiii", "xor.b", "xor.b #imm,@(r0,gbr)", "u8");
    t("11000011iiiiiiii", "trapa", "trapa #imm", "u8");
    t("10001001dddddddd", "bt", "bt @T", "b8");
    t("10001011dddddddd", "bf", "bf @T", "b8");
    t("10001101dddddddd", "bt/s", "bt/s @T", "b8 delay");
    t("10001111dddddddd", "bf/s", "bf/s @T", "b8 delay");
    t("1010dddddddddddd", "bra", "bra @T", "b12 delay");
    t("1011dddddddddddd", "bsr", "bsr @T", "b12 delay");
    // first match wins, most specific first (Python's stable sort on -popcount)
    std::stable_sort(g_table.begin(), g_table.end(), [](const Entry& a, const Entry& b) { return a.bits > b.bits; });
}

bool has(const std::vector<std::string>& k, const char* w) { return std::find(k.begin(), k.end(), w) != k.end(); }

struct Lookup { const Entry* e; std::vector<std::string> kind; };
Lookup g_cache[65536];

const Lookup& lookup(uint16_t w) {
    static std::once_flag once;
    std::call_once(once, [] {
        build();
        for (uint32_t x = 0; x < 65536; ++x) {
            g_cache[x].e = nullptr;
            for (auto& e : g_table)
                if ((x & e.mask) == e.val) {
                    g_cache[x].e = &e;
                    std::string k = e.kind;
                    size_t p = 0;
                    while (p < k.size()) {
                        size_t q = k.find(' ', p);
                        if (q == std::string::npos) q = k.size();
                        if (q > p) g_cache[x].kind.push_back(k.substr(p, q - p));
                        p = q + 1;
                    }
                    break;
                }
        }
    });
    return g_cache[w];
}

int s8(int x) { return x & 0x80 ? x - 0x100 : x; }
int s12(int x) { return x & 0x800 ? x - 0x1000 : x; }

void replace_all(std::string& s, const std::string& from, const std::string& to) {
    // str.replace: every non-overlapping occurrence, left to right
    std::string out;
    size_t p = 0;
    for (;;) {
        size_t q = s.find(from, p);
        if (q == std::string::npos) break;
        out.append(s, p, q - p);
        out += to;
        p = q + from.size();
    }
    out.append(s, p, std::string::npos);
    s = std::move(out);
}

}  // namespace

bool Insn::is(const char* o) const { return strcmp(op, o) == 0; }

std::string Insn::text() const {
    std::string f = fmt;
    char b[32];
    replace_all(f, "Rn", n >= 0 ? (snprintf(b, sizeof b, "r%d", n), std::string(b)) : std::string());
    replace_all(f, "Rm", m >= 0 ? (snprintf(b, sizeof b, "r%d", m), std::string(b)) : std::string());
    if (imm) {
        if (-256 < *imm && *imm < 256) snprintf(b, sizeof b, "#%d", *imm);
        else snprintf(b, sizeof b, "#0x%X", uint32_t(*imm));
        replace_all(f, "#imm", b);
    }
    if (target) { snprintf(b, sizeof b, "0x%08X", *target); replace_all(f, "@T", b); }
    if (disp) { snprintf(b, sizeof b, "%d", *disp); replace_all(f, "disp", b); }
    return f;
}

Insn decode(uint16_t word, uint32_t pc) {
    const Lookup& l = lookup(word);
    Insn ins;
    ins.pc = pc;
    ins.word = word;
    if (!l.e) {
        char b[16];
        snprintf(b, sizeof b, ".word 0x%04X", word);
        ins.fmt = b;
        return ins;
    }
    const Entry& e = *l.e;
    const auto& k = l.kind;
    ins.op = e.op;
    ins.fmt = e.fmt;
    ins.delay = has(k, "delay");
    if (e.nsh >= 0) ins.n = word >> e.nsh & 15;
    if (e.msh >= 0) ins.m = word >> e.msh & 15;
    int d4 = word & 15, d8 = word & 0xFF;
    if (has(k, "d4")) ins.disp = d4;
    if (has(k, "d4w")) ins.disp = d4 * 2;
    if (has(k, "d4l")) ins.disp = d4 * 4;
    if (has(k, "d8")) ins.disp = d8;
    if (has(k, "d8w")) ins.disp = d8 * 2;
    if (has(k, "d8l")) ins.disp = d8 * 4;
    if (has(k, "s8")) ins.imm = s8(d8);
    if (has(k, "u8")) ins.imm = d8;
    if (has(k, "pcw")) { ins.target = pc + 4 + d8 * 2; ins.size = 2; }
    if (has(k, "pcl")) { ins.target = (pc & ~3u) + 4 + d8 * 4; ins.size = 4; }
    if (has(k, "b8")) ins.target = uint32_t(int64_t(pc) + 4 + s8(d8) * 2);
    if (has(k, "b12")) ins.target = uint32_t(int64_t(pc) + 4 + s12(word & 0xFFF) * 2);
    return ins;
}

std::optional<uint32_t> FlatImage::literal(const Insn& ins) const {
    if ((ins.is("mov.w") || ins.is("mov.l")) && ins.size && contains(*ins.target, ins.size)) {
        if (ins.size == 2) {
            uint32_t v = u16(*ins.target);
            if (v & 0x8000) v |= 0xFFFF0000u;
            return v;
        }
        return u32(*ins.target);
    }
    return std::nullopt;
}

}  // namespace sf3::gen
