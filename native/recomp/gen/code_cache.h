// SF3 recomp, on-console generator: the code cache file (MIT).
//
// The console builds one cache per program image the first time it is loaded and keeps it in
// /data/sfiii/cache/. It is machine code for the host, made from the user's own disc on the
// user's own console, and is never distributed. Layout (little-endian, all offsets from the file start):
//   Header | Entry[nfuncs] sorted by guest addr | Reloc[nrelocs] | code bytes (code_size)
// Relocations patch 64-bit absolute addresses of runtime services (ld/st helpers, sh2_call,
// sh2_poll, the interpreter) at load time. The cache stores no host addresses, so ASLR and a
// runtime rebuild don't invalidate it. A changed runtime ABI bumps kAbi, and the cache is rebuilt.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace sf3::gen {

constexpr uint32_t kCacheMagic = 0x43334653;   // "SF3C"
constexpr uint32_t kCacheVersion = 1;
constexpr uint32_t kAbi = 1;                   // runtime services' ABI; see Service

enum class Service : uint32_t {                // targets a reloc can name
    InterpCall = 0,                            // sf3::sh2_interp_call(SH2Context&, uint32_t)
    Sh2Call, Sh2Poll, Ld8, Ld16, Ld32, St8, St16, St32,
    Count
};

struct CacheHeader {
    uint32_t magic, version, abi, backend;     // backend: 1 = x86-64 SysV
    uint32_t image_base, image_size, image_crc;
    uint32_t nfuncs, nrelocs, code_size;
};
struct CacheEntry { uint32_t addr, code_off; };
struct CacheReloc { uint32_t code_off; Service target; };

struct Cache {
    CacheHeader h{};
    std::vector<CacheEntry> funcs;
    std::vector<CacheReloc> relocs;
    std::vector<uint8_t> code;
};

std::vector<uint8_t> cache_serialize(const Cache&);
// Checks magic, version, abi, backend, sizes, sorted entries and reloc bounds. On failure it returns false with why.
bool cache_parse(const uint8_t* p, size_t n, Cache& out, std::string& why);

}  // namespace sf3::gen
