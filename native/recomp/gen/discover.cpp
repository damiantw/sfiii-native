#include "discover.h"
#include "../sh2_interp.h"

namespace sf3::gen {
namespace {

int32_t disp8(uint16_t w) { return int8_t(w & 0xFF); }
int32_t disp12(uint16_t w) { return int32_t(w << 20) >> 20; }

void walk(const Image& img, Function& f, std::vector<uint32_t>& pending, const std::set<uint32_t>& entries) {
    std::vector<uint32_t> work{f.entry};
    auto take = [&](uint32_t a) {
        if (!img.inside(a)) { if (!f.bad) f.bad = "branch outside the image", f.bad_at = a; return; }
        if (!f.code.count(a)) work.push_back(a);
    };
    while (!work.empty()) {
        uint32_t pc = work.back();
        work.pop_back();
        for (;;) {
            if (!img.inside(pc)) { if (!f.bad) f.bad = "ran off the image", f.bad_at = pc; break; }
            if (!f.code.insert(pc).second) break;
            uint16_t w = img.word(pc);
            Sh2Op op = sh2_decode(w);
            if (op == OP_INVALID) { if (!f.bad) f.bad = "undefined instruction", f.bad_at = pc; break; }
            // pc-relative literal loads: mov.w @(disp,pc),Rn 9nxx ; mov.l @(disp,pc),Rn Dnxx ; mova C7xx
            if ((w & 0xF000) == 0x9000) f.literals.insert(pc + 4 + (w & 0xFF) * 2);
            else if ((w & 0xF000) == 0xD000) f.literals.insert(((pc + 4) & ~3u) + (w & 0xFF) * 4);
            bool delayed = sh2_is_delayed(op);
            if (delayed) {
                uint32_t slot = pc + 2;
                if (img.inside(slot)) f.code.insert(slot);
                else if (!f.bad) f.bad = "delay slot outside the image", f.bad_at = slot;
            }
            switch (op) {
            case OP_BT_PC: case OP_BF_PC: take(pc + 4 + disp8(w) * 2); pc += 2; continue;
            case OP_BT_S_PC: case OP_BF_S_PC: take(pc + 4 + disp8(w) * 2); pc += 4; continue;
            case OP_BRA_PC: {
                uint32_t t = pc + 4 + disp12(w) * 2;
                if (entries.count(t) && t != f.entry) f.tails.insert(t); else take(t);
                break;
            }
            case OP_BSR_PC: {
                uint32_t t = pc + 4 + disp12(w) * 2;
                if (img.inside(t)) { f.calls.insert(t); pending.push_back(t); }
                else if (!f.bad) f.bad = "call outside the image", f.bad_at = t;
                pc += 4;
                continue;
            }
            case OP_JSR_AT_RN: case OP_BSRF_RN: f.unresolved.push_back(pc); pc += 4; continue;
            case OP_JMP_AT_RN: case OP_BRAF_RN: f.unresolved.push_back(pc); break;
            case OP_RTS: case OP_RTE: break;
            default: pc += 2; continue;
            }
            break;   // the block ended
        }
    }
}

}  // namespace

Program discover(const Image& img, const std::vector<uint32_t>& seeds) {
    sh2_interp_init();
    Program p;
    std::set<uint32_t> entries(seeds.begin(), seeds.end());
    std::vector<uint32_t> pending(seeds.begin(), seeds.end());
    while (!pending.empty()) {
        uint32_t e = pending.back();
        pending.pop_back();
        if (p.funcs.count(e)) continue;
        entries.insert(e);
        Function& f = p.funcs[e];
        f.entry = e;
        walk(img, f, pending, entries);
    }
    return p;
}

}  // namespace sf3::gen
