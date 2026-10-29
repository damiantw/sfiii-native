// SF3 recomp, on-console generator: tools/generate.py in C++ (MIT). See profile_gen.h.
#include "profile_gen.h"

#include <algorithm>
#include <cstdarg>
#include <filesystem>
#include <fstream>
#include <map>
#include <regex>
#include <stdexcept>

#include "discovery.h"
#include "hashes.h"
#include "json.h"

namespace fs = std::filesystem;

namespace sf3::gen {
namespace {

std::string read_text(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    if (!in) throw std::runtime_error("cannot read " + p.string());
    return std::string(std::istreambuf_iterator<char>(in), {});
}

std::vector<uint8_t> read_bytes(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    if (!in) throw std::runtime_error("cannot read " + p.string());
    return std::vector<uint8_t>(std::istreambuf_iterator<char>(in), {});
}

int64_t hex(const std::string& s) {
    size_t used = 0;
    long long v = std::stoll(s, &used, 16);
    if (used != s.size()) throw std::runtime_error("not a hexadecimal number: " + s);
    return v;
}

std::string fmt(const char* f, ...) __attribute__((format(printf, 1, 2)));
std::string fmt(const char* f, ...) {
    char b[512];
    va_list ap;
    va_start(ap, f);
    vsnprintf(b, sizeof b, f, ap);
    va_end(ap);
    return b;
}

// A module of the profile (or one expanded from a container), as generate.py reads it.
struct ModuleDef {
    std::string name, file, source_file, base;
    std::vector<std::string> seeds;
    std::optional<std::string> offset, bytes;
    std::vector<int64_t> required_veneer_offsets;
    std::vector<std::string> stack_return_calls;
    bool overlay = false;
};

ModuleDef module_def(const json::Value& m) {
    ModuleDef d;
    d.name = m.at("name").str();
    d.file = m.at("file").str();
    d.base = m.at("base").str();
    if (auto* s = m.find("source_file")) d.source_file = s->str();
    for (auto& s : m.at("seeds").items) d.seeds.push_back(s.str());
    if (auto* o = m.find("offset")) d.offset = o->str();
    if (auto* b = m.find("bytes")) d.bytes = b->str();
    if (auto* r = m.find("required_veneer_offsets")) for (auto& x : r->items) d.required_veneer_offsets.push_back(x.integer());
    if (auto* r = m.find("stack_return_calls")) for (auto& x : r->items) d.stack_return_calls.push_back(x.str());
    if (auto* o = m.find("overlay")) d.overlay = o->truthy();
    return d;
}

const json::Value& manifest_file(const json::Value& manifest, const std::string& name) {
    return manifest.at("files").at("/" + name);
}

// module_images.expand_modules
std::vector<ModuleDef> expand_modules(const json::Value& profile, const json::Value& manifest) {
    std::vector<ModuleDef> modules;
    for (auto& m : profile.at("modules").items) modules.push_back(module_def(m));
    if (auto* containers = profile.find("module_containers")) {
        for (auto& c : containers->items) {
            std::string source = c.at("file").str(), prefix = c.at("prefix").str();
            if (!std::regex_match(source, std::regex("[A-Za-z0-9_]+\\.BIN")) ||
                !std::regex_match(prefix, std::regex("[A-Za-z_][A-Za-z0-9_]*")))
                throw std::runtime_error("Unsafe container name");
            int64_t stride = hex(c.at("chunk_bytes").str());
            const json::Value& cv = c.at("count");
            if (cv.kind != json::Value::Number) throw std::runtime_error("Invalid container layout");
            int64_t count = cv.integer();
            if (count < 1 || count > 256 || stride < 12 || (stride & 3)) throw std::runtime_error("Invalid container layout");
            if (manifest_file(manifest, source).at("size").integer() != stride * count)
                throw std::runtime_error("Container size does not match its verified layout: " + source);
            int64_t base = hex(c.at("base").str());
            if (base < 0 || (base & 1) || base + stride > 0x100000000LL) throw std::runtime_error("Invalid container load address");
            std::vector<int64_t> offsets;
            for (auto& o : c.at("entry_offsets").items) offsets.push_back(o.integer());
            for (int64_t index = 0; index < count; ++index) {
                ModuleDef d;
                d.name = prefix + fmt("%02llX", (long long)index);
                d.file = d.name + ".BIN";
                d.source_file = source;
                d.offset = fmt("%llX", (long long)(stride * index));
                d.bytes = fmt("%llX", (long long)stride);
                d.base = fmt("%08llX", (long long)base);
                d.required_veneer_offsets = offsets;
                for (int64_t o : offsets) d.seeds.push_back(fmt("%08llX", (long long)(base + o)));
                d.overlay = true;
                for (int64_t o : offsets)
                    if (o < 0 || (o & 1) || o >= stride) throw std::runtime_error("Container entry is outside its image");
                std::vector<ModuleDef*> existing;
                for (auto& m : modules) if (m.name == d.name || m.file == d.file) existing.push_back(&m);
                if (!existing.empty()) {
                    const ModuleDef& e = *existing[0];
                    bool same = existing.size() == 1 && e.file == d.file && e.source_file == d.source_file &&
                                e.offset == d.offset && e.bytes == d.bytes && e.base == d.base &&
                                e.required_veneer_offsets == d.required_veneer_offsets && e.overlay == d.overlay;
                    std::set<std::string> have(e.seeds.begin(), e.seeds.end());
                    for (auto& s : d.seeds) if (!have.count(s)) same = false;
                    if (!same) throw std::runtime_error("Container module collides with an existing image: " + d.name);
                } else {
                    modules.push_back(d);
                }
            }
        }
    }
    return modules;
}

// module_images.image_bytes
std::vector<uint8_t> image_bytes(const ModuleDef& m, const std::vector<uint8_t>& original) {
    int64_t offset = hex(m.offset.value_or("0"));
    int64_t count = m.bytes ? hex(*m.bytes) : int64_t(original.size());
    if (offset < 0 || count < 1 || offset > int64_t(original.size()) - count)
        throw std::runtime_error("Module image extends outside its verified source: " + m.file);
    if (!m.source_file.empty() && (!m.offset || !m.bytes))
        throw std::runtime_error("Container module needs an exact offset and length");
    std::vector<uint8_t> data(original.begin() + offset, original.begin() + offset + count);
    int64_t base = hex(m.base);
    if (base < 0 || (base & 1) || base + count > 0x100000000LL) throw std::runtime_error("Invalid module load address: " + m.file);
    for (auto& s : m.seeds) {
        int64_t e = hex(s);
        if ((e & 1) || !(base <= e && e <= base + count - 2))
            throw std::runtime_error("Module entry is outside its image or unaligned: " + m.file);
    }
    auto at_bytes = [&](int64_t at, std::initializer_list<uint8_t> want) {
        size_t i = 0;
        for (uint8_t w : want) if (data[size_t(at) + i++] != w) return false;
        return true;
    };
    for (auto& pc : m.stack_return_calls) {
        int64_t at = hex(pc) - base;
        if ((at & 1) || at < 2 || at + 6 > int64_t(data.size()) || !at_bytes(at - 2, {0x4f, 0x22, 0x40, 0x0b}) ||
            !at_bytes(at + 4, {0x4f, 0x26}))
            throw std::runtime_error("Stack-return call must have its verified PR-save/call/restore wrapper: " + m.file);
    }
    for (int64_t at : m.required_veneer_offsets) {
        if (at < 0 || at + 12 > int64_t(data.size()) || !at_bytes(at, {0xd0, 0x01, 0x40, 0x2b, 0x00, 0x09, 0x00, 0x09}))
            throw std::runtime_error("Container export header is invalid: " + m.file);
        uint32_t target = uint32_t(data[at + 8]) << 24 | uint32_t(data[at + 9]) << 16 | uint32_t(data[at + 10]) << 8 | data[at + 11];
        if ((target & 1) || !(base <= target && target <= base + int64_t(data.size()) - 2))
            throw std::runtime_error("Container export points outside its image: " + m.file);
    }
    return data;
}

uint32_t word16(const std::vector<uint8_t>& d, int64_t at) {    // int.from_bytes(data[at:at+2]): short at the end
    if (at < 0) return 0;
    uint32_t v = 0;
    for (int64_t i = at; i < at + 2 && i < int64_t(d.size()); ++i) v = v << 8 | d[size_t(i)];
    return v;
}

// scene_data_entries.plausible_code: "" if a straight walk reads as code, else why not.
std::string plausible_code(const FlatImage& img, uint32_t start, const USet& pools) {
    int64_t pc = start;
    for (int i = 0; i < 256; ++i) {
        if (!img.contains(uint32_t(pc), 2) || pc > 0xFFFFFFFF) return fmt("runs off the image at %08llX", (long long)pc);
        if (pools.count(uint32_t(pc))) return fmt("runs into a literal pool at %08llX", (long long)pc);
        Insn ins = img.insn(uint32_t(pc));
        if (ins.is(".word")) return fmt("illegal %04X at %08llX", ins.word, (long long)pc);
        if (ins.target && !img.contains(*ins.target, ins.size ? ins.size : 2))
            return fmt("%s target %08X outside the image at %08llX", ins.op, *ins.target, (long long)pc);
        if (ins.delay) {
            int64_t slot_pc = pc + 2;
            if (!img.contains(uint32_t(slot_pc), 2) || pools.count(uint32_t(slot_pc)))
                return fmt("no delay slot at %08llX", (long long)slot_pc);
            Insn slot = img.insn(uint32_t(slot_pc));
            if (slot.is(".word") || slot.delay || slot.is("bt") || slot.is("bf"))
                return fmt("illegal delay slot %04X at %08llX", slot.word, (long long)slot_pc);
            if (ins.is("rts") || ins.is("rte") || ins.is("jmp") || ins.is("bra") || ins.is("braf")) return "";
            pc += 4;
            continue;
        }
        pc += 2;
    }
    return "no unconditional branch within 256 instructions";
}

// scene_data_entries.data_table_entries
std::set<uint32_t> data_table_entries(const FlatImage& img, const Program& prog, const std::string& name,
                                      std::vector<SceneRow>& rows) {
    std::vector<uint32_t> code_v = prog.sorted_code();
    USet code(code_v.begin(), code_v.end());
    USet pools;
    for (uint32_t a : code_v) {
        Insn ins = img.insn(a);
        if ((ins.is("mov.w") || ins.is("mov.l")) && ins.size && img.contains(*ins.target, ins.size))
            for (uint32_t k = *ins.target; k < *ins.target + ins.size; k += 2) pools.insert(k);
    }
    std::map<uint32_t, std::vector<uint32_t>> refs;
    int64_t first = int64_t(img.base) + ((4 - int64_t(img.base) % 4) % 4);
    for (int64_t at = first; at < int64_t(img.end()) - 3; at += 4) {
        uint32_t a = uint32_t(at);
        if (code.count(a) || code.count(a + 2) || pools.count(a)) continue;
        uint32_t value = img.u32(a);
        if (img.base <= value && int64_t(value) < int64_t(img.end()) - 1 && !(value & 1)) refs[value].push_back(a);
    }
    std::set<uint32_t> accepted;
    for (auto& [target, at] : refs) {
        SceneRow r{name, target, "", "", at};
        if (prog.func_index.count(target)) r.verdict = "known", r.reason = "already an entry";
        else if (code.count(target)) r.verdict = "rejected", r.reason = "inside known code";
        else if (pools.count(target)) r.verdict = "rejected", r.reason = "a literal-pool slot";
        else {
            r.reason = plausible_code(img, target, pools);
            r.verdict = r.reason.empty() ? "accepted" : "rejected";
            if (r.reason.empty()) {
                accepted.insert(target);
                r.reason = "plausible code";
            }
        }
        rows.push_back(r);
    }
    if (name == "X1JASN01" || name == "X1FUTTIN") {      // REGRESSION_SEEDS
        uint32_t target = 0x0605E06C;
        if (!refs.count(target) && img.contains(target, 2)) {
            if (prog.func_index.count(target)) {
                rows.push_back({name, target, "known", "already an entry (regression seed)", {}});
            } else {
                std::string reason = code.count(target) ? "inside known code" : plausible_code(img, target, pools);
                if (!reason.empty()) rows.push_back({name, target, "rejected", reason + " (regression seed)", {}});
                else {
                    accepted.insert(target);
                    rows.push_back({name, target, "accepted", "regression seed, plausible code", {}});
                }
            }
        }
    }
    return accepted;
}

}  // namespace

std::set<uint32_t> idiom_entries(const std::vector<uint8_t>& data, uint32_t base) {
    std::set<uint32_t> out;
    int64_t len = int64_t(data.size());
    auto word = [&](int64_t at) { return word16(data, at); };
    // registered_store_callback_entries
    for (int64_t at = 0; at < len - 11; at += 2) {
        if (((base + at) & 1) || (word(at) & 0xFF00) != 0xC700) continue;
        if (word(at + 2) != 0x6543 || word(at + 4) != 0x6403 || word(at + 8) != 0x402B || word(at + 10) != 0x0009) continue;
        if ((word(at + 6) & 0xFF00) != 0xD000) continue;
        int64_t target = ((int64_t(base) + at + 4) & ~int64_t(3)) + (word(at) & 255) * 4;
        int64_t literal = ((int64_t(base) + at + 10) & ~int64_t(3)) + (word(at + 6) & 255) * 4;
        int64_t off = target - base;
        if (!(0 <= off && off <= len - 6 && base <= literal && literal <= base + len - 4)) continue;
        if ((word(off) & 0xFF00) != 0xC700 || word(off + 2) != 0x000B || word(off + 4) != 0x2041) continue;
        int64_t destination = ((target + 4) & ~int64_t(3)) + (word(off) & 255) * 4;
        if (base <= destination && destination <= base + len - 2) out.insert(uint32_t(target));
    }
    // unrolled_copy_entries
    {
        std::vector<uint8_t> pattern;
        for (int n = 15; n >= 0; --n)
            for (uint32_t w : {0x5050u | n, 0x1400u | n}) pattern.push_back(uint8_t(w >> 8)), pattern.push_back(uint8_t(w));
        for (int64_t off = 0; off < len - 67; off += 2) {
            if ((base + off) & 1) continue;
            if (!std::equal(pattern.begin(), pattern.end(), data.begin() + off)) continue;
            const uint8_t* t = data.data() + off + 64;
            bool ok = (t[0] == 0x00 && t[1] == 0x0b && t[2] == 0x00 && t[3] == 0x09) ||
                      (t[0] == 0x00 && t[1] == 0x0b && t[2] == 0x20 && t[3] == 0x0b);
            if (!ok) continue;
            for (int n = 0; n < 17; ++n) out.insert(uint32_t(base + off + n * 4));
        }
    }
    // arithmetic_shift_entries
    for (uint32_t r = 0; r < 16; ++r) {
        uint32_t shar = 0x4021 | r << 8;
        std::vector<uint32_t> words(6, shar);
        for (uint32_t w : {0x4029 | r << 8, 0x4019 | r << 8, 0x000Bu, 0x600E | r << 8 | r << 4}) words.push_back(w);
        for (int i = 0; i < 7; ++i) words.push_back(shar);
        for (uint32_t w : {0x4029 | r << 8, 0x000Bu, 0x600F | r << 8 | r << 4}) words.push_back(w);
        for (int i = 0; i < 14; ++i) words.push_back(shar);
        for (uint32_t w : {0x000Bu, shar, 0x000Bu, 0x0009u}) words.push_back(w);
        std::vector<uint8_t> pattern;
        for (uint32_t w : words) pattern.push_back(uint8_t(w >> 8)), pattern.push_back(uint8_t(w));
        auto it = data.begin();
        while (true) {
            it = std::search(it, data.end(), pattern.begin(), pattern.end());
            if (it == data.end()) break;
            int64_t at = it - data.begin();
            if (!((base + at) & 1))
                for (int64_t off = 0; off < int64_t(pattern.size()); off += 2)
                    if (off != 18 && off != 38 && off != 70 && off != 74) out.insert(uint32_t(base + at + off));
            ++it;
        }
    }
    // the export veneer: mov.l @(PC),r0; jmp @r0; nop; nop; target
    static const uint8_t veneer[8] = {0xd0, 0x01, 0x40, 0x2b, 0x00, 0x09, 0x00, 0x09};
    for (int64_t at = 0; at < len - 11; at += 4) {
        if (!std::equal(veneer, veneer + 8, data.begin() + at)) continue;
        uint32_t target = uint32_t(data[at + 8]) << 24 | uint32_t(data[at + 9]) << 16 | uint32_t(data[at + 10]) << 8 | data[at + 11];
        if (base <= target && target < base + len && target % 2 == 0) out.insert(uint32_t(base + at));
    }
    return out;
}

std::vector<Spec> prepare_specs(const GenOptions& o, std::vector<SceneRow>& scene_rows) {
    fs::path work = fs::absolute(o.work);
    json::Value profile = json::parse(read_text(o.profile));
    // disc_profile.verify_inventory
    json::Value manifest = json::parse(read_text(work / "manifest.json"));
    if (auto* c = profile.find("content_sha256"); c && c->truthy()) {
        std::string canon;
        json::dump_sorted(manifest, canon);
        if (sha256_hex(reinterpret_cast<const uint8_t*>(canon.data()), canon.size()) != c->str())
            throw std::runtime_error("Inventory contents do not match the selected revision profile");
    } else {
        json::Value hashes = json::parse(read_text(work / "hashes.json"));
        bool found = false;
        for (auto& [_, v] : hashes.fields) if (v.at("sha256").str() == profile.at("track1_sha256").str()) found = true;
        if (!found) throw std::runtime_error("Inventory revision does not match profile");
    }
    std::vector<Spec> specs;
    std::map<std::string, std::vector<uint8_t>> sources;
    for (const ModuleDef& m : expand_modules(profile, manifest)) {
        // module_images.verified_source
        std::string src = m.source_file.empty() ? m.file : m.source_file;
        if (!std::regex_match(src, std::regex("[A-Za-z0-9_]+\\.BIN"))) throw std::runtime_error("Unsafe module source filename");
        fs::path source = work / "extract" / src;
        auto cached = sources.find(src);
        if (cached == sources.end()) {
            std::vector<uint8_t> d = read_bytes(source);
            const json::Value& want = manifest_file(manifest, src);
            if (int64_t(d.size()) != want.at("size").integer() || sha1_hex(d.data(), d.size()) != want.at("sha1").str())
                throw std::runtime_error("Extracted module changed: " + src);
            cached = sources.emplace(src, std::move(d)).first;
        }
        std::vector<uint8_t> data = image_bytes(m, cached->second);
        if (m.bytes || m.offset) {
            if (!std::regex_match(m.file, std::regex("[A-Za-z0-9_]+\\.BIN"))) throw std::runtime_error("Unsafe module filename");
            fs::path prepared = work / "modules" / m.file;
            fs::create_directories(prepared.parent_path());
            std::ofstream out(prepared, std::ios::binary | std::ios::trunc);
            out.write(reinterpret_cast<const char*>(data.data()), std::streamsize(data.size()));
            if (!out) throw std::runtime_error("cannot write " + prepared.string());
            source = prepared;
        }
        uint32_t base = uint32_t(hex(m.base));
        std::set<uint32_t> seeds;
        for (auto& s : m.seeds) seeds.insert(uint32_t(hex(s)));
        for (uint32_t s : idiom_entries(data, base)) seeds.insert(s);
        if (std::regex_match(m.name, std::regex("X1[A-Z0-9_]+"))) {
            FlatImage img;
            img.base = base;
            img.data = data;
            std::vector<uint32_t> ps{base};
            for (uint32_t s : seeds) if (s != base) ps.push_back(s);
            Program prog(img, ps);
            size_t before = scene_rows.size();
            auto found = data_table_entries(img, prog, m.name, scene_rows);
            seeds.insert(found.begin(), found.end());
            size_t rejected = 0;
            for (size_t i = before; i < scene_rows.size(); ++i) rejected += scene_rows[i].verdict == "rejected";
            if (o.log)
                o.log(fmt("%s: scene data-table entries: %zu accepted, %zu rejected", m.name.c_str(), found.size(), rejected));
        }
        Spec s;
        s.name = m.name;
        s.path = source.string();
        s.base = base;
        s.seeds.assign(seeds.begin(), seeds.end());
        s.overlay = m.overlay;
        for (auto& pc : m.stack_return_calls) s.stack_return_calls.insert(uint32_t(hex(pc)));
        specs.push_back(std::move(s));
    }
    return specs;
}

EmitBuild discover_build(const std::vector<Spec>& specs, const GenOptions& o) {
    EmitBuild b;
    b.native_states = true;
    b.runtime = o.runtime;
    for (const Spec& s : specs) {
        EmitModule m;
        m.name = s.name, m.path = s.path, m.base = s.base;
        m.runtime_literals = true;
        m.callable_entry = s.overlay;
        m.block_coverage = o.block_coverage;
        m.stack_return_calls = s.stack_return_calls;
        FlatImage img;
        img.base = s.base;
        img.data = read_bytes(s.path);
        std::vector<uint32_t> seeds{s.base};
        seeds.insert(seeds.end(), s.seeds.begin(), s.seeds.end());
        Program p(img, seeds);
        m.prog_code = p.sorted_code();
        USet all_code;
        for (auto& f : p.funcs) all_code.insert(f->code.begin(), f->code.end());
        for (uint32_t pc : s.stack_return_calls) {
            Insn ins = img.insn(pc);
            if (!all_code.count(pc) || !(ins.is("jsr") || ins.is("bsrf")))
                throw std::runtime_error("Configured stack-return call is not a discovered indirect call");
        }
        USet vol = volatile_literals_of(img, m.prog_code);
        for (uint32_t a : m.prog_code) {
            Insn ins = img.insn(a);
            if ((ins.is("mov.w") || ins.is("mov.l")) && ins.size) vol.insert(*ins.target);
        }
        for (auto& f : p.funcs) {
            EmitFunc ef;
            ef.entry = f->entry;
            ef.code.assign(f->code.begin(), f->code.end());
            std::sort(ef.code.begin(), ef.code.end());
            ef.targets = p.resolve(*f, vol);
            m.funcs.push_back(std::move(ef));
        }
        b.modules.push_back(std::move(m));
    }
    return b;
}

void generate_from_profile(const GenOptions& o) {
    std::vector<SceneRow> rows;
    auto specs = prepare_specs(o, rows);
    fs::create_directories(o.out);
    {
        std::ofstream log(fs::path(o.out) / "scene-data-entries.tsv", std::ios::binary | std::ios::trunc);
        log << "module\ttarget\tverdict\treason\ttable_words\n";
        for (auto& r : rows) {
            log << r.module << '\t' << fmt("%08X", r.target) << '\t' << r.verdict << '\t' << r.reason << '\t';
            for (size_t i = 0; i < r.refs.size(); ++i) log << (i ? " " : "") << fmt("%08X", r.refs[i]);
            log << '\n';
        }
    }
    EmitBuild b = discover_build(specs, o);
    generate(b, o.out, o.per_file, o.comments);
}

}  // namespace sf3::gen
