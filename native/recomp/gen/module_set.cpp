// SF3 recomp, on-console generator: the module set file (MIT). See module_set.h.
#include "module_set.h"
#include "code_cache.h"

namespace sf3::gen {

namespace {
void u8(std::vector<uint8_t>& o, uint8_t v) { o.push_back(v); }
void u16(std::vector<uint8_t>& o, uint16_t v) { o.push_back(uint8_t(v)), o.push_back(uint8_t(v >> 8)); }
void u32(std::vector<uint8_t>& o, uint32_t v) { for (int i = 0; i < 4; ++i) o.push_back(uint8_t(v >> (8 * i))); }

struct Reader {
    const uint8_t* p;
    size_t n, at = 0;
    bool ok = true;
    bool need(size_t k) { if (n - at < k) ok = false; return ok; }
    uint8_t r8() { if (!need(1)) return 0; return p[at++]; }
    uint16_t r16() { if (!need(2)) return 0; uint16_t v = uint16_t(p[at] | p[at + 1] << 8); at += 2; return v; }
    uint32_t r32() {
        if (!need(4)) return 0;
        uint32_t v = uint32_t(p[at]) | uint32_t(p[at + 1]) << 8 | uint32_t(p[at + 2]) << 16 | uint32_t(p[at + 3]) << 24;
        at += 4;
        return v;
    }
};
}  // namespace

std::vector<uint8_t> set_serialize(const ModuleSetFile& s) {
    std::vector<uint8_t> o;
    u32(o, kSetMagic), u32(o, kSetVersion), u32(o, kAbi), u32(o, uint32_t(s.modules.size()));
    u8(o, s.native_states), u32(o, s.tasks[0]), u32(o, s.tasks[1]), u32(o, uint32_t(s.task_switches.size()));
    for (auto& t : s.task_switches) for (uint32_t v : t) u32(o, v);
    for (auto& m : s.modules) {
        u8(o, uint8_t(m.name.size()));
        o.insert(o.end(), m.name.begin(), m.name.end());
        u8(o, m.callable_entry), u32(o, uint32_t(m.sizes.size()));
        for (uint16_t v : m.sizes) u16(o, v);
    }
    return o;
}

bool set_parse(const uint8_t* p, size_t n, ModuleSetFile& out, std::string& why) {
    Reader r{p, n};
    if (r.r32() != kSetMagic) return why = "not a module set", false;
    if (r.r32() != kSetVersion) return why = "module set version differs", false;
    if (r.r32() != kAbi) return why = "module set made for another runtime ABI", false;
    uint32_t nm = r.r32();
    out = {};
    out.native_states = r.r8() != 0;
    out.tasks[0] = r.r32(), out.tasks[1] = r.r32();
    uint32_t ns = r.r32();
    if (!r.ok || ns > 1024 || nm > 4096) return why = "module set header is damaged", false;
    for (uint32_t i = 0; i < ns; ++i) {
        std::array<uint32_t, 5> t{};
        for (auto& v : t) v = r.r32();
        out.task_switches.push_back(t);
    }
    for (uint32_t i = 0; i < nm && r.ok; ++i) {
        SetModule m;
        uint8_t len = r.r8();
        if (!r.need(len)) break;
        m.name.assign(reinterpret_cast<const char*>(p + r.at), len), r.at += len;
        m.callable_entry = r.r8() != 0;
        uint32_t ne = r.r32();
        if (ne > (1u << 20) || !r.need(size_t(ne) * 2)) { r.ok = false; break; }
        m.sizes.resize(ne);
        for (auto& v : m.sizes) v = r.r16();
        out.modules.push_back(std::move(m));
    }
    if (!r.ok || r.at != n) return why = "module set is truncated or damaged", false;
    return true;
}

}  // namespace sf3::gen
