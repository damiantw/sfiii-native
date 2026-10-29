// SF3 recomp, on-console generator: SH-2 -> C++ emission (MIT). See emit_cpp.h.
#include "emit_cpp.h"

#include <algorithm>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <tuple>
#include <unordered_map>

#include "hashes.h"
#include "emit_body.h"

namespace sf3::gen {
namespace {


// Writes a file only if its content changed (Out).
void put(const std::string& path, const std::string& text) {
    {
        std::ifstream in(path, std::ios::binary);
        if (in) {
            std::stringstream ss;
            ss << in.rdbuf();
            if (ss.str() == text) return;
        }
    }
    std::ofstream o(path, std::ios::binary);
    o << text;
    if (!o) throw std::runtime_error("cannot write " + path);
}


std::vector<std::string> split(const std::string& line) {
    std::vector<std::string> out;
    std::istringstream ss(line);
    std::string w;
    while (ss >> w) out.push_back(w);
    return out;
}

uint32_t hx(const std::string& s) { return uint32_t(strtoul(s.c_str(), nullptr, 16)); }

std::string module_files(const EmitBuild& b, const EmitModule& mod, const std::string& out, int per_file, bool comments,
                         std::vector<std::string>& files) {
    ModulePlan P = plan_module(b, mod);
    FlatImage& img = P.img;
    const std::string& ns = P.ns;
    auto& primary = P.primary;
    auto& by_entry = P.by_entry;
    auto& resume = P.resume;
    auto& entries = P.entries;
    auto& entries_u = P.entries_u;
    auto& vol = P.vol;

    using Row = std::tuple<uint32_t, uint32_t, std::string, std::string, size_t>;
    std::vector<Row> rows;
    std::vector<std::string> buf;
    std::vector<std::pair<uint32_t, std::vector<std::tuple<uint32_t, size_t, const char*>>>> places;
    size_t count = 0;
    int idx = 0;
    auto flush = [&] {
        if (buf.empty()) return;
        std::string name = F("%s_%03d.cpp", ns.c_str(), idx);
        std::string text = "#include \"" + ns + "_funcs.h\"\n\nnamespace " + ns + " {\n\n";
        for (size_t i = 0; i < buf.size(); ++i) { if (i) text += "\n\n"; text += buf[i]; }
        text += "\n\n}  // namespace " + ns + "\n";
        put(out + "/" + name, text);
        size_t line = 5;
        for (size_t i = 0; i < buf.size(); ++i) {
            for (auto& [a, k, kind] : places[i].second) rows.emplace_back(a, places[i].first, kind, name, line + k);
            line += size_t(std::count(buf[i].begin(), buf[i].end(), '\n')) + 2;
        }
        files.push_back(name);
        buf.clear(), places.clear(), count = 0, ++idx;
    };
    static const std::set<uint32_t> none;
    for (uint32_t e : primary) {
        size_t i = size_t(std::lower_bound(entries.begin(), entries.end(), e) - entries.begin());
        const EmitFunc& fn = *by_entry[e];
        std::set<uint32_t> hooks;
        for (uint32_t a : fn.code) if (mod.hooks.count(a)) hooks.insert(a);
        auto r = resume.find(e);
        Body body(img, fn, entries_u, vol, comments, hooks, mod.unwind_returns, r == resume.end() ? none : r->second,
                  mod.stack_return_calls);
        auto lines = body.emit();
        lines.insert(lines.begin() + 1, F("    ran[%zu] = 1;", i));
        std::string joined;
        for (size_t j = 0; j < lines.size(); ++j) { if (j) joined += "\n"; joined += lines[j]; }
        buf.push_back(std::move(joined));
        std::vector<std::tuple<uint32_t, size_t, const char*>> loc;
        for (auto& [a, k, kind] : body.locations) loc.emplace_back(a, k + (k >= 1), kind);
        places.emplace_back(e, std::move(loc));
        count += fn.code.size();
        if (count >= size_t(per_file)) flush();
    }
    flush();
    std::filesystem::create_directories(out + "/map");
    std::sort(rows.begin(), rows.end());
    std::string base = std::filesystem::path(mod.path).filename().string();
    std::string m = F("# %s: %s at %08X, %zu bytes, sha1 %s\n# address\tfunction\tkind\tfile\tline\n", mod.name.c_str(),
                      base.c_str(), mod.base, img.data.size(), sha1_hex(img.data.data(), img.data.size()).c_str());
    for (auto& [a, e, kind, name, line] : rows) m += F("%08X\t%08X\t%s\t%s\t%zu\n", a, e, kind.c_str(), name.c_str(), line);
    put(out + "/map/" + mod.name + ".tsv", m);

    std::string h = "#pragma once\n#include \"saturn/sh2.h\"\n\nnamespace " + ns + " {\n";
    for (uint32_t e : entries) h += "void " + fname(e) + "(SH2Context& c);\n";
    if (mod.block_coverage) h += "extern uint8_t blk[];\n";
    h += "extern uint8_t ran[];\nextern const SH2Module module;\n}  // namespace " + ns + "\n";
    put(out + "/" + ns + "_funcs.h", h);

    std::string t = "#include \"" + ns + "_funcs.h\"\n\nnamespace " + ns + " {\n\n";
    t += "static const SH2FuncEntry funcs[] = {\n";
    for (uint32_t e : entries) t += F("    {0x%08Xu, %s},\n", e, fname(e).c_str());
    t += "};\n\n";
    t += F("uint8_t ran[%zu];\n", entries.size());
    std::string sizes;
    for (size_t j = 0; j < entries.size(); ++j) {
        if (j) sizes += ", ";
        auto it = by_entry.find(entries[j]);
        sizes += it == by_entry.end() ? "0" : std::to_string(it->second->code.size());
    }
    t += "static const uint16_t sizes[] = {" + sizes + "};\n\n";
    t += F("extern const SH2Module module = {\"%s\", 0x%08Xu, %zuu, 0x%08Xu, funcs, %zu, ran, sizes, %s};\n", mod.name.c_str(),
           mod.base, img.data.size(), crc32(img.data.data(), img.data.size()), entries.size(), mod.callable_entry ? "true" : "false");
    if (mod.block_coverage) throw std::runtime_error("block_coverage is not ported yet");
    t += "\n}  // namespace " + ns + "\n";
    put(out + "/" + ns + "_table.cpp", t);
    files.push_back(ns + "_table.cpp");
    return ns;
}

const char* CMAKE_HEAD = "cmake_minimum_required(VERSION 3.20)\nproject(saturn_recomp CXX)\nset(CMAKE_CXX_STANDARD 20)\n"
    "if(NOT CMAKE_BUILD_TYPE)\n  set(CMAKE_BUILD_TYPE Release)\nendif()\nif(NOT SATURN_RUNTIME)\n  set(SATURN_RUNTIME \"";
const char* CMAKE_TAIL = ")\ntarget_include_directories(recomp PUBLIC ${SATURN_RUNTIME}/include)\n"
    "target_compile_options(recomp PRIVATE -Wno-unused-label -Wno-tautological-compare)\n"
    "# the runtime's targets (runtime/runtime.cmake)\ninclude(${SATURN_RUNTIME}/runtime.cmake)\n"
    "add_executable(selftest ${SATURN_RUNTIME}/src/app/selftest.cpp)\n"
    "target_link_libraries(selftest saturn_core saturn_stub recomp)\n"
    "# the Saturn: boots a disc into these modules; on Android, the libmain.so SDL's Java side loads\n"
    "if(ANDROID)\n  add_library(saturn SHARED ${SATURN_RUNTIME}/src/app/main.cpp)\n"
    "  set_target_properties(saturn PROPERTIES OUTPUT_NAME main)\nelse()\n"
    "  add_executable(saturn ${SATURN_RUNTIME}/src/app/main.cpp)\nendif()\n"
    "target_link_libraries(saturn saturn_core saturn_machine saturn_host recomp Threads::Threads)\n"
    "# a project can add its own targets (the game) with -DSATURN_EXTRA=file.cmake\n"
    "if(DEFINED SATURN_EXTRA)\n  include(${SATURN_EXTRA})\nendif()\n";

}  // namespace

std::unordered_set<uint32_t> volatile_literals_of(const FlatImage& img, const std::vector<uint32_t>& prog_code) {
    return volatile_literals(img, prog_code);
}

EmitBuild read_dump(const std::string& path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot read " + path);
    EmitBuild b;
    std::string line;
    std::unordered_map<uint32_t, size_t> fidx;
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        auto w = split(line);
        char k = line[0];
        auto vals = [&](size_t from) {
            std::vector<uint32_t> v;
            for (size_t i = from; i < w.size(); ++i) v.push_back(hx(w[i]));
            return v;
        };
        if (k == 'G') {
            b.native_states = w[1] == "1";
            b.tasks[0] = hx(w[2]), b.tasks[1] = hx(w[3]);
            size_t n = std::stoul(w[4]);
            for (size_t i = 0; i < n; ++i) {
                std::vector<uint32_t> s;
                for (size_t j = 0; j < 5; ++j) s.push_back(hx(w[5 + i * 5 + j]));
                b.task_switches.push_back(s);
            }
            b.runtime = w.back();
        } else if (k == 'M') {
            EmitModule m;
            m.name = w[1], m.base = hx(w[2]), m.path = w[3];
            m.runtime_literals = w[4] == "1", m.callable_entry = w[5] == "1";
            m.unwind_returns = w[6] == "1", m.block_coverage = w[7] == "1";
            b.modules.push_back(std::move(m));
            fidx.clear();
        } else if (k == 'K') {
            for (auto v : vals(1)) b.modules.back().hooks.insert(v);
        } else if (k == 'S') {
            for (auto v : vals(1)) b.modules.back().stack_return_calls.insert(v);
        } else if (k == 'P') {
            b.modules.back().prog_code = vals(1);
        } else if (k == 'F') {
            EmitFunc f;
            f.entry = hx(w[1]);
            f.code = vals(2);
            fidx[f.entry] = b.modules.back().funcs.size();
            b.modules.back().funcs.push_back(std::move(f));
        } else if (k == 'T') {
            auto& f = b.modules.back().funcs.at(fidx.at(hx(w[1])));
            Target t;
            t.how = w[3];
            std::replace(t.how.begin(), t.how.end(), '_', ' ');
            t.cands = vals(4);
            f.targets[hx(w[2])] = std::move(t);
        }
    }
    return b;
}

