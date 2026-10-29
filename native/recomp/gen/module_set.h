// SF3 recomp, on-console generator: the module set file (MIT).
//
// What a generated modules.cpp and the *_table.cpp files say about a build, for a build that has none:
// which modules there are, in which order, each one's per-entry instruction counts and flags, and
// the build's task settings. With one code cache per module (code_cache.h: entries, base, size,
// crc) it is everything the runtime needs, so one generic binary runs whatever the generator made
// from the user's disc (x64_set.cpp). Like the caches it is made on the user's machine from the
// user's disc and never distributed. Layout (little-endian):
//   "SF3M" u32 version u32 abi u32 nmodules u8 native_states u32 tasks[2] u32 nswitches
//   u32[5] per switch, then per module: u8 namelen, name, u8 callable_entry, u32 nentries,
//   u16 sizes[nentries].
#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace sf3::gen {

constexpr uint32_t kSetMagic = 0x4D334653;   // "SF3M"
constexpr uint32_t kSetVersion = 1;

struct SetModule {
    std::string name;
    bool callable_entry = false;
    std::vector<uint16_t> sizes;             // per entry, in the cache's entry order
};

struct ModuleSetFile {
    bool native_states = false;
    uint32_t tasks[2] = {0, 0};
    std::vector<std::array<uint32_t, 5>> task_switches;
    std::vector<SetModule> modules;
};

std::vector<uint8_t> set_serialize(const ModuleSetFile&);
bool set_parse(const uint8_t* p, size_t n, ModuleSetFile& out, std::string& why);

}  // namespace sf3::gen
