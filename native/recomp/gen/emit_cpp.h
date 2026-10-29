// SF3 recomp, on-console generator: SH-2 -> C++ emission, a C++ port of saturn-recomp's
// recomp/emit.py (Body, stmt, cycles, contended) and recomp/__main__.py (Module.generate,
// volatile_literals, modules.cpp, CMakeLists.txt) (MIT).
//
// Input is what discovery decided (tools/ps5/gen-dump-discovery.py's dump, or later the C++
// discovery): per module its code, functions and resolved computed jumps. Output is the same tree
// the Python writes, byte for byte except report.txt (tools/ps5/check-emit-cpp.sh diffs them).
#pragma once
#include <cstdint>
#include <map>
#include <set>
#include <string>
#include <unordered_set>
#include <vector>

#include "sh2_text.h"

namespace sf3::gen {

struct Target { std::vector<uint32_t> cands; std::string how; };

struct EmitFunc {
    uint32_t entry = 0;
    std::vector<uint32_t> code;                 // sorted
    std::map<uint32_t, Target> targets;         // Body._resolve
};

struct EmitModule {
    std::string name, path;
    uint32_t base = 0;
    bool runtime_literals = false, callable_entry = false, unwind_returns = false, block_coverage = false;
    std::set<uint32_t> hooks, stack_return_calls;
    std::vector<uint32_t> prog_code;            // sorted
    std::vector<EmitFunc> funcs;                // prog.funcs order
};

struct EmitBuild {
    bool native_states = false;
    uint32_t tasks[2] = {0, 0};
    std::vector<std::vector<uint32_t>> task_switches;
    std::string runtime;
    std::vector<EmitModule> modules;
};

// Reads gen-dump-discovery.py's dump.
EmitBuild read_dump(const std::string& path);

// Writes the generated tree into out (per_file, comments: as generate()'s).
void generate(const EmitBuild&, const std::string& out, int per_file = 8000, bool comments = true);

}  // namespace sf3::gen