void generate(const EmitBuild& b, const std::string& out, int per_file, bool comments) {
    std::filesystem::create_directories(out);
    std::vector<std::string> nss, srcs;
    for (auto& m : b.modules) nss.push_back(module_files(b, m, out, per_file, comments, srcs));
    std::string s;
    for (auto& ns : nss) s += "#include \"" + ns + "_funcs.h\"\n";
    s += "\nextern const SH2Module* const g_sh2_modules[] = {\n";
    for (auto& ns : nss) s += "    &" + ns + "::module,\n";
    s += F("};\nextern const int g_sh2_nmodules = %zu;\n", nss.size());
    s += F("extern const bool g_sh2_native_states = %s;\n", b.native_states ? "true" : "false");
    s += F("extern const uint32_t g_sh2_tasks[2] = {0x%08X, 0x%08X};\n", b.tasks[0], b.tasks[1]);
    std::string rows;
    if (b.task_switches.empty()) rows = "{0, 0, 0, 0, 0}";
    for (auto& t : b.task_switches) {
        if (!rows.empty()) rows += ", ";
        std::string r;
        for (auto v : t) { if (!r.empty()) r += ", "; r += F("0x%X", v); }
        rows += "{" + r + "}";
    }
    s += "extern const SH2TaskSwitch g_sh2_task_switches[] = {" + rows + "};\n";
    s += F("extern const int g_sh2_ntask_switches = %zu;\n", b.task_switches.size());
    put(out + "/modules.cpp", s);
    srcs.push_back("modules.cpp");
    std::string c = std::string(CMAKE_HEAD) + b.runtime + "\")\nendif()\nadd_library(recomp STATIC\n    ";
    for (size_t i = 0; i < srcs.size(); ++i) { if (i) c += "\n    "; c += srcs[i]; }
    c += CMAKE_TAIL;
    put(out + "/CMakeLists.txt", c);
}

}  // namespace sf3::gen
