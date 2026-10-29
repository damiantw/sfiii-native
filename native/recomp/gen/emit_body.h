// SF3 recomp, on-console generator: emit.py's decisions (Body, stmt, cycles, contended) shared by the
// C++ printer (emit_cpp.cpp) and the x86-64 backend (emit_x64.cpp) (MIT). Internal header.
#pragma once
#include <algorithm>
#include <fstream>
#include <iterator>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "emit_cpp.h"

namespace sf3::gen {
namespace {

std::string F(const char* f, ...) __attribute__((format(printf, 1, 2)));
std::string F(const char* f, ...) {
    va_list ap, ap2;
    va_start(ap, f);
    va_copy(ap2, ap);
    int n = vsnprintf(nullptr, 0, f, ap);
    va_end(ap);
    std::string s(size_t(n), '\0');
    vsnprintf(s.data(), size_t(n) + 1, f, ap2);
    va_end(ap2);
    return s;
}

std::string fname(uint32_t a) { return F("f_%08X", a); }
std::string H(uint32_t v) { return v > 0xFFFF ? F("0x%08Xu", v) : F("0x%Xu", v); }
std::string R(int n) { return F("c.r[%d]", n); }
std::string plus(const std::string& b, int d) { return d ? F("%s + %d", b.c_str(), d) : b; }

bool in(const char* op, std::initializer_list<const char*> l) {
    for (auto* x : l) if (!strcmp(op, x)) return true;
    return false;
}

const char* LD(int s) { return s == 1 ? "ld8" : s == 2 ? "ld16" : "ld32"; }
const char* ST(int s) { return s == 1 ? "st8" : s == 2 ? "st16" : "st32"; }
std::string ext(int size, const std::string& e) {
    if (size == 1) return "(uint32_t)(int8_t)" + e;
    if (size == 2) return "(uint32_t)(int16_t)" + e;
    return e;
}

struct Unsupported : std::runtime_error { using std::runtime_error::runtime_error; };

std::string mov(const Insn& ins, const std::string& form, int size, const std::optional<uint32_t>& lit) {
    int n = ins.n, m = ins.m, d = ins.disp.value_or(0);
    std::string ld = LD(size), st = ST(size);
    if (form == "@T,Rn") {
        if (lit) return R(n) + " = " + H(*lit) + ";";
        return R(n) + " = " + ext(size, ld + "(" + H(*ins.target) + ")") + ";";
    }
    if (form == "Rm,@Rn") return st + "(" + R(n) + ", " + R(m) + ");";
    if (form == "@Rm,Rn") return R(n) + " = " + ext(size, ld + "(" + R(m) + ")") + ";";
    if (form == "Rm,@-Rn") {
        if (n == m) return F("{ uint32_t v = %s; %s -= %d; %s(%s, v); }", R(m).c_str(), R(n).c_str(), size, st.c_str(), R(n).c_str());
        return F("%s -= %d; %s(%s, %s);", R(n).c_str(), size, st.c_str(), R(n).c_str(), R(m).c_str());
    }
    if (form == "@Rm+,Rn") {
        std::string load = R(n) + " = " + ext(size, ld + "(" + R(m) + ")") + ";";
        return n == m ? load : F("%s %s += %d;", load.c_str(), R(m).c_str(), size);
    }
    if (form == "Rm,@(r0,Rn)") return st + "(c.r[0] + " + R(n) + ", " + R(m) + ");";
    if (form == "@(r0,Rm),Rn") return R(n) + " = " + ext(size, ld + "(c.r[0] + " + R(m) + ")") + ";";
    if (form == "r0,@(disp,Rn)") return st + "(" + plus(R(n), d) + ", c.r[0]);";
    if (form == "@(disp,Rm),r0") return "c.r[0] = " + ext(size, ld + "(" + plus(R(m), d) + ")") + ";";
    if (form == "Rm,@(disp,Rn)") return st + "(" + plus(R(n), d) + ", " + R(m) + ");";
    if (form == "@(disp,Rm),Rn") return R(n) + " = " + ld + "(" + plus(R(m), d) + ");";
    if (form == "r0,@(disp,gbr)") return st + "(" + plus("c.gbr", d) + ", c.r[0]);";
    if (form == "@(disp,gbr),r0") return "c.r[0] = " + ext(size, ld + "(" + plus("c.gbr", d) + ")") + ";";
    throw Unsupported(ins.text());
}

std::string sreg(const std::string& r) {
    if (r == "sr") return "sh2_get_sr(c)";
    return "c." + r;
}

std::string stmt(const Insn& ins, const std::optional<uint32_t>& lit) {
    const char* op = ins.op;
    std::string f(ins.fmt);
    int n = ins.n, m = ins.m;
    size_t sp = f.find(' ');
    std::string form = sp == std::string::npos ? "" : f.substr(sp + 1);
    std::string Rn = n >= 0 ? R(n) : "", Rm = m >= 0 ? R(m) : "";
    const char* rn = Rn.c_str();
    const char* rm = Rm.c_str();
    auto is = [&](const char* o) { return !strcmp(op, o); };
    if (is("nop")) return ";";
    if (is("mov.b")) return mov(ins, form, 1, lit);
    if (is("mov.w")) return mov(ins, form, 2, lit);
    if (is("mov.l")) return mov(ins, form, 4, lit);
    if (is("mov")) return Rn + " = " + (ins.imm ? H(uint32_t(*ins.imm)) : Rm) + ";";
    if (is("mova")) return "c.r[0] = " + H(*ins.target) + ";";
    if (is("movt")) return Rn + " = c.t;";
    if (is("swap.b")) return F("%s = (%s & 0xFFFF0000u) | (%s & 0xFFu) << 8 | (%s >> 8 & 0xFFu);", rn, rm, rm, rm);
    if (is("swap.w")) return F("%s = %s << 16 | %s >> 16;", rn, rm, rm);
    if (is("xtrct")) return F("%s = %s << 16 | %s >> 16;", rn, rm, rn);
    if (is("add")) {
        if (ins.imm) return F("%s %s= %d;", rn, *ins.imm >= 0 ? "+" : "-", abs(*ins.imm));
        return F("%s += %s;", rn, rm);
    }
    if (is("addc")) return F("{ uint64_t s = (uint64_t)%s + %s + c.t; c.t = (uint32_t)(s >> 32); %s = (uint32_t)s; }", rn, rm, rn);
    if (is("addv") || is("subv"))
        return F("{ int64_t s = (int64_t)(int32_t)%s %s (int32_t)%s; c.t = s > INT32_MAX || s < INT32_MIN; %s = (uint32_t)s; }",
                 rn, is("addv") ? "+" : "-", rm, rn);
    if (is("sub")) return F("%s -= %s;", rn, rm);
    if (is("subc")) return F("{ uint32_t a = %s, b = %s, t = c.t; %s = a - b - t; c.t = (uint64_t)a < (uint64_t)b + t; }", rn, rm, rn);
    if (is("neg")) return F("%s = 0u - %s;", rn, rm);
    if (is("negc")) return F("{ uint32_t b = %s, t = c.t; %s = 0u - b - t; c.t = (uint64_t)b + t != 0; }", rm, rn);
    if (is("dt")) return F("%s -= 1; c.t = %s == 0;", rn, rn);
    if (is("exts.b")) return F("%s = (uint32_t)(int32_t)(int8_t)%s;", rn, rm);
    if (is("exts.w")) return F("%s = (uint32_t)(int32_t)(int16_t)%s;", rn, rm);
    if (is("extu.b")) return F("%s = %s & 0xFFu;", rn, rm);
    if (is("extu.w")) return F("%s = %s & 0xFFFFu;", rn, rm);
    if (is("cmp/eq")) {
        if (ins.imm) return "c.t = c.r[0] == " + H(uint32_t(*ins.imm)) + ";";
        return F("c.t = %s == %s;", rn, rm);
    }
    if (is("cmp/hs") || is("cmp/hi")) return F("c.t = %s %s %s;", rn, is("cmp/hs") ? ">=" : ">", rm);
    if (is("cmp/ge") || is("cmp/gt")) return F("c.t = (int32_t)%s %s (int32_t)%s;", rn, is("cmp/ge") ? ">=" : ">", rm);
    if (is("cmp/pz") || is("cmp/pl")) return F("c.t = (int32_t)%s %s 0;", rn, is("cmp/pz") ? ">=" : ">");
    if (is("cmp/str"))
        return F("{ uint32_t x = %s ^ %s; c.t = !(x & 0xFFu) || !(x & 0xFF00u) || !(x & 0xFF0000u) || !(x & 0xFF000000u); }", rn, rm);
    if (is("and") || is("or") || is("xor")) {
        const char* sym = is("and") ? "&" : is("or") ? "|" : "^";
        if (ins.imm) return F("c.r[0] %s= %s;", sym, H(uint32_t(*ins.imm)).c_str());
        return F("%s %s= %s;", rn, sym, rm);
    }
    if (is("tst")) {
        if (ins.imm) return "c.t = (c.r[0] & " + H(uint32_t(*ins.imm)) + ") == 0;";
        return F("c.t = (%s & %s) == 0;", rn, rm);
    }
    if (is("and.b") || is("or.b") || is("xor.b")) {
        const char* sym = is("and.b") ? "&" : is("or.b") ? "|" : "^";
        return F("{ uint32_t a = c.gbr + c.r[0]; st8(a, ld8(a) %s %s); }", sym, H(uint32_t(*ins.imm)).c_str());
    }
    if (is("tst.b")) return "c.t = (ld8(c.gbr + c.r[0]) & " + H(uint32_t(*ins.imm)) + ") == 0;";
    if (is("not")) return F("%s = ~%s;", rn, rm);
    if (is("tas.b")) return F("{ uint32_t a = %s, v = ld8(a); c.t = v == 0; st8(a, v | 0x80u); }", rn);
    if (is("shll") || is("shal")) return F("c.t = %s >> 31; %s <<= 1;", rn, rn);
    if (is("shlr")) return F("c.t = %s & 1; %s >>= 1;", rn, rn);
    if (is("shar")) return F("c.t = %s & 1; %s = (uint32_t)((int32_t)%s >> 1);", rn, rn, rn);
    if (is("shll2") || is("shll8") || is("shll16")) return F("%s <<= %s;", rn, op + 4);
    if (is("shlr2") || is("shlr8") || is("shlr16")) return F("%s >>= %s;", rn, op + 4);
    if (is("rotl")) return F("c.t = %s >> 31; %s = %s << 1 | c.t;", rn, rn, rn);
    if (is("rotr")) return F("c.t = %s & 1; %s = %s >> 1 | c.t << 31;", rn, rn, rn);
    if (is("rotcl")) return F("{ uint32_t t = %s >> 31; %s = %s << 1 | c.t; c.t = t; }", rn, rn, rn);
    if (is("rotcr")) return F("{ uint32_t t = %s & 1; %s = %s >> 1 | c.t << 31; c.t = t; }", rn, rn, rn);
    if (is("mul.l")) return F("c.macl = %s * %s;", rn, rm);
    if (is("muls.w")) return F("c.macl = (uint32_t)((int32_t)(int16_t)%s * (int16_t)%s);", rn, rm);
    if (is("mulu.w")) return F("c.macl = (%s & 0xFFFFu) * (%s & 0xFFFFu);", rn, rm);
    if (is("dmuls.l"))
        return F("{ uint64_t p = (uint64_t)((int64_t)(int32_t)%s * (int32_t)%s); c.mach = (uint32_t)(p >> 32); c.macl = (uint32_t)p; }", rn, rm);
    if (is("dmulu.l"))
        return F("{ uint64_t p = (uint64_t)%s * %s; c.mach = (uint32_t)(p >> 32); c.macl = (uint32_t)p; }", rn, rm);
    if (is("mac.w")) return F("sh2_mac_w(c, %d, %d);", n, m);
    if (is("mac.l")) return F("sh2_mac_l(c, %d, %d);", n, m);
    if (is("clrmac")) return "c.mach = c.macl = 0;";
    if (is("div0u")) return "c.m = c.q = c.t = 0;";
    if (is("div0s")) return F("c.q = %s >> 31; c.m = %s >> 31; c.t = c.q != c.m;", rn, rm);
    if (is("div1")) return F("sh2_div1(c, %s, %s);", rn, rm);
    if (is("clrt")) return "c.t = 0;";
    if (is("sett")) return "c.t = 1;";
    if (is("ldc") || is("ldc.l") || is("lds") || is("lds.l")) {
        std::string reg = form.substr(form.find(',') + 1);
        reg = reg.substr(0, reg.find(','));
        bool l = is("ldc.l") || is("lds.l");
        std::string head = l ? F("uint32_t v = ld32(%s); %s += 4; ", rm, rm) : "", v = l ? "v" : Rm;
        std::string body = reg == "sr" ? "sh2_set_sr(c, " + v + " & 0x3F3u); SH2_SAFE(c);" : "c." + reg + " = " + v + ";";
        return l ? "{ " + head + body + " }" : body;
    }
    if (is("stc") || is("stc.l") || is("sts") || is("sts.l")) {
        std::string reg = form.substr(0, form.find(','));
        if (is("stc.l") || is("sts.l")) return F("%s -= 4; st32(%s, %s);", rn, rn, sreg(reg).c_str());
        return Rn + " = " + sreg(reg) + ";";
    }
    if (is("trapa")) return F("sh2_trapa(c, %d, %s);", *ins.imm, H(ins.pc + 2).c_str());
    if (is("sleep")) return "sh2_sleep(c, " + H(ins.pc) + ");";
    throw Unsupported(ins.text());
}

bool is_branch(const char* op) {
    return in(op, {"bt", "bf", "bt/s", "bf/s", "bra", "bsr", "jmp", "jsr", "braf", "bsrf", "rts", "rte"});
}

std::pair<int, int> cycles(const Insn& ins) {
    const char* op = ins.op;
    static const std::pair<const char*, int> C[] = {
        {"bra", 2}, {"bsr", 2}, {"braf", 2}, {"bsrf", 2}, {"jmp", 2}, {"jsr", 2}, {"rts", 2}, {"rte", 4},
        {"trapa", 8}, {"sleep", 3}, {"and.b", 3}, {"or.b", 3}, {"xor.b", 3}, {"tst.b", 3}, {"tas.b", 4},
        {"mul.l", 2}, {"dmuls.l", 2}, {"dmulu.l", 2}, {"mac.l", 3}, {"mac.w", 3}, {"stc.l", 2}};
    int n = 1;
    for (auto& [o, c] : C) if (!strcmp(o, op)) n = c;
    if (!strcmp(op, "ldc.l")) n = 3;
    int mem = 0;
    if (in(op, {"mov.b", "mov.w", "mov.l", "and.b", "or.b", "xor.b", "tst.b", "tas.b", "ldc.l", "lds.l", "stc.l", "sts.l"})) mem = 1;
    else if (in(op, {"mac.l", "mac.w"})) mem = 2;
    else if (!strcmp(op, "rte")) mem = 2;
    else if (!strcmp(op, "trapa")) mem = 3;
    return {n, mem};
}

int taken(const char* op) { return in(op, {"bt", "bf"}) ? 2 : 1; }

std::string strip(const std::string& s) {
    size_t a = s.find_first_not_of(" \t\n\r\f\v"), b = s.find_last_not_of(" \t\n\r\f\v");
    return a == std::string::npos ? "" : s.substr(a, b - a + 1);
}

// _args: text.split(None, 1)[1], split at commas not inside parentheses (r",(?![^(]*\))"), stripped.
bool space(char ch) { return ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r' || ch == '\f' || ch == '\v'; }

std::vector<std::string> args(const std::string& text) {
    std::vector<std::string> out;
    size_t a = 0;
    while (a < text.size() && space(text[a])) ++a;
    size_t b = a;
    while (b < text.size() && !space(text[b])) ++b;
    while (b < text.size() && space(text[b])) ++b;
    if (b >= text.size()) return out;
    std::string rest = text.substr(b);
    size_t start = 0;
    for (size_t i = 0; i < rest.size(); ++i) {
        if (rest[i] != ',') continue;
        bool inside = false;
        for (size_t j = i + 1; j < rest.size(); ++j) {
            if (rest[j] == '(') break;
            if (rest[j] == ')') { inside = true; break; }
        }
        if (inside) continue;
        out.push_back(strip(rest.substr(start, i - start)));
        start = i + 1;
    }
    out.push_back(strip(rest.substr(start)));
    return out;
}

bool reg_name(const std::string& s) {    // re.fullmatch(r"r\d+", s)
    if (s.size() < 2 || s[0] != 'r') return false;
    for (size_t i = 1; i < s.size(); ++i) if (!isdigit(uint8_t(s[i]))) return false;
    return true;
}

bool word_char(char ch) { return isalnum(uint8_t(ch)) || ch == '_'; }

int parity(uint32_t pc, const char* op, const std::string& text) {
    if (in(op, {"lds.l", "sts.l"})) return (pc & 3) == 0 ? 1 : 0;
    if (in(op, {"ldc.l", "stc.l"}) || (pc & 3) != 2) return 0;
    if (in(op, {"and.b", "or.b", "xor.b", "tst.b", "tas.b", "mac.l", "mac.w"})) return 1;
    if (in(op, {"mov.b", "mov.w", "mov.l"})) {
        auto a = args(text);
        if (a.size() == 2 && (!(a[0].rfind("r", 0) == 0 || a[0].rfind("#", 0) == 0) || a[1].rfind("@", 0) == 0)) return 1;
    }
    return 0;
}

std::string loaded(const char* op, const std::string& text) {
    auto a = args(text);
    if (in(op, {"mov.b", "mov.w", "mov.l"}) && a.size() == 2 && a[0].rfind("@", 0) == 0 && reg_name(a[1])) return a[1];
    return "";
}

bool uses(const char* op, const std::string& text, const std::string& r) {
    auto a = args(text);
    if (in(op, {"mov", "mov.b", "mov.w", "mov.l", "movt", "sts", "stc", "mova", "extu.b", "extu.w", "exts.b", "exts.w",
                "neg", "not", "swap.b", "swap.w"}) && !a.empty() && reg_name(a.back()))
        a.pop_back();
    for (auto& x : a)
        for (size_t p = x.find(r); p != std::string::npos; p = x.find(r, p + 1)) {
            if (p > 0 && word_char(x[p - 1])) continue;
            size_t e = p + r.size();
            if (e < x.size() && isdigit(uint8_t(x[e]))) continue;
            return true;
        }
    return false;
}

int contended(const std::vector<Insn>& seq) {
    int k = 0;
    bool have = false;
    uint32_t ppc = 0;
    const char* pop = nullptr;
    std::string ptext;
    int pci = 0;
    for (size_t n = 0; n < seq.size(); ++n) {
        const Insn& ins = seq[n];
        std::string text = ins.text();
        int ci = parity(ins.pc, ins.op, text);
        if (ci && n + 1 < seq.size() && seq[n + 1].pc == ins.pc + 2 &&
            in(seq[n + 1].op, {"bra", "bsr", "jmp", "jsr", "braf", "bsrf", "rts", "rte"}))
            ci = 0;
        k += ci;
        if (in(ins.op, {"mul.l", "dmuls.l", "dmulu.l"})) k += 1;
        if (!strcmp(ins.op, "tas.b")) k += 7;
        if (have && ppc + 2 == ins.pc && !is_branch(ins.op)) {
            std::string r = loaded(pop, ptext);
            if (!r.empty() && !pci && !ci && uses(ins.op, text, r)) k += 1;
        }
        have = true, ppc = ins.pc, pop = ins.op, ptext = std::move(text), pci = ci;
    }
    return k;
}

using USet = std::unordered_set<uint32_t>;

struct Body {
    const FlatImage& img;
    const EmitFunc& f;
    const USet& entries;
    const USet& vol;
    bool comments, unwind_returns;
    std::set<uint32_t> hooks, stack_return_calls, resume_points, state_points, slots, local_returns;
    USet code;
    std::unordered_map<uint32_t, Insn> ops;
    std::vector<uint32_t> fallback;
    std::vector<std::tuple<uint32_t, size_t, const char*>> locations;

    Body(const FlatImage& img, const EmitFunc& f, const USet& entries, const USet& vol, bool comments,
         std::set<uint32_t> hooks, bool unwind, const std::set<uint32_t>& resume, std::set<uint32_t> src)
        : img(img), f(f), entries(entries), vol(vol), comments(comments), unwind_returns(unwind),
          hooks(std::move(hooks)), stack_return_calls(std::move(src)) {
        code.insert(f.code.begin(), f.code.end());
        if (code.count(f.entry)) resume_points = resume;
        for (uint32_t a : f.code) ops.emplace(a, img.insn(a));
        for (auto& [a, i] : ops) if (i.delay && code.count(a + 2)) slots.insert(a + 2);
        state_points = resume_points;
        if (!resume_points.empty()) {
            state_points.insert(f.entry);
            for (auto& [a, i] : ops)
                if (in(i.op, {"bt", "bf", "bt/s", "bf/s", "bra"}) && i.target && code.count(*i.target) &&
                    *i.target <= a && !slots.count(*i.target))
                    state_points.insert(*i.target);
        }
        for (auto& [a, ins] : ops) {
            auto p = ops.find(a - 2);
            if (ins.is("lds") && ins.fmt == "lds Rm,pr" && ins.m == 0 && p != ops.end() && p->second.is("mova") &&
                code.count(*p->second.target))
                local_returns.insert(*p->second.target);
        }
    }

    std::optional<uint32_t> literal(const Insn& ins) const {
        if ((ins.is("mov.w") || ins.is("mov.l")) && ins.size && !vol.count(*ins.target)) return img.literal(ins);
        return std::nullopt;
    }
    std::string st(const Insn& ins) const { return stmt(ins, literal(ins)); }

    std::string returned() const {
        std::string cases;
        for (uint32_t t : local_returns) {
            if (!cases.empty()) cases += " ";
            cases += F("case %s: SH2_SAFE(c); goto L_%08X;", H(t).c_str(), t);
        }
        return cases.empty() ? "return;" : "switch (c.pc) { " + cases + " default: return; }";
    }
    std::string tail(uint32_t t) const {
        if (entries.count(t)) return fname(t) + "(c); " + returned();
        return "sh2_call(c, " + H(t) + "); " + returned();
    }
    std::string go(uint32_t t, uint32_t src) const {
        if (!code.count(t)) return "{ " + tail(t) + " }";
        if (t <= src) return F("SH2_SAFE(c); goto L_%08X;", t);
        return F("goto L_%08X;", t);
    }
    std::string call(uint32_t t) const {
        if (entries.count(t)) return fname(t) + "(c);";
        return "sh2_call(c, " + H(t) + ");";
    }
    const Target& target(uint32_t a) const {
        auto it = f.targets.find(a);
        if (it == f.targets.end()) throw std::runtime_error(F("no resolved target for %08X", a));
        return it->second;
    }
    std::string dcall(uint32_t a) const {
        std::vector<uint32_t> known;
        for (uint32_t v : target(a).cands) if (entries.count(v)) known.push_back(v);
        if (known.empty()) return "sh2_call(c, x);";
        if (known.size() == 1)
            return "if (x == " + H(known[0]) + ") " + fname(known[0]) + "(c); else sh2_call(c, x);";
        std::string cases;
        for (uint32_t v : known) {
            if (!cases.empty()) cases += " ";
            cases += "case " + H(v) + ": " + fname(v) + "(c); break;";
        }
        return "switch (x) { " + cases + " default: sh2_call(c, x); }";
    }
    std::string djump(uint32_t a) const {
        const Target& t = target(a);
        const std::vector<uint32_t>& cands = t.how == "unresolved" ? fallback : t.cands;
        std::vector<std::string> cases;
        bool back = false;
        std::unordered_set<uint32_t> seen;
        for (uint32_t v : cands) {
            if (!seen.insert(v).second) continue;
            if (code.count(v)) {
                cases.push_back(F("case %s: goto L_%08X;", H(v).c_str(), v));
                back |= v <= a;
            } else if (entries.count(v)) {
                cases.push_back("case " + H(v) + ": " + tail(v));
            }
        }
        if (cases.empty()) return "sh2_call(c, x); " + returned();
        std::string j;
        for (auto& c : cases) { if (!j.empty()) j += " "; j += c; }
        return std::string(back ? "SH2_SAFE(c); " : "") + "switch (x) { " + j + " default: sh2_call(c, x); " + returned() + " }";
    }

    std::set<uint32_t> labels() {
        std::set<uint32_t> out = local_returns;
        out.insert(resume_points.begin(), resume_points.end());
        out.insert(state_points.begin(), state_points.end());
        fallback.clear();
        for (uint32_t a : f.code) if (!slots.count(a)) fallback.push_back(a);
        for (auto& [a, ins] : ops) {
            if (in(ins.op, {"bt", "bf", "bt/s", "bf/s", "bra"}) && ins.target && code.count(*ins.target))
                out.insert(*ins.target);
            else if (f.targets.count(a) && in(ins.op, {"jmp", "braf"})) {
                const Target& t = f.targets.at(a);
                for (uint32_t v : t.how == "unresolved" ? fallback : t.cands) if (code.count(v)) out.insert(v);
            }
        }
        return out;
    }

    // (C++ for the instruction at a, the address it continues at or 0 with has=false)
    std::string insn(uint32_t a, std::optional<uint32_t>& succ) const {
        const Insn& ins = ops.at(a);
        const char* op = ins.op;
        if (hooks.count(a)) {
            if (is_branch(op) || slots.count(a)) throw Unsupported(F("a hook at %08X, on a branch or a delay slot", a));
            succ = a + 2;
            return st(ins) + " sh2_hook(c, " + H(a) + ");";
        }
        if (!is_branch(op)) { succ = a + 2; return st(ins); }
        if (in(op, {"bt", "bf"})) {
            succ = a + 2;
            return F("if (%sc.t) { SH2_CYC(c, %d, 0); %s }", ins.is("bt") ? "" : "!", taken(op), go(*ins.target, a).c_str());
        }
        std::string slot = st(img.insn(a + 2));
        if (slot == ";") slot = "";
        std::string s = slot.empty() ? "" : slot + " ";
        std::string ret = H(a + 4);
        std::string check = unwind_returns ? "if (c.pc != " + ret + ") return;" : "SH2_RET(c, " + ret + ");";
        if (in(op, {"bt/s", "bf/s"})) {
            succ = a + 4;
            return F("{ const bool k = %sc.t; %sif (k) { SH2_CYC(c, %d, 0); %s } }", ins.is("bt/s") ? "" : "!", s.c_str(),
                     taken(op), go(*ins.target, a).c_str());
        }
        if (ins.is("bra")) { succ.reset(); return s + go(*ins.target, a); }
        if (ins.is("bsr")) {
            succ = a + 4;
            return "c.pr = " + ret + "; " + s + "SH2_SAFE(c); " + call(*ins.target) + " " + check;
        }
        if (in(op, {"jsr", "bsrf"})) {
            std::string x = ins.is("jsr") ? R(ins.n) : ret + " + " + R(ins.n);
            succ = a + 4;
            if (stack_return_calls.count(a)) {
                check = "if (c.pc != " + ret + " && c.r[15] == saved_sp + 4u && c.pc == saved_return) return; SH2_RET(c, " + ret + ");";
                return "{ const uint32_t x = " + x + "; const uint32_t saved_sp = c.r[15], saved_return = ld32(saved_sp); c.pr = " +
                       ret + "; " + s + "SH2_SAFE(c); " + dcall(a) + " " + check + " }";
            }
            return "{ const uint32_t x = " + x + "; c.pr = " + ret + "; " + s + "SH2_SAFE(c); " + dcall(a) + " " + check + " }";
        }
        if (in(op, {"jmp", "braf"})) {
            std::string x = ins.is("jmp") ? R(ins.n) : ret + " + " + R(ins.n);
            succ.reset();
            return "{ const uint32_t x = " + x + "; " + s + djump(a) + " }";
        }
        if (ins.is("rts")) {
            std::string cases;
            for (uint32_t t : local_returns) {
                if (!cases.empty()) cases += " ";
                cases += F("case %s: SH2_SAFE(c); goto L_%08X;", H(t).c_str(), t);
            }
            std::string local = cases.empty() ? "" : "switch (x) { " + cases + " default: break; } ";
            succ.reset();
            return "{ const uint32_t x = c.pr; " + s + local + "c.pc = x; return; }";
        }
        if (ins.is("rte")) {
            succ.reset();
            return "{ const uint32_t x = ld32(c.r[15]); c.r[15] += 4; sh2_set_sr(c, ld32(c.r[15]) & 0x3F3u); c.r[15] += 4; " + s +
                   "c.pc = x; return; }";
        }
        throw Unsupported(ins.text());
    }

    std::vector<std::string> emit() {
        std::set<uint32_t> lab = labels();
        std::vector<uint32_t> order;
        for (uint32_t a : f.code) if (!slots.count(a) || lab.count(a) || a == f.entry) order.push_back(a);
        std::vector<std::string> lines{"void " + fname(f.entry) + "(SH2Context& c) {"};
        if (!resume_points.empty()) {
            std::string cases;
            for (uint32_t a : resume_points) {
                if (!cases.empty()) cases += " ";
                cases += F("case %s: goto L_%08X;", H(a).c_str(), a);
            }
            lines = {F("static void body_%08X(SH2Context& c, uint32_t resume) {", f.entry),
                     "    switch (resume) { " + cases + " default: break; }"};
            lab.insert(f.entry);
        }
        if (!order.empty() && order[0] != f.entry) {
            lab.insert(f.entry);
            lines.push_back(F("    goto L_%08X;", f.entry));
        }
        std::set<uint32_t> late;
        bool lead = true;
        std::optional<uint32_t> pointed;
        bool rp = !resume_points.empty();
        for (size_t i = 0; i < order.size(); ++i) {
            uint32_t a = order[i];
            if (lab.count(a) || late.count(a)) {
                lines.push_back(F("L_%08X:", a));
                lead = true;
            }
            if (lead) {
                int cyc = 0, mem = 0;
                std::vector<Insn> seq;
                for (size_t j = i; j < order.size(); ++j) {
                    uint32_t b = order[j];
                    if (b != a && (lab.count(b) || late.count(b))) break;
                    const Insn& insb = ops.at(b);
                    auto [n, m] = cycles(insb);
                    cyc += n, mem += m;
                    seq.push_back(insb);
                    if (insb.delay && code.count(b + 2)) {
                        Insn slot = img.insn(b + 2);
                        auto [n2, m2] = cycles(slot);
                        cyc += n2, mem += m2;
                        seq.push_back(slot);
                    }
                    if (is_branch(insb.op)) break;
                }
                if (rp && state_points.count(a)) {
                    lines.push_back("    SH2_STATE_POINT(c, " + H(a) + ");");
                    pointed = a;
                }
                int cont = contended(seq);
                if (cont) lines.push_back(F("    SH2_CYC2(c, %d, %d, %d);", cyc, mem, cont));
                else lines.push_back(F("    SH2_CYC(c, %d, %d);", cyc, mem));
                lead = false;
            }
            std::optional<uint32_t> succ;
            std::string text = insn(a, succ);
            const Insn& ins = ops.at(a);
            if (comments) {
                std::string note = ins.text();
                if (ins.delay) note += " ; " + img.insn(a + 2).text();
                text += F("  // %08X ", a) + note;
            }
            locations.emplace_back(a, lines.size(), "insn");
            if (ins.delay && code.count(a + 2)) locations.emplace_back(a + 2, lines.size(), "slot");
            if (rp && state_points.count(a) && pointed != a) lines.push_back("    SH2_STATE_POINT(c, " + H(a) + ");");
            lines.push_back("    " + text);
            if (is_branch(ins.op)) lead = true;
            std::optional<uint32_t> nxt;
            if (i + 1 < order.size()) nxt = order[i + 1];
            if (succ && succ != nxt) {
                if (code.count(*succ)) {
                    late.insert(*succ);
                    lines.push_back(F("    goto L_%08X;", *succ));
                } else {
                    lines.push_back("    " + tail(*succ));
                }
            }
        }
        lines.push_back("}");
        if (rp) {
            std::set<uint32_t> all = resume_points;
            all.insert(f.entry);
            for (uint32_t a : all)
                lines.push_back("void " + fname(a) + F("(SH2Context& c) { body_%08X(c, ", f.entry) + H(a) + "); }");
        }
        return lines;
    }
};

bool writes_r0(const Insn& ins) {       // 0 in discover._writes(ins)
    std::string f(ins.fmt);
    auto ends = [&](const char* s) { size_t l = strlen(s); return f.size() >= l && f.compare(f.size() - l, l, s) == 0; };
    std::set<int> out;
    std::string first = f.substr(0, f.find(' '));
    if (ends("Rn") && ins.n >= 0) out.insert(ins.n);
    else if (ends(",r0") || ins.is("mova")) out.insert(0);
    else if (ins.is("movt") || ins.is("dt") || (first == ins.op && ends("Rn"))) out.insert(ins.n);
    if (f.find("@Rm+") != std::string::npos && ins.m >= 0) out.insert(ins.m);
    if (f.find("@-Rn") != std::string::npos && ins.n >= 0) out.insert(ins.n);
    return out.count(0);
}

USet volatile_literals(const FlatImage& img, const std::vector<uint32_t>& prog_code) {
    USet code(prog_code.begin(), prog_code.end());
    std::unordered_map<uint32_t, int> pools;
    USet values;
    for (uint32_t a : prog_code) {
        Insn ins = img.insn(a);
        if (ins.is("mova")) {
            for (uint32_t b = a + 2; b < a + 12; b += 2) {
                if (!code.count(b)) break;
                Insn j = img.insn(b);
                if (j.n == 0 && (j.fmt == "mov.l Rm,@Rn" || j.fmt == "mov.w Rm,@Rn" || j.fmt == "mov.b Rm,@Rn"))
                    values.insert(*ins.target);
                else if (j.n == 0 && (j.fmt == "mov.l Rm,@(disp,Rn)" || j.fmt == "mov.w r0,@(disp,Rn)" || j.fmt == "mov.b r0,@(disp,Rn)"))
                    values.insert(*ins.target + uint32_t(*j.disp));
                if (in(j.op, {"bra", "jmp", "rts", "rte", "braf", "bt", "bf", "bt/s", "bf/s", "jsr", "bsr"}) || writes_r0(j)) break;
            }
        }
        if ((ins.is("mov.w") || ins.is("mov.l")) && ins.size && ins.target) {
            pools[*ins.target] = ins.size;
            if (ins.size == 4) {
                auto v = img.literal(ins);
                if (v) values.insert(*v >> 29 == 1 ? *v & 0x1FFFFFFF : *v);
            }
        }
    }
    USet out;
    for (uint32_t v : values)
        for (uint32_t t : {v, v & ~1u, v & ~3u, (v & ~1u) - 2}) {
            auto p = pools.find(t);
            if (p != pools.end() && t <= v && uint64_t(v) < uint64_t(t) + p->second) out.insert(t);
        }
    return out;
}


struct ModulePlan {
    FlatImage img;
    std::string ns;
    std::vector<uint32_t> primary;                          // function entries, sorted
    std::unordered_map<uint32_t, const EmitFunc*> by_entry;
    std::map<uint32_t, std::set<uint32_t>> resume;          // native-state resume points per function
    std::vector<uint32_t> entries;                          // every exported entry (functions and resume points), sorted
    USet entries_u, vol;
};

// Module.generate's preamble: the image, entries, resume points and volatile literals.
inline ModulePlan plan_module(const EmitBuild& b, const EmitModule& mod) {
    ModulePlan P;
    FlatImage& img = P.img;
    std::string& ns = P.ns;
    auto& primary = P.primary;
    auto& by_entry = P.by_entry;
    auto& resume = P.resume;
    auto& entries = P.entries;
    auto& entries_u = P.entries_u;
    auto& vol = P.vol;
    img.base = mod.base;
    {
        std::ifstream in(mod.path, std::ios::binary);
        if (!in) throw std::runtime_error("cannot read " + mod.path);
        img.data.assign(std::istreambuf_iterator<char>(in), {});
    }
    ns = "p_";
    for (char ch : mod.name) ns += char(tolower(uint8_t(ch)));
    for (auto& f : mod.funcs) { primary.push_back(f.entry); by_entry[f.entry] = &f; }
    std::sort(primary.begin(), primary.end());
    if (b.native_states) {
        std::unordered_set<uint32_t> owned(primary.begin(), primary.end());
        for (uint32_t e : primary) {
            const EmitFunc& fn = *by_entry[e];
            USet code(fn.code.begin(), fn.code.end());
            std::set<uint32_t> points{e};
            USet slots;
            for (uint32_t a : fn.code) if (img.insn(a).delay) slots.insert(a + 2);
            for (uint32_t a : fn.code) {
                Insn ins = img.insn(a);
                if (ins.is("lds") && ins.fmt == "lds Rm,pr" && ins.m == 0 && code.count(a - 2)) {
                    Insn prev = img.insn(a - 2);
                    if (prev.is("mova") && code.count(*prev.target) && !slots.count(*prev.target) && owned.insert(*prev.target).second)
                        points.insert(*prev.target);
                }
                if (in(ins.op, {"bsr", "jsr", "bsrf"}) && code.count(a + 4) && !slots.count(a + 4) && owned.insert(a + 4).second)
                    points.insert(a + 4);
                if (in(ins.op, {"bt", "bf", "bt/s", "bf/s", "bra"}) && ins.target && code.count(*ins.target) && *ins.target <= a &&
                    !slots.count(*ins.target) && owned.insert(*ins.target).second)
                    points.insert(*ins.target);
            }
            resume[e] = std::move(points);
        }
    }
    std::set<uint32_t> eset(primary.begin(), primary.end());
    for (auto& [e, p] : resume) eset.insert(p.begin(), p.end());
    entries.assign(eset.begin(), eset.end());
    entries_u.insert(entries.begin(), entries.end());

    vol = volatile_literals(img, mod.prog_code);
    if (mod.runtime_literals)
        for (uint32_t a : mod.prog_code) {
            Insn ins = img.insn(a);
            if ((ins.is("mov.w") || ins.is("mov.l")) && ins.size) vol.insert(*ins.target);
        }

    return P;
}

}  // namespace
}  // namespace sf3::gen
