// sf3-emit-cpp DUMP OUT [--per-file N] [--no-comments]: the C++ generator's emitter on a discovery
// dump (tools/ps5/gen-dump-discovery.py), for the byte-identical check against saturn-recomp (MIT).
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>

#include "emit_cpp.h"

int main(int argc, char** argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s DUMP OUT [--per-file N] [--no-comments]\n", argv[0]); return 2; }
    int per_file = 8000;
    bool comments = true;
    for (int i = 3; i < argc; ++i) {
        if (!strcmp(argv[i], "--per-file") && i + 1 < argc) per_file = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--no-comments")) comments = false;
    }
    try {
        auto b = sf3::gen::read_dump(argv[1]);
        sf3::gen::generate(b, argv[2], per_file, comments);
        size_t f = 0;
        for (auto& m : b.modules) f += m.funcs.size();
        printf("%zu modules, %zu functions\n", b.modules.size(), f);
    } catch (const std::exception& e) {
        fprintf(stderr, "sf3-emit-cpp: %s\n", e.what());
        return 1;
    }
}
