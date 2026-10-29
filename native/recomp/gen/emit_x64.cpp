// SF3 recomp, on-console generator: the x86-64 backend (MIT). See emit_x64.h, x64_abi.h.
#include "emit_x64.h"
#include "module_set.h"

#include <array>
#include <filesystem>
#include <fstream>

#include "emit_body.h"
#include "hashes.h"
#include "x64_abi.h"

namespace sf3::gen {
namespace {
using namespace x64;

enum Reg : uint8_t { EAX = 0, ECX = 1, EDX = 2, EBX = 3, ESP = 4, EBP = 5, ESI = 6, EDI = 7 };
int8_t RO(int n) { return int8_t(4 * n); }     // c.r[n]

// A tiny assembler over the cache's code: only the forms the lowering uses. Memory operands are
// [rbx+d8] (SH2Context), [rsp+d8] (scratch) or [r12+d8] (service table).
struct Asm {
    std::vector<uint8_t>& o;
    explicit Asm(std::vector<uint8_t>& o) : o(o) {}
    size_t pos() const { return o.size(); }
    void b(uint8_t v) { o.push_back(v); }
    void d32(uint32_t v) { for (int i = 0; i < 4; ++i) b(uint8_t(v >> (8 * i))); }
    void d64(uint64_t v) { for (int i = 0; i < 8; ++i) b(uint8_t(v >> (8 * i))); }
    void patch32(size_t at, uint32_t v) { for (int i = 0; i < 4; ++i) o[at + i] = uint8_t(v >> (8 * i)); }
    void ctx(uint8_t reg, int8_t d) { b(uint8_t(0x40 | (reg & 7) << 3 | EBX)); b(uint8_t(d)); }   // modrm [rbx+d8]
    void rr(uint8_t reg, uint8_t rm) { b(uint8_t(0xC0 | (reg & 7) << 3 | (rm & 7))); }

    void ld(Reg r, int8_t d) { b(0x8B); ctx(r, d); }                    // mov r32, [rbx+d]
    void st(int8_t d, Reg r) { b(0x89); ctx(r, d); }                    // mov [rbx+d], r32
    void sti(int8_t d, uint32_t v) { b(0xC7); ctx(0, d); d32(v); }      // mov dword [rbx+d], imm32
    void movi(Reg r, uint32_t v) { b(uint8_t(0xB8 + r)); d32(v); }
    void mov(Reg dst, Reg src) { b(0x89); rr(src, dst); }
    // ALU group: 0 add, 1 or, 4 and, 5 sub, 6 xor, 7 cmp
    void alu_mi(int x, int8_t d, uint32_t v) {
        if (int32_t(v) >= -128 && int32_t(v) < 128) { b(0x83); ctx(uint8_t(x), d); b(uint8_t(v)); }
        else { b(0x81); ctx(uint8_t(x), d); d32(v); }
    }
    void alu_ri(int x, Reg r, uint32_t v) {
        if (int32_t(v) >= -128 && int32_t(v) < 128) { b(0x83); rr(uint8_t(x), r); b(uint8_t(v)); }
        else { b(0x81); rr(uint8_t(x), r); d32(v); }
    }
    void alu_mr(int x, int8_t d, Reg r) { b(uint8_t(x * 8 + 1)); ctx(r, d); }     // op [rbx+d], r
    void alu_rm(int x, Reg r, int8_t d) { b(uint8_t(x * 8 + 3)); ctx(r, d); }     // op r, [rbx+d]
    void alu_rr(int x, Reg dst, Reg src) { b(uint8_t(x * 8 + 1)); rr(src, dst); }
    void test_rm(Reg r, int8_t d) { b(0x85); ctx(r, d); }
    void test_mi(int8_t d, uint32_t v) { b(0xF7); ctx(0, d); d32(v); }
    // shift group on [rbx+d]: 0 rol, 1 ror, 4 shl, 5 shr, 7 sar
    void sh_m(int x, int8_t d, int count) {
        if (count == 1) { b(0xD1); ctx(uint8_t(x), d); }
        else { b(0xC1); ctx(uint8_t(x), d); b(uint8_t(count)); }
    }
    void setcc_t(uint8_t cc) {          // c.t = cc ? 1 : 0   (setcc al; movzx eax, al; mov [t], eax)
        b(0x0F); b(uint8_t(0x90 | cc)); rr(0, EAX);
        b(0x0F); b(0xB6); rr(EAX, EAX);
        st(kT, EAX);
    }
    void movsx8(Reg r) { b(0x0F); b(0xBE); rr(r, r); }
    void movsx16(Reg r) { b(0x0F); b(0xBF); rr(r, r); }
    void movzx8(Reg r) { b(0x0F); b(0xB6); rr(r, r); }
    void movzx16(Reg r) { b(0x0F); b(0xB7); rr(r, r); }
    void movsx16m(Reg r, int8_t d) { b(0x0F); b(0xBF); ctx(r, d); }
    void movzx16m(Reg r, int8_t d) { b(0x0F); b(0xB7); ctx(r, d); }
    void imul_rm(Reg r, int8_t d) { b(0x0F); b(0xAF); ctx(r, d); }
    void imul_rr(Reg dst, Reg src) { b(0x0F); b(0xAF); rr(dst, src); }
    void neg(Reg r) { b(0xF7); rr(3, r); }
    void shr(Reg r, int count) { if (count == 1) { b(0xD1); rr(5, r); } else { b(0xC1); rr(5, r); b(uint8_t(count)); } }
    void not_(Reg r) { b(0xF7); rr(2, r); }
    // scratch [rsp+d]
    void sp_st(int8_t d, Reg r) { b(0x89); b(uint8_t(0x44 | (r & 7) << 3)); b(0x24); b(uint8_t(d)); }
    void sp_ld(Reg r, int8_t d) { b(0x8B); b(uint8_t(0x44 | (r & 7) << 3)); b(0x24); b(uint8_t(d)); }
    void sp_cmpi(int8_t d, uint32_t v) { b(0x81); b(0x7C); b(0x24); b(uint8_t(d)); d32(v); }
    // service table
    void svc(int slot) { b(0x41); b(0xFF); b(0x54); b(0x24); b(uint8_t(slot)); }        // call [r12+slot]
    void tbl(Reg r, int slot) {                                                           // mov r64, [r12+slot]
        b(0x49); b(0x8B);
        if (slot < 128) { b(uint8_t(0x44 | r << 3)); b(0x24); b(uint8_t(slot)); }
        else { b(uint8_t(0x84 | r << 3)); b(0x24); d32(uint32_t(slot)); }
    }
    void svc_ptr(int slot) { tbl(EAX, slot); }                                            // mov rax, [r12+slot]
    void arg_c() { b(0x48); b(0x89); b(0xDF); }                                            // mov rdi, rbx
    void prologue() {
        b(0x53); b(0x41); b(0x54); b(0x48); b(0x83); b(0xEC); b(40); b(0x48); b(0x89); b(0xFB);
    }
    void epilogue() { b(0x48); b(0x83); b(0xC4); b(40); b(0x41); b(0x5C); b(0x5B); b(0xC3); }
    size_t jcc32(uint8_t cc) { b(0x0F); b(uint8_t(0x80 | cc)); d32(0); return pos() - 4; }
    size_t jmp32() { b(0xE9); d32(0); return pos() - 4; }
    size_t call32() { b(0xE8); d32(0); return pos() - 4; }
    size_t jcc8(uint8_t cc) { b(uint8_t(0x70 | cc)); b(0); return pos() - 1; }
    void here8(size_t at) {
        size_t d = pos() - (at + 1);
        if (d > 127) throw std::runtime_error("x64: short jump too far");
        o[at] = uint8_t(d);
    }
    void here32(size_t at) { patch32(at, uint32_t(pos() - (at + 4))); }
};
// condition codes
enum CC : uint8_t { cB = 2, cAE = 3, cE = 4, cNE = 5, cA = 7, cL = 0xC, cGE = 0xD, cG = 0xF };

int8_t sreg_off(const std::string& r) {
    if (r == "gbr") return kGbr;
    if (r == "vbr") return kVbr;
    if (r == "mach") return kMach;
    if (r == "macl") return kMacl;
    if (r == "pr") return kPr;
    throw std::runtime_error("x64: no register " + r);
}

struct Lower {
    const Body& B;
    Asm& a;
    Cache& cache;
    std::unordered_map<uint32_t, size_t> labels;                       // this function's L_ labels
    std::vector<std::pair<size_t, uint32_t>> label_fix;                // rel32 at, label
    std::vector<std::pair<size_t, uint32_t>>& entry_fix;               // rel32 at, entry (module-wide)

