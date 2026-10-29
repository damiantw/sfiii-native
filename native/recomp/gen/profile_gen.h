// SF3 recomp, on-console generator: tools/generate.py's saturn-recomp path in C++ (MIT): a revision
// profile and a verified extraction in, the generated C++ tree out, with no Python on the machine.
//
// It ports module_images.py (container expansion, verified sources, image slices), disc_profile.py's
// verify_inventory, module_entries.py and the export veneer rule (seeds), scene_data_entries.py, and
// then runs the C++ discovery (discovery.h) and emitter (emit_cpp.h) with generate.py's options.
#pragma once
#include <cstdint>
#include <functional>
#include <set>
#include <string>
#include <vector>

#include "emit_cpp.h"

namespace sf3::gen {

struct GenOptions {
    std::string work;            // WORK: manifest.json, hashes.json, extract/ (modules/ is written)
    std::string profile;         // the revision profile (JSON)
    std::string out;             // generated tree
    std::string runtime;         // saturn-recomp's runtime directory, as CMakeLists.txt names it
    bool block_coverage = false;
    int per_file = 8000;
    bool comments = true;
    std::function<void(const std::string&)> log;
};

struct Spec {
    std::string name, path;
    uint32_t base = 0;
    std::vector<uint32_t> seeds;   // sorted
    bool overlay = false;
    std::set<uint32_t> stack_return_calls;
};

struct SceneRow {
    std::string module;
    uint32_t target = 0;
    std::string verdict, reason;
    std::vector<uint32_t> refs;
};

// generate.py up to generate(): the modules to build and their seeds (writes WORK/modules/ slices).
std::vector<Spec> prepare_specs(const GenOptions&, std::vector<SceneRow>& scene_rows);

// Discovery and resolution of every spec, as Module() does, into the emitter's input.
EmitBuild discover_build(const std::vector<Spec>&, const GenOptions&);

// The whole of generate.py --framework saturn-recomp: the tree and scene-data-entries.tsv.
void generate_from_profile(const GenOptions&);

// module_entries.py and the veneer rule, for one image.
std::set<uint32_t> idiom_entries(const std::vector<uint8_t>& data, uint32_t base);

}  // namespace sf3::gen
