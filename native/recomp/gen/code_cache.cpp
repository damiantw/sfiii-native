#include "code_cache.h"
#include <cstring>

namespace sf3::gen {

template <class T> static void put(std::vector<uint8_t>& o, const T& v) {
    auto* b = reinterpret_cast<const uint8_t*>(&v);
    o.insert(o.end(), b, b + sizeof v);
}

std::vector<uint8_t> cache_serialize(const Cache& c) {
    std::vector<uint8_t> o;
    CacheHeader h = c.h;
    h.magic = kCacheMagic, h.version = kCacheVersion, h.abi = kAbi;
    h.nfuncs = uint32_t(c.funcs.size()), h.nrelocs = uint32_t(c.relocs.size()), h.code_size = uint32_t(c.code.size());
    put(o, h);
    for (auto& e : c.funcs) put(o, e);
    for (auto& r : c.relocs) put(o, r);
    o.insert(o.end(), c.code.begin(), c.code.end());
    return o;
}

bool cache_parse(const uint8_t* p, size_t n, Cache& c, std::string& why) {
    if (n < sizeof(CacheHeader)) return why = "short file", false;
    std::memcpy(&c.h, p, sizeof c.h);
    if (c.h.magic != kCacheMagic) return why = "not a code cache", false;
    if (c.h.version != kCacheVersion || c.h.abi != kAbi) return why = "old cache version", false;
    if (c.h.backend != 1 && c.h.backend != 2) return why = "other backend", false;
    size_t need = sizeof(CacheHeader) + size_t(c.h.nfuncs) * sizeof(CacheEntry) + size_t(c.h.nrelocs) * sizeof(CacheReloc) + c.h.code_size;
    if (n != need) return why = "size mismatch", false;
    const uint8_t* q = p + sizeof(CacheHeader);
    c.funcs.resize(c.h.nfuncs);
    std::memcpy(c.funcs.data(), q, c.funcs.size() * sizeof(CacheEntry));
    q += c.funcs.size() * sizeof(CacheEntry);
    c.relocs.resize(c.h.nrelocs);
    std::memcpy(c.relocs.data(), q, c.relocs.size() * sizeof(CacheReloc));
    q += c.relocs.size() * sizeof(CacheReloc);
    c.code.assign(q, q + c.h.code_size);
    for (size_t i = 0; i < c.funcs.size(); ++i) {
        if (c.funcs[i].code_off >= c.h.code_size) return why = "entry outside code", false;
        if (i && c.funcs[i].addr <= c.funcs[i - 1].addr) return why = "entries not sorted", false;
    }
    for (auto& r : c.relocs)
        if (uint64_t(r.code_off) + 8 > c.h.code_size || uint32_t(r.target) >= uint32_t(Service::Count)) return why = "bad reloc", false;
    return true;
}

}  // namespace sf3::gen