    void jmp_label(uint32_t t) { label_fix.emplace_back(a.jmp32(), t); }
    void jcc_label(uint8_t cc, uint32_t t) { label_fix.emplace_back(a.jcc32(cc), t); }

    void safe() {                                                     // SH2_SAFE(c)
        a.b(0x83); a.ctx(7, kBudget); a.b(0);                         // cmp dword [budget], 0
        size_t j = a.jcc8(cGE);
        a.arg_c(); a.svc(sPoll);
        a.here8(j);
    }
    void cyc(int n, int m, int k) {                                   // SH2_CYC / SH2_CYC2
        if (!m && !k) { a.alu_mi(5, kBudget, uint32_t(n * 4)); return; }
        // without the bus model: budget -= n*4 + m*g_sh2_mem_q (k counts only with it)
        a.tbl(EAX, sBus); a.b(0x80); a.b(0x38); a.b(0x00);           // cmp byte [rax], 0
        size_t slow = a.jcc8(cNE);
        a.tbl(EAX, sMemQ); a.b(0x69); a.b(0x00); a.d32(uint32_t(m));  // imul eax, [rax], m
        a.b(0x05); a.d32(uint32_t(n * 4));                            // add eax, n*4
        a.alu_mr(5, kBudget, EAX);                                    // sub [budget], eax
        a.b(0xEB); a.b(0); size_t done = a.pos() - 1;                // jmp rel8
        a.here8(slow);
        a.arg_c(); a.movi(ESI, uint32_t(n)); a.movi(EDX, uint32_t(m)); a.movi(ECX, uint32_t(k)); a.svc(sCyc);
        a.here8(done);
    }
    void state_point(uint32_t pc) {                                    // SH2_STATE_POINT(c, pc)
        a.svc_ptr(sStateReq);
        a.b(0x80); a.b(0x38); a.b(0x00);                              // cmp byte [rax], 0
        size_t j = a.jcc8(cE);
        a.arg_c(); a.movi(ESI, pc); a.svc(sStatePoint);
        a.here8(j);
    }
    void call_entry(uint32_t t) { a.arg_c(); entry_fix.emplace_back(a.call32(), t); }   // f_t(c)
    void call_sh2(uint32_t t) { a.arg_c(); a.movi(ESI, t); a.svc(sCall); }              // sh2_call(c, t)
    void call_sh2_x() { a.arg_c(); a.sp_ld(ESI, 0); a.svc(sCall); }                     // sh2_call(c, x)
    void ret_check(uint32_t ret) {                                     // SH2_RET or the unwind check
        a.alu_mi(7, kPc, ret);
        size_t j = a.jcc8(cE);
        if (B.unwind_returns) a.epilogue();
        else { a.arg_c(); a.movi(ESI, ret); a.svc(sBadReturn); }
        a.here8(j);
    }
    void local_switch(bool from_pc) {          // case t: SH2_SAFE(c); goto L_t; for each local return
        for (uint32_t t : B.local_returns) {
            if (from_pc) a.alu_mi(7, kPc, t);
            else a.sp_cmpi(0, t);
            size_t j = a.jcc32(cNE);
            safe();
            jmp_label(t);
            a.here32(j);
        }
    }
    void returned() { local_switch(true); a.epilogue(); }
    void tail(uint32_t t) {
        if (B.entries.count(t)) call_entry(t);
        else call_sh2(t);
        returned();
    }
    void go(uint32_t t, uint32_t src) {
        if (!B.code.count(t)) { tail(t); return; }
        if (t <= src) safe();
        jmp_label(t);
    }
    void call(uint32_t t) {
        if (B.entries.count(t)) call_entry(t);
        else call_sh2(t);
    }
    void dcall(uint32_t at) {
        std::vector<uint32_t> known;
        for (uint32_t v : B.target(at).cands)
            if (B.entries.count(v) && std::find(known.begin(), known.end(), v) == known.end()) known.push_back(v);
        std::vector<size_t> done;
        for (uint32_t v : known) {
            a.sp_cmpi(0, v);
            size_t j = a.jcc32(cNE);
            call_entry(v);
            done.push_back(a.jmp32());
            a.here32(j);
        }
        call_sh2_x();
        for (size_t d : done) a.here32(d);
    }
    void djump(uint32_t at) {
        const Target& t = B.target(at);
        const std::vector<uint32_t>& cands = t.how == "unresolved" ? B.fallback : t.cands;
        std::vector<uint32_t> gotos, tails;
        bool back = false;
        std::unordered_set<uint32_t> seen;
        for (uint32_t v : cands) {
            if (!seen.insert(v).second) continue;
            if (B.code.count(v)) gotos.push_back(v), back |= v <= at;
            else if (B.entries.count(v)) tails.push_back(v);
        }
        if (gotos.empty() && tails.empty()) { call_sh2_x(); returned(); return; }
        if (back) safe();
        a.sp_ld(EAX, 0);
        for (uint32_t v : gotos) { a.alu_ri(7, EAX, v); jcc_label(cE, v); }
        for (uint32_t v : tails) {
            a.sp_cmpi(0, v);
            size_t j = a.jcc32(cNE);
            tail(v);
            a.here32(j);
        }
        call_sh2_x();
        returned();
    }

