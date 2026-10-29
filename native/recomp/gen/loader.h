// SF3 recomp, on-console generator: loading a cache as executable code (MIT).
//
// The PS5 path (PROBE.md, fw 12.09) is: map RW, copy the code, apply relocs, then mprotect to RX.
// Asking for exec at map time is refused. Linux runs the same sequence with mmap/mprotect, so
// the loader is tested on the box. The PS5 build swaps in sceKernel* calls behind the same API.
#pragma once
#include "code_cache.h"
#include "saturn/sh2.h"
#include <string>
#include <vector>

namespace sf3::gen {

struct LoadedCode {
    void* base = nullptr;
    size_t size = 0;
    std::vector<SH2FuncEntry> funcs;    // sorted, ready for an SH2Module
};

using ServiceTable = void* [size_t(Service::Count)];

bool load_cache(const Cache&, const ServiceTable&, LoadedCode& out, std::string& why);
void unload(LoadedCode&);

}  // namespace sf3::gen
