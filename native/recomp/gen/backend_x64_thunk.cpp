#include "backend.h"
#include <algorithm>

namespace sf3::gen {

void X64ThunkBackend::emit(const Image&, const Function& f, Cache& c) {
    // SysV: rdi = SH2Context& (passed through), esi = entry; tail-jump to sh2_interp_call.
    //   BE imm32            mov esi, entry
    //   48 B8 imm64         movabs rax, <InterpCall>   (reloc)
    //   FF E0               jmp rax
    uint32_t off = uint32_t(c.code.size());
    c.funcs.push_back({f.entry, off});
    c.code.push_back(0xBE);
    for (int i = 0; i < 4; ++i) c.code.push_back(uint8_t(f.entry >> (8 * i)));
    c.code.push_back(0x48), c.code.push_back(0xB8);
    c.relocs.push_back({uint32_t(c.code.size()), Service::InterpCall});
    for (int i = 0; i < 8; ++i) c.code.push_back(0);
    c.code.push_back(0xFF), c.code.push_back(0xE0);
    while (c.code.size() % 16) c.code.push_back(0xCC);       // int3 padding, 16-byte aligned entries
}

Cache build_cache(const Image& img, const std::vector<uint32_t>& seeds, Backend& be) {
    Cache c;
    c.h.backend = be.id();
    c.h.image_base = img.base, c.h.image_size = uint32_t(img.bytes.size());
    Program p = discover(img, seeds);
    for (auto& [addr, f] : p.funcs) be.emit(img, f, c);     // map order: entries come out sorted
    return c;
}

}  // namespace sf3::gen