    // ---- one non-branch instruction: emit.py's stmt -------------------------------------------
    // ldN/stN: high work RAM inline (no bus model, no --watch), everything else through the service.
    void wram_h_check(bool store) {                                   // jumps (rel32) to the slow path
        a.b(0x89); a.b(0xF8);                                         // mov eax, edi
        a.b(0x25); a.d32(0xDFF00000u);                                // and eax, 0xDFF00000
        a.b(0x3D); a.d32(0x06000000u);                                // cmp eax, 0x06000000
        size_t j1 = a.jcc8(cNE);
        a.tbl(EAX, sBus); a.b(0x80); a.b(0x38); a.b(0x00);           // cmp byte [rax], 0
        size_t j2 = a.jcc8(cNE), j3 = 0;
        if (store) { a.tbl(EAX, sWatchLen); a.b(0x83); a.b(0x38); a.b(0x00); j3 = a.jcc8(cNE); }   // cmp dword [rax], 0
        a.b(0x89); a.b(0xF8); a.b(0x25); a.d32(0xFFFFFu);             // eax = edi & 0xFFFFF
        a.tbl(ECX, sWramH);                                           // rcx = g_wram_h
        fast_slow = {j1, j2, j3};
    }
    std::array<size_t, 3> fast_slow{};
    void fast_end(int slot) {
        a.b(0xEB); a.b(0); size_t done = a.pos() - 1;
        for (size_t j : fast_slow) if (j) a.here8(j);
        a.svc(slot);
        a.here8(done);
    }
    void ldm(int size) {                                              // eax = ld(edi)
        wram_h_check(false);
        if (size == 4) { a.b(0x8B); a.b(0x04); a.b(0x01); a.b(0x0F); a.b(0xC8); }                    // mov eax,[rcx+rax]; bswap
        else if (size == 2) { a.b(0x0F); a.b(0xB7); a.b(0x04); a.b(0x01); a.b(0x66); a.b(0xC1); a.b(0xC0); a.b(8); }  // movzx; rol ax,8
        else { a.b(0x0F); a.b(0xB6); a.b(0x04); a.b(0x01); }                                          // movzx eax, byte
        fast_end(size == 1 ? sLd8 : size == 2 ? sLd16 : sLd32);
    }
    void stm(int size) {                                              // st(edi, esi)
        wram_h_check(true);
        if (size == 4) { a.b(0x89); a.b(0xF2); a.b(0x0F); a.b(0xCA); a.b(0x89); a.b(0x14); a.b(0x01); }  // edx=bswap esi; mov [rcx+rax],edx
        else if (size == 2) { a.b(0x89); a.b(0xF2); a.b(0x66); a.b(0xC1); a.b(0xC2); a.b(8); a.b(0x66); a.b(0x89); a.b(0x14); a.b(0x01); }
        else { a.b(0x40); a.b(0x88); a.b(0x34); a.b(0x01); }                                          // mov [rcx+rax], sil
        fast_end(size == 1 ? sSt8 : size == 2 ? sSt16 : sSt32);
    }
    void ext(int size) { if (size == 1) a.movsx8(EAX); else if (size == 2) a.movsx16(EAX); }
    void addr(int8_t base, int d) { a.ld(EDI, base); if (d) a.alu_ri(0, EDI, uint32_t(d)); }
    void rare(Rare k, uint32_t n, uint32_t m, uint32_t imm) {
        a.arg_c(); a.movi(ESI, k); a.movi(EDX, n); a.movi(ECX, m);
        a.b(0x41); a.b(0xB8); a.d32(imm);                             // mov r8d, imm
        a.svc(sRare);
    }

