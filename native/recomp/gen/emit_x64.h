// SF3 recomp, on-console generator: the x86-64 backend (MIT).
//
// Lowers what emit.py decides (emit_body.h's Body: labels, blocks and their cycle charges, safe points,
// state points, calls, jump tables, folded literals) to x86-64 machine code, one code cache per module.
// It makes the same decisions as the C++ printer, so a build running this code has the same guest
// timing and state as the clang build of the generated C++ (tools/ps5/check-x64.sh compares state hashes).
#pragma once
#include <functional>
#include <string>
#include <vector>

#include "code_cache.h"
#include "emit_cpp.h"

namespace sf3::gen {

struct X64Module {
    std::string name, ns;
    std::vector<uint32_t> entries;     // every exported entry, sorted (as the module's funcs[] table)
    std::vector<uint16_t> sizes;       // each entry's instruction count (the table's sizes[]), 0 for a secondary entry
    bool callable_entry = false;
    Cache cache;
};

// One module's cache. Throws on an instruction the generator does not support (as the C++ printer).
X64Module emit_x64_module(const EmitBuild&, const EmitModule&);

// Writes OUT/x64/<NAME>.sf3c for every module, and OUT/<ns>_x64.cpp: f_XXXXXXXX definitions that call
// into the loaded cache (sf3_x64_bind, x64_rt.cpp), to replace the generated C++ bodies in a test build.
void generate_x64(const EmitBuild&, const std::string& out);

// The caches alone, for a generic build (x64_set.cpp): OUT/<NAME>.sf3c for every module and OUT/modules.sf3m.
// progress(done, total, name) is called before each module; nothing else is written.
void generate_x64_set(const EmitBuild&, const std::string& out,
                      const std::function<void(size_t, size_t, const std::string&)>& progress = {});

}  // namespace sf3::gen
