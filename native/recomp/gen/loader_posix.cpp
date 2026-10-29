#include "loader.h"
#include <cstring>
#include <sys/mman.h>
#include <unistd.h>

namespace sf3::gen {

bool load_cache(const Cache& c, const ServiceTable& svc, LoadedCode& out, std::string& why) {
    size_t page = size_t(sysconf(_SC_PAGESIZE));
    size_t size = (c.code.size() + page - 1) / page * page;
    if (!size) return why = "empty cache", false;
    void* m = mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (m == MAP_FAILED) return why = "mmap RW failed", false;
    auto* b = static_cast<uint8_t*>(m);
    std::memcpy(b, c.code.data(), c.code.size());
    for (auto& r : c.relocs) {
        void* t = svc[size_t(r.target)];
        if (!t) { munmap(m, size); return why = "missing service", false; }
        uint64_t v;
        std::memcpy(&v, b + r.code_off, 8);
        v += reinterpret_cast<uint64_t>(t);
        std::memcpy(b + r.code_off, &v, 8);
    }
    if (mprotect(m, size, PROT_READ | PROT_EXEC)) { munmap(m, size); return why = "mprotect RX failed", false; }
    out.base = m, out.size = size, out.funcs.clear();
    for (auto& e : c.funcs) out.funcs.push_back({e.addr, reinterpret_cast<SH2Func>(b + e.code_off)});
    return true;
}

void unload(LoadedCode& l) {
    if (l.base) munmap(l.base, l.size);
    l = {};
}

}  // namespace sf3::gen