    void mov(const Insn& ins, const std::string& form, int size, const std::optional<uint32_t>& lit) {
        int n = ins.n, m = ins.m, d = ins.disp.value_or(0);
        if (form == "@T,Rn") {
            if (lit) { a.sti(RO(n), *lit); return; }
            a.movi(EDI, *ins.target); ldm(size); ext(size); a.st(RO(n), EAX); return;
        }
        if (form == "Rm,@Rn") { a.ld(EDI, RO(n)); a.ld(ESI, RO(m)); stm(size); return; }
        if (form == "@Rm,Rn") { a.ld(EDI, RO(m)); ldm(size); ext(size); a.st(RO(n), EAX); return; }
        if (form == "Rm,@-Rn") {
            a.ld(ESI, RO(m)); a.alu_mi(5, RO(n), uint32_t(size)); a.ld(EDI, RO(n));   // v read first (n == m)
            stm(size); return;
        }
        if (form == "@Rm+,Rn") {
            a.ld(EDI, RO(m)); ldm(size); ext(size); a.st(RO(n), EAX);
            if (n != m) a.alu_mi(0, RO(m), uint32_t(size));
            return;
        }
        if (form == "Rm,@(r0,Rn)") { a.ld(EDI, RO(0)); a.alu_rm(0, EDI, RO(n)); a.ld(ESI, RO(m)); stm(size); return; }
        if (form == "@(r0,Rm),Rn") { a.ld(EDI, RO(0)); a.alu_rm(0, EDI, RO(m)); ldm(size); ext(size); a.st(RO(n), EAX); return; }
        if (form == "r0,@(disp,Rn)") { addr(RO(n), d); a.ld(ESI, RO(0)); stm(size); return; }
        if (form == "@(disp,Rm),r0") { addr(RO(m), d); ldm(size); ext(size); a.st(RO(0), EAX); return; }
        if (form == "Rm,@(disp,Rn)") { addr(RO(n), d); a.ld(ESI, RO(m)); stm(size); return; }
        if (form == "@(disp,Rm),Rn") { addr(RO(m), d); ldm(size); a.st(RO(n), EAX); return; }
        if (form == "r0,@(disp,gbr)") { addr(kGbr, d); a.ld(ESI, RO(0)); stm(size); return; }
        if (form == "@(disp,gbr),r0") { addr(kGbr, d); ldm(size); ext(size); a.st(RO(0), EAX); return; }
        throw Unsupported(ins.text());
    }

