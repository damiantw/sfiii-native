// sf3-discovery-check DUMP [--emit OUT] [--only NAME]: runs the C++ discovery on each module of a
// gen-dump-discovery.py dump (its Q records: the seeds) and compares what it decides with the
// Python's (P, F and T records). --emit then generates the tree from the C++ discovery alone (MIT).
#include <chrono>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>

#include "discovery.h"
#include "emit_cpp.h"

using namespace sf3::gen;

int main(int argc, char** argv) {
    if (argc < 2) { fprintf(stderr, "usage: sf3-discovery-check DUMP [--emit OUT] [--only NAME]\n"); return 2; }
    std::string dump = argv[1], emit_out, only;
    for (int i = 2; i + 1 < argc; ++i) {
        if (std::string(argv[i]) == "--emit") emit_out = argv[++i];
        else if (std::string(argv[i]) == "--only") only = argv[++i];
    }
    EmitBuild b = read_dump(dump);
    std::map<std::string, std::vector<uint32_t>> seeds;
    {
        std::ifstream in(dump);
        std::string line;
        while (std::getline(in, line)) {
            if (line.size() < 2 || line[0] != 'Q') continue;
            std::istringstream ss(line.substr(2));
            std::string name, w;
            ss >> name >> w;     // base
            auto& v = seeds[name];
            while (ss >> w) v.push_back(uint32_t(strtoul(w.c_str(), nullptr, 16)));
        }
    }
    int bad_modules = 0;
    auto t0 = std::chrono::steady_clock::now();
    for (auto& m : b.modules) {
        if (!only.empty() && m.name != only) continue;
        FlatImage img;
        img.base = m.base;
        std::ifstream in(m.path, std::ios::binary);
        img.data.assign(std::istreambuf_iterator<char>(in), {});
        std::vector<uint32_t> s{m.base};
        auto q = seeds.find(m.name);
        if (q == seeds.end()) { fprintf(stderr, "%s: no Q record\n", m.name.c_str()); return 1; }
        s.insert(s.end(), q->second.begin(), q->second.end());
        std::vector<std::string> diffs;
        try {
            Program p(img, s);
            auto code = p.sorted_code();
            if (code != m.prog_code)
                diffs.push_back("P: " + std::to_string(code.size()) + " vs " + std::to_string(m.prog_code.size()));
            if (p.funcs.size() != m.funcs.size())
                diffs.push_back("F count " + std::to_string(p.funcs.size()) + " vs " + std::to_string(m.funcs.size()));
            USet vol = volatile_literals_of(img, code);
            if (m.runtime_literals)
                for (uint32_t a : code) {
                    Insn ins = img.insn(a);
                    if ((ins.is("mov.w") || ins.is("mov.l")) && ins.size) vol.insert(*ins.target);
                }
            std::vector<EmitFunc> mine;
            for (size_t i = 0; i < p.funcs.size(); ++i) {
                const Function& f = *p.funcs[i];
                EmitFunc ef;
                ef.entry = f.entry;
                ef.code.assign(f.code.begin(), f.code.end());
                std::sort(ef.code.begin(), ef.code.end());
                ef.targets = p.resolve(f, vol);
                if (i < m.funcs.size() && diffs.size() < 12) {
                    const EmitFunc& o = m.funcs[i];
                    char buf[160];
                    if (o.entry != ef.entry) {
                        snprintf(buf, sizeof buf, "F[%zu] entry %X vs %X", i, ef.entry, o.entry);
                        diffs.push_back(buf);
                    } else if (o.code != ef.code) {
                        snprintf(buf, sizeof buf, "F %X code %zu vs %zu", ef.entry, ef.code.size(), o.code.size());
                        diffs.push_back(buf);
                    } else {
                        for (auto& [site, t] : o.targets) {
                            auto it = ef.targets.find(site);
                            if (it == ef.targets.end() || it->second.how != t.how || it->second.cands != t.cands) {
                                snprintf(buf, sizeof buf, "T %X site %X: %s vs %s", ef.entry, site,
                                         it == ef.targets.end() ? "-" : it->second.how.c_str(), t.how.c_str());
                                diffs.push_back(buf);
                                break;
                            }
                        }
                        if (ef.targets.size() != o.targets.size()) {
                            snprintf(buf, sizeof buf, "T %X count %zu vs %zu", ef.entry, ef.targets.size(), o.targets.size());
                            diffs.push_back(buf);
                        }
                    }
                }
                mine.push_back(std::move(ef));
            }
            m.prog_code = code;
            m.funcs = std::move(mine);
        } catch (const std::exception& e) {
            diffs.push_back(std::string("exception: ") + e.what());
        }
        if (!diffs.empty()) {
            ++bad_modules;
            printf("%s:", m.name.c_str());
            for (auto& d : diffs) printf("  %s;", d.c_str());
            printf("\n");
        }
    }
    double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    printf("%zu modules, %d differ, %.1f s\n", b.modules.size(), bad_modules, secs);
    if (!emit_out.empty() && only.empty()) generate(b, emit_out);
    return bad_modules ? 1 : 0;
}
