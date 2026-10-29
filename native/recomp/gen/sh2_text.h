// SF3 recomp, on-console generator: SH-2 decoding with saturn-recomp's mnemonics and text (MIT).
// A port of saturn-recomp's src/saturnrecomp/sh2.py (decode, Insn.text, Image.literal): the C++
// emitter (emit_cpp) prints these strings in its comments, so they must match byte for byte.
#pragma once
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace sf3::gen {

struct Insn {
    uint32_t pc = 0;
    uint16_t word = 0;
    const char* op = ".word";   // canonical mnemonic
    std::string_view fmt;       // "mov.l @(disp,Rm),Rn" (".word 0x1234" when unknown); static storage
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
    // Python's struct.unpack_from: a negative offset counts from the end, past the end raises.
    size_t off(uint32_t a, size_t size) const {
        int64_t o = int64_t(a) - int64_t(base);
        if (o < 0) o += int64_t(data.size());
        if (o < 0 || uint64_t(o) + size > data.size()) throw std::out_of_range("image read outside the image");
        return size_t(o);
    }
    uint16_t u16(uint32_t a) const { size_t o = off(a, 2); return uint16_t(data[o] << 8 | data[o + 1]); }
    uint32_t u32(uint32_t a) const {
        size_t o = off(a, 4);
        return uint32_t(data[o]) << 24 | uint32_t(data[o + 1]) << 16 | uint32_t(data[o + 2]) << 8 | data[o + 3];
    }
    Insn insn(uint32_t a) const { return decode(u16(a), a); }
    std::optional<uint32_t> literal(const Insn&) const;
};

}  // namespace sf3::gen
