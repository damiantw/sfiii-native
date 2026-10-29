// SF3 recomp, on-console generator: SH-2 decoding with saturn-recomp's mnemonics and text (MIT).
// A port of saturn-recomp's src/saturnrecomp/sh2.py (decode, Insn.text, Image.literal): the C++
// emitter (emit_cpp) prints these strings in its comments, so they must match byte for byte.
#pragma once
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace sf3::gen {

struct Insn {
    uint32_t pc = 0;
    uint16_t word = 0;
    const char* op = ".word";   // canonical mnemonic
    std::string fmt;            // "mov.l @(disp,Rm),Rn" (".word 0x1234" when unknown)
    int n = -1, m = -1;         // -1: none
    std::optional<int32_t> imm, disp;
    std::optional<uint32_t> target;
    bool delay = false;
    int size = 0;               // 2/4 for pc-relative loads and mova (mova: 4), else 0
    std::string text() const;
    bool is(const char* o) const;
};

Insn decode(uint16_t word, uint32_t pc);

struct FlatImage {
    uint32_t base = 0;
    std::vector<uint8_t> data;
    uint32_t end() const { return base + uint32_t(data.size()); }
    bool contains(uint32_t a, uint32_t size = 2) const { return base <= a && uint64_t(a) + size <= end(); }
    uint16_t u16(uint32_t a) const { size_t o = a - base; return uint16_t(data[o] << 8 | data[o + 1]); }
    uint32_t u32(uint32_t a) const { return uint32_t(u16(a)) << 16 | u16(a + 2); }
    Insn insn(uint32_t a) const { return decode(u16(a), a); }
    std::optional<uint32_t> literal(const Insn&) const;
};

}  // namespace sf3::gen