    void stmt(const Insn& ins, const std::optional<uint32_t>& lit) {
        const char* op = ins.op;
        std::string f(ins.fmt);
        int n = ins.n, m = ins.m;
        size_t sp = f.find(' ');
        std::string form = sp == std::string::npos ? "" : f.substr(sp + 1);
        auto is = [&](const char* o) { return !strcmp(op, o); };
        uint32_t un = uint32_t(n), um = uint32_t(m), imm = ins.imm ? uint32_t(*ins.imm) : 0;
        if (is("nop")) return;
        if (is("mov.b")) return mov(ins, form, 1, lit);
        if (is("mov.w")) return mov(ins, form, 2, lit);
        if (is("mov.l")) return mov(ins, form, 4, lit);
        if (is("mov")) {
            if (ins.imm) a.sti(RO(n), imm);
            else { a.ld(EAX, RO(m)); a.st(RO(n), EAX); }
            return;
        }
        if (is("mova")) { a.sti(RO(0), *ins.target); return; }
        if (is("movt")) { a.ld(EAX, kT); a.st(RO(n), EAX); return; }
        if (is("swap.b")) return rare(rSwapB, un, um, 0);
        if (is("swap.w")) return rare(rSwapW, un, um, 0);
        if (is("xtrct")) return rare(rXtrct, un, um, 0);
        if (is("add")) {
            if (ins.imm) a.alu_mi(0, RO(n), imm);
            else { a.ld(EAX, RO(m)); a.alu_mr(0, RO(n), EAX); }
            return;
        }
        if (is("addc") || is("subc")) {      // CF = t; rn = rn +/- rm +/- CF; t = carry/borrow
            a.ld(ECX, kT); a.shr(ECX, 1); a.ld(EAX, RO(n)); a.alu_rm(is("addc") ? 2 : 3, EAX, RO(m)); a.st(RO(n), EAX);
            a.setcc_t(cB);
            return;
        }
        if (is("addv")) return rare(rAddv, un, um, 0);
        if (is("subv")) return rare(rSubv, un, um, 0);
        if (is("sub")) { a.ld(EAX, RO(m)); a.alu_mr(5, RO(n), EAX); return; }
        if (is("neg")) { a.ld(EAX, RO(m)); a.neg(EAX); a.st(RO(n), EAX); return; }
        if (is("negc")) return rare(rNegc, un, um, 0);
        if (is("dt")) { a.alu_mi(5, RO(n), 1); a.setcc_t(cE); return; }
        if (is("exts.b") || is("exts.w") || is("extu.b") || is("extu.w")) {
            a.ld(EAX, RO(m));
            if (is("exts.b")) a.movsx8(EAX);
            else if (is("exts.w")) a.movsx16(EAX);
            else if (is("extu.b")) a.movzx8(EAX);
            else a.movzx16(EAX);
            a.st(RO(n), EAX);
            return;
        }
        if (is("cmp/eq")) {
            if (ins.imm) a.alu_mi(7, RO(0), imm);
            else { a.ld(EAX, RO(n)); a.alu_rm(7, EAX, RO(m)); }
            a.setcc_t(cE);
            return;
        }
        if (is("cmp/hs") || is("cmp/hi") || is("cmp/ge") || is("cmp/gt")) {
            a.ld(EAX, RO(n)); a.alu_rm(7, EAX, RO(m));
            a.setcc_t(is("cmp/hs") ? cAE : is("cmp/hi") ? cA : is("cmp/ge") ? cGE : cG);
            return;
        }
        if (is("cmp/pz") || is("cmp/pl")) { a.alu_mi(7, RO(n), 0); a.setcc_t(is("cmp/pz") ? cGE : cG); return; }
        if (is("cmp/str")) return rare(rCmpStr, un, um, 0);
        if (is("and") || is("or") || is("xor")) {
            int x = is("and") ? 4 : is("or") ? 1 : 6;
            if (ins.imm) a.alu_mi(x, RO(0), imm);
            else { a.ld(EAX, RO(m)); a.alu_mr(x, RO(n), EAX); }
            return;
        }
        if (is("tst")) {
            if (ins.imm) a.test_mi(RO(0), imm);
            else { a.ld(EAX, RO(n)); a.test_rm(EAX, RO(m)); }
            a.setcc_t(cE);
            return;
        }
        if (is("and.b")) return rare(rAndB, 0, 0, imm);
        if (is("or.b")) return rare(rOrB, 0, 0, imm);
        if (is("xor.b")) return rare(rXorB, 0, 0, imm);
        if (is("tst.b")) return rare(rTstB, 0, 0, imm);
        if (is("not")) { a.ld(EAX, RO(m)); a.not_(EAX); a.st(RO(n), EAX); return; }
        if (is("tas.b")) return rare(rTasB, un, 0, 0);
        if (is("shll") || is("shal")) { a.sh_m(4, RO(n), 1); a.setcc_t(cB); return; }
        if (is("shlr")) { a.sh_m(5, RO(n), 1); a.setcc_t(cB); return; }
        if (is("shar")) { a.sh_m(7, RO(n), 1); a.setcc_t(cB); return; }
        if (is("shll2") || is("shll8") || is("shll16")) { a.sh_m(4, RO(n), atoi(op + 4)); return; }
        if (is("shlr2") || is("shlr8") || is("shlr16")) { a.sh_m(5, RO(n), atoi(op + 4)); return; }
        if (is("rotl")) { a.sh_m(0, RO(n), 1); a.setcc_t(cB); return; }
        if (is("rotr")) { a.sh_m(1, RO(n), 1); a.setcc_t(cB); return; }
        if (is("rotcl") || is("rotcr")) {    // CF = t; rcl/rcr rn, 1; t = CF
            a.ld(ECX, kT); a.shr(ECX, 1); a.b(0xD1); a.ctx(is("rotcl") ? 2 : 3, RO(n)); a.setcc_t(cB);
            return;
        }
        if (is("mul.l")) { a.ld(EAX, RO(n)); a.imul_rm(EAX, RO(m)); a.st(kMacl, EAX); return; }
        if (is("muls.w")) { a.movsx16m(EAX, RO(n)); a.movsx16m(ECX, RO(m)); a.imul_rr(EAX, ECX); a.st(kMacl, EAX); return; }
        if (is("mulu.w")) { a.movzx16m(EAX, RO(n)); a.movzx16m(ECX, RO(m)); a.imul_rr(EAX, ECX); a.st(kMacl, EAX); return; }
        if (is("dmuls.l") || is("dmulu.l")) {   // edx:eax = rn * [rm]
            a.ld(EAX, RO(n)); a.b(0xF7); a.ctx(is("dmuls.l") ? 5 : 4, RO(m)); a.st(kMacl, EAX); a.st(kMach, EDX);
            return;
        }
        if (is("mac.w")) return rare(rMacW, un, um, 0);
        if (is("mac.l")) return rare(rMacL, un, um, 0);
        if (is("clrmac")) { a.sti(kMach, 0); a.sti(kMacl, 0); return; }
        if (is("div0u")) { a.sti(kM, 0); a.sti(kQ, 0); a.sti(kT, 0); return; }
        if (is("div0s")) {                   // q = rn>>31; m = rm>>31; t = q != m
            a.ld(EAX, RO(n)); a.shr(EAX, 31); a.st(kQ, EAX); a.ld(ECX, RO(m)); a.shr(ECX, 31); a.st(kM, ECX);
            a.alu_rr(7, EAX, ECX); a.setcc_t(cNE);
            return;
        }
        if (is("div1")) {                    // sh2_div1: q' = q ^ tmp1 ^ m, t = !(q ^ tmp1)
            a.ld(EDX, kQ);                                            // old q
            a.ld(EAX, RO(n)); a.mov(ECX, EAX); a.shr(ECX, 31); a.st(kQ, ECX);
            a.alu_rr(0, EAX, EAX); a.alu_rm(1, EAX, kT); a.st(RO(n), EAX);
            a.ld(ESI, RO(m));                                         // after the write: n == m reads the new rn
            a.alu_rm(7, EDX, kM);
            size_t j = a.jcc8(cNE);
            a.alu_rr(5, EAX, ESI);                                    // sub: CF = borrow
            a.b(0xEB); a.b(0); size_t k = a.pos() - 1;
            a.here8(j);
            a.alu_rr(0, EAX, ESI);                                    // add: CF = carry
            a.here8(k);
            a.b(0x0F); a.b(0x92); a.rr(0, EDX); a.movzx8(EDX);        // edx = tmp1
            a.st(RO(n), EAX);
            a.alu_rm(6, EDX, kQ); a.mov(EAX, EDX); a.alu_rm(6, EAX, kM); a.st(kQ, EAX);
            a.alu_ri(6, EDX, 1); a.st(kT, EDX);
            return;
        }
        if (is("clrt")) { a.sti(kT, 0); return; }
        if (is("sett")) { a.sti(kT, 1); return; }
        if (is("ldc") || is("ldc.l") || is("lds") || is("lds.l")) {
            std::string reg = form.substr(form.find(',') + 1);
            reg = reg.substr(0, reg.find(','));
            bool l = is("ldc.l") || is("lds.l");
            if (l) { a.ld(EDI, RO(m)); ldm(4); a.alu_mi(0, RO(m), 4); }
            else a.ld(EAX, RO(m));
            if (reg == "sr") {
                a.mov(ESI, EAX); a.alu_ri(4, ESI, 0x3F3u); a.arg_c(); a.svc(sSetSr);
                safe();
            } else {
                a.st(sreg_off(reg), EAX);
            }
            return;
        }
        if (is("stc") || is("stc.l") || is("sts") || is("sts.l")) {
            std::string reg = form.substr(0, form.find(','));
            bool l = is("stc.l") || is("sts.l");
            if (l) a.alu_mi(5, RO(n), 4);
            if (reg == "sr") { a.arg_c(); a.svc(sGetSr); }
            else a.ld(EAX, sreg_off(reg));
            if (l) { a.mov(ESI, EAX); a.ld(EDI, RO(n)); stm(4); }
            else a.st(RO(n), EAX);
            return;
        }
        if (is("trapa")) return rare(rTrapa, ins.pc + 2, 0, imm);
        if (is("sleep")) return rare(rSleep, ins.pc, 0, 0);
        throw Unsupported(ins.text());
    }
    void st(const Insn& ins) { stmt(ins, B.literal(ins)); }

