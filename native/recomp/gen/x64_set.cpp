// SF3 recomp: running a generated module set in a generic build (MIT).
//
// A build made from the generated C++ tree compiles each module's tables (*_table.cpp, modules.cpp) in.
// A generic build has none: the generator wrote the code caches and modules.sf3m on the user's
// machine (module_set.h), and this file turns them into the same SH2Module records at start. The
// binary then holds no code or data made from a disc. Link modules_none.cpp with it for the empty
// generated tables the runtime still names.
#include "x64_set.h"

#include <fstream>
#include <iterator>
#include <memory>
#include <vector>

#include "code_cache.h"
#include "loader.h"
#include "module_set.h"
#include "saturn/sh2.h"
#include "sf3_x64_bind.h"

using namespace sf3::gen;

namespace {

struct Owned {                                   // one module's records; they live for the process
    std::string name;
    std::vector<SH2FuncEntry> funcs;
    std::vector<uint8_t> ran;
    std::vector<uint16_t> sizes;
    LoadedCode code;
    SH2Module module{};
};

bool read_file(const std::string& path, std::vector<uint8_t>& out) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return false;
    out.assign(std::istreambuf_iterator<char>(in), {});
    return true;
}

}  // namespace

bool sf3_x64_install_set(const std::string& dir, std::string& why) {
    std::vector<uint8_t> bytes;
    if (!read_file(dir + "/modules.sf3m", bytes)) return why = "no module set in " + dir, false;
    ModuleSetFile set;
    if (!set_parse(bytes.data(), bytes.size(), set, why)) return false;
    auto owned = std::make_unique<std::vector<std::unique_ptr<Owned>>>();
    for (auto& sm : set.modules) {
        if (!read_file(dir + "/" + sm.name + ".sf3c", bytes)) return why = "missing cache " + sm.name, false;
        Cache c;
        if (!cache_parse(bytes.data(), bytes.size(), c, why)) return why = sm.name + ": " + why, false;
        if (c.funcs.size() != sm.sizes.size()) return why = sm.name + ": entry count differs from the set", false;
        auto o = std::make_unique<Owned>();
        o->name = sm.name, o->sizes = sm.sizes, o->ran.assign(c.funcs.size(), 0);
        if (!sf3_x64_load(c, o->ran.data(), o->code, why)) return why = sm.name + ": " + why, false;
        o->funcs = o->code.funcs;
        o->module = {o->name.c_str(), c.h.image_base, c.h.image_size, c.h.image_crc, o->funcs.data(),
                     uint32_t(o->funcs.size()), o->ran.data(), o->sizes.data(), sm.callable_entry};
        owned->push_back(std::move(o));
    }
    auto* list = new std::vector<const SH2Module*>;
    for (auto& o : *owned) list->push_back(&o->module);
    auto* sw = new std::vector<SH2TaskSwitch>;
    for (auto& t : set.task_switches) sw->push_back({t[0], t[1], t[2], t[3], t[4]});
    auto* s = new SH2ModuleSet{list->data(), int(list->size()), set.native_states, {set.tasks[0], set.tasks[1]},
                               sw->empty() ? nullptr : sw->data(), int(sw->size())};
    owned.release();                             // the records and the code stay for the process
    sat_set_module_set(s);
    return true;
}
