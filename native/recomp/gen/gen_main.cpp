// sf3-gen: the on-console generator (MIT). A revision profile and a verified extraction in, the
// generated tree out, with no Python: tools/generate.py --framework saturn-recomp, in C++.
//
//     sf3-gen --work WORK --profile PROFILE.json --out OUT --runtime DIR [--block-coverage] [--specs FILE]
//
// --specs writes generate()'s specs (Q records: name base seed...), to compare with the Python's.
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>

#include "profile_gen.h"

using namespace sf3::gen;

int main(int argc, char** argv) {
    GenOptions o;
    std::string specs_out;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) { fprintf(stderr, "%s needs a value\n", a.c_str()); exit(2); }
            return argv[++i];
        };
        if (a == "--work") o.work = next();
        else if (a == "--profile") o.profile = next();
        else if (a == "--out") o.out = next();
        else if (a == "--runtime") o.runtime = next();
        else if (a == "--block-coverage") o.block_coverage = true;
        else if (a == "--specs") specs_out = next();
        else { fprintf(stderr, "unknown option %s\n", a.c_str()); return 2; }
    }
    if (o.work.empty() || o.profile.empty() || (o.out.empty() && specs_out.empty())) {
        fprintf(stderr, "usage: sf3-gen --work WORK --profile PROFILE.json --out OUT --runtime DIR [--block-coverage] [--specs FILE]\n");
        return 2;
    }
    o.log = [](const std::string& s) { printf("%s\n", s.c_str()); fflush(stdout); };
    try {
        if (!specs_out.empty()) {
            std::vector<SceneRow> rows;
            auto specs = prepare_specs(o, rows);
            std::ofstream q(specs_out);
            for (auto& s : specs) {
                char b[16];
                snprintf(b, sizeof b, "%X", s.base);
                q << "Q " << s.name << ' ' << b;
                for (uint32_t v : s.seeds) { snprintf(b, sizeof b, "%X", v); q << ' ' << b; }
                q << '\n';
            }
        }
        if (!o.out.empty()) generate_from_profile(o);
    } catch (const std::exception& e) {
        fprintf(stderr, "sf3-gen: %s\n", e.what());
        return 1;
    }
    return 0;
}