    // ---- one instruction (Body::insn) ------------------------------------------------------
    void insn(uint32_t at, std::optional<uint32_t>& succ) {
        const Insn& ins = B.ops.at(at);
        const char* op = ins.op;
        if (B.hooks.count(at)) {
            if (is_branch(op) || B.slots.count(at)) throw Unsupported(F("a hook at %08X, on a branch or a delay slot", at));
            succ = at + 2;
            st(ins);
            a.arg_c(); a.movi(ESI, at); a.svc(sHook);
            return;
        }
        if (!is_branch(op)) { succ = at + 2; st(ins); return; }
        if (in(op, {"bt", "bf"})) {
            succ = at + 2;
            a.alu_mi(7, kT, 0);
            size_t j = a.jcc32(ins.is("bt") ? cE : cNE);
            cyc(taken(op), 0, 0);
            go(*ins.target, at);
            a.here32(j);
            return;
        }
        Insn slot = B.img.insn(at + 2);
        uint32_t ret = at + 4;
        if (in(op, {"bt/s", "bf/s"})) {
            succ = at + 4;
            a.ld(EAX, kT); a.sp_st(0, EAX);
            st(slot);
            a.sp_cmpi(0, 0);
            size_t j = a.jcc32(ins.is("bt/s") ? cE : cNE);
            cyc(taken(op), 0, 0);
            go(*ins.target, at);
            a.here32(j);
            return;
        }
        if (ins.is("bra")) { succ.reset(); st(slot); go(*ins.target, at); return; }
        if (ins.is("bsr")) {
            succ = at + 4;
            a.sti(kPr, ret); st(slot); safe(); call(*ins.target); ret_check(ret);
            return;
        }
        if (in(op, {"jsr", "bsrf"})) {
            succ = at + 4;
            a.ld(EAX, RO(ins.n));
            if (ins.is("bsrf")) a.alu_ri(0, EAX, ret);
            a.sp_st(0, EAX);
            bool src = B.stack_return_calls.count(at);
            if (src) {                                       // saved_sp = r15, saved_return = ld32(saved_sp)
                a.ld(EDI, RO(15)); a.sp_st(4, EDI); ldm(4); a.sp_st(8, EAX);
            }
            a.sti(kPr, ret); st(slot); safe(); dcall(at);
            if (src) {   // if (c.pc != ret && c.r[15] == saved_sp + 4u && c.pc == saved_return) return;
                a.alu_mi(7, kPc, ret);
                size_t j1 = a.jcc32(cE);
                a.sp_ld(EAX, 4); a.alu_ri(0, EAX, 4); a.alu_rm(7, EAX, RO(15));
                size_t j2 = a.jcc32(cNE);
                a.sp_ld(EAX, 8); a.alu_rm(7, EAX, kPc);
                size_t j3 = a.jcc32(cNE);
                a.epilogue();
                a.here32(j1); a.here32(j2); a.here32(j3);
                a.alu_mi(7, kPc, ret);
                size_t j = a.jcc8(cE);
                a.arg_c(); a.movi(ESI, ret); a.svc(sBadReturn);
                a.here8(j);
            } else {
                ret_check(ret);
            }
            return;
        }
        if (in(op, {"jmp", "braf"})) {
            succ.reset();
            a.ld(EAX, RO(ins.n));
            if (ins.is("braf")) a.alu_ri(0, EAX, ret);
            a.sp_st(0, EAX);
            st(slot);
            djump(at);
            return;
        }
        if (ins.is("rts")) {
            succ.reset();
            a.ld(EAX, kPr); a.sp_st(0, EAX);
            st(slot);
            local_switch(false);
            a.sp_ld(EAX, 0); a.st(kPc, EAX);
            a.epilogue();
            return;
        }
        if (ins.is("rte")) {
            succ.reset();
            a.ld(EDI, RO(15)); ldm(4); a.sp_st(0, EAX);
            a.alu_mi(0, RO(15), 4);
            a.ld(EDI, RO(15)); ldm(4); a.mov(ESI, EAX); a.alu_ri(4, ESI, 0x3F3u); a.arg_c(); a.svc(sSetSr);
            a.alu_mi(0, RO(15), 4);
            st(slot);
            a.sp_ld(EAX, 0); a.st(kPc, EAX);
            a.epilogue();
            return;
        }
        throw Unsupported(ins.text());
    }

    // ---- the function (Body::emit) -----------------------------------------------------------
    void body() {
        Body& b = const_cast<Body&>(B);
        std::set<uint32_t> lab = b.labels();
        const EmitFunc& f = B.f;
        std::vector<uint32_t> order;
        for (uint32_t x : f.code) if (!B.slots.count(x) || lab.count(x) || x == f.entry) order.push_back(x);
        lab.insert(f.entry);                         // the entry stubs jump to L_entry
        std::set<uint32_t> late;
        bool lead = true;
        std::optional<uint32_t> pointed;
        bool rp = !B.resume_points.empty();
        for (size_t i = 0; i < order.size(); ++i) {
            uint32_t x = order[i];
            if (lab.count(x) || late.count(x)) { labels[x] = a.pos(); lead = true; }
            if (lead) {
                int cy = 0, mem = 0;
                std::vector<Insn> seq;
                for (size_t j = i; j < order.size(); ++j) {
                    uint32_t y = order[j];
                    if (y != x && (lab.count(y) || late.count(y))) break;
                    const Insn& iy = B.ops.at(y);
                    auto [n, m] = cycles(iy);
                    cy += n, mem += m;
                    seq.push_back(iy);
                    if (iy.delay && B.code.count(y + 2)) {
                        Insn s = B.img.insn(y + 2);
                        auto [n2, m2] = cycles(s);
                        cy += n2, mem += m2;
                        seq.push_back(s);
                    }
                    if (is_branch(iy.op)) break;
                }
                if (rp && B.state_points.count(x)) { state_point(x); pointed = x; }
                cyc(cy, mem, contended(seq));
                lead = false;
            }
            const Insn& ins = B.ops.at(x);
            if (rp && B.state_points.count(x) && pointed != x) state_point(x);
            std::optional<uint32_t> succ;
            insn(x, succ);
            if (is_branch(ins.op)) lead = true;
            std::optional<uint32_t> nxt;
            if (i + 1 < order.size()) nxt = order[i + 1];
            if (succ && succ != nxt) {
                if (B.code.count(*succ)) { late.insert(*succ); jmp_label(*succ); }
                else tail(*succ);
            }
        }
        // falling off the end of the body (C++: the closing brace) returns; a function with no code is only that
        if (order.empty()) labels[f.entry] = a.pos();
        a.epilogue();
        for (auto& [at, t] : label_fix) {
            auto it = labels.find(t);
            if (it == labels.end()) throw std::runtime_error(F("x64: no label L_%08X in f_%08X", t, B.f.entry));
            a.patch32(at, uint32_t(it->second - (at + 4)));
        }
    }
};

void entry_stub(Asm& a, Cache& c, uint32_t ran_index) {
    a.prologue();
    a.b(0x49); a.b(0xBC);                                    // movabs r12, <Table>
    c.relocs.push_back({uint32_t(a.pos()), Service::Table});
    a.d64(0);
    a.b(0x48); a.b(0xB8);                                    // movabs rax, <ModuleRan> + index
    c.relocs.push_back({uint32_t(a.pos()), Service::ModuleRan});
    a.d64(ran_index);
    a.b(0xC6); a.b(0x00); a.b(0x01);                         // mov byte [rax], 1
}

void write_file(const std::string& path, const std::string& text) {
    std::ofstream o(path, std::ios::binary);
    o << text;
    if (!o) throw std::runtime_error("cannot write " + path);
}

}  // namespace

X64Module emit_x64_module(const EmitBuild& b, const EmitModule& mod) {
    ModulePlan P = plan_module(b, mod);
    X64Module out;
    out.name = mod.name, out.ns = P.ns, out.entries = P.entries, out.callable_entry = mod.callable_entry;
    for (uint32_t e : P.entries) {
        auto it = P.by_entry.find(e);
        out.sizes.push_back(it == P.by_entry.end() ? uint16_t(0) : uint16_t(it->second->code.size()));
    }
    Cache& c = out.cache;
    c.h.backend = 2, c.h.image_base = mod.base, c.h.image_size = uint32_t(P.img.data.size());
    c.h.image_crc = crc32(P.img.data.data(), P.img.data.size());
    Asm a(c.code);
    std::unordered_map<uint32_t, size_t> entry_off;
    std::vector<std::pair<size_t, uint32_t>> entry_fix;
    static const std::set<uint32_t> none;
    for (uint32_t e : P.primary) {
        size_t i = size_t(std::lower_bound(P.entries.begin(), P.entries.end(), e) - P.entries.begin());
        const EmitFunc& fn = *P.by_entry.at(e);
        std::set<uint32_t> hooks;
        for (uint32_t x : fn.code) if (mod.hooks.count(x)) hooks.insert(x);
        auto r = P.resume.find(e);
        Body body(P.img, fn, P.entries_u, P.vol, false, hooks, mod.unwind_returns, r == P.resume.end() ? none : r->second,
                  mod.stack_return_calls);
        std::set<uint32_t> starts{e};
        if (!body.resume_points.empty()) starts.insert(body.resume_points.begin(), body.resume_points.end());
        Lower L{body, a, c, {}, {}, entry_fix};
        std::vector<std::pair<size_t, uint32_t>> stub_jumps;
        for (uint32_t s : starts) {
            while (a.pos() % 16) a.b(0xCC);
            entry_off[s] = a.pos();
            entry_stub(a, c, uint32_t(i));
            stub_jumps.emplace_back(a.jmp32(), s);
        }
        L.label_fix = stub_jumps;
        L.body();
    }
    for (auto& [at, t] : entry_fix) {
        auto it = entry_off.find(t);
        if (it == entry_off.end()) throw std::runtime_error(F("x64: call to %08X, not an entry", t));
        a.patch32(at, uint32_t(it->second - (at + 4)));
    }
    for (uint32_t e : P.entries) {
        auto it = entry_off.find(e);
        if (it == entry_off.end()) throw std::runtime_error(F("x64: entry %08X has no code", e));
        c.funcs.push_back({e, uint32_t(it->second)});
    }
    return out;
}

void generate_x64(const EmitBuild& b, const std::string& out) {
    std::filesystem::create_directories(out + "/x64");
    for (auto& m : b.modules) {
        X64Module x = emit_x64_module(b, m);
        auto bytes = cache_serialize(x.cache);
        write_file(out + "/x64/" + m.name + ".sf3c", std::string(bytes.begin(), bytes.end()));
        std::string s = "#include \"" + x.ns + "_funcs.h\"\n#include \"sf3_x64_bind.h\"\n\nnamespace " + x.ns + " {\n\n";
        s += F("static SH2Func fn[%zu];\nstatic const uint32_t addrs[] = {", x.entries.size());
        for (size_t i = 0; i < x.entries.size(); ++i) s += F("%s0x%08Xu", i ? ", " : "", x.entries[i]);
        s += "};\n";
        for (size_t i = 0; i < x.entries.size(); ++i) s += F("void f_%08X(SH2Context& c) { fn[%zu](c); }\n", x.entries[i], i);
        s += F("static const bool bound = sf3_x64_bind(\"%s\", addrs, fn, %zu, ran);\n", m.name.c_str(), x.entries.size());
        s += "\n}  // namespace " + x.ns + "\n";
        write_file(out + "/" + x.ns + "_x64.cpp", s);
    }
}

void generate_x64_set(const EmitBuild& b, const std::string& out,
                      const std::function<void(size_t, size_t, const std::string&)>& progress) {
    std::filesystem::create_directories(out);
    ModuleSetFile set;
    set.native_states = b.native_states, set.tasks[0] = b.tasks[0], set.tasks[1] = b.tasks[1];
    for (auto& t : b.task_switches) {
        if (t.size() != 5) throw std::runtime_error("x64: a task switch needs 5 values");
        set.task_switches.push_back({t[0], t[1], t[2], t[3], t[4]});
    }
    for (size_t i = 0; i < b.modules.size(); ++i) {
        auto& m = b.modules[i];
        if (progress) progress(i, b.modules.size(), m.name);
        if (m.name.size() > 255) throw std::runtime_error("x64: module name too long");
        X64Module x = emit_x64_module(b, m);
        auto bytes = cache_serialize(x.cache);
        write_file(out + "/" + m.name + ".sf3c", std::string(bytes.begin(), bytes.end()));
        set.modules.push_back({m.name, x.callable_entry, x.sizes});
    }
    auto bytes = set_serialize(set);
    // last, so a set file means every cache it names was written
    write_file(out + "/modules.sf3m", std::string(bytes.begin(), bytes.end()));
    if (progress) progress(b.modules.size(), b.modules.size(), "");
}

}  // namespace sf3::gen
