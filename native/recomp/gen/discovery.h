// SF3 recomp, on-console generator: function discovery for flat SH-2 programs, a C++ port of
// saturn-recomp's recomp/discover.py (Program and its passes) and emit.py's Body._resolve (MIT).
//
// It must decide exactly what the Python decides (the same functions, in the same order, the same
// code, the same switch tables), since the emitted tree is checked byte for byte against the
// Python's: tools/ps5/check-discovery.sh compares it with gen-dump-discovery.py's dump.
#pragma once
#include <array>
#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "emit_cpp.h"
#include "sh2_text.h"

namespace sf3::gen {

using USet = std::unordered_set<uint32_t>;

// A set of halfword addresses, mostly inside one image: a bitmap there, a hash set elsewhere.
class AddrSet {
public:
    void init(uint32_t lo, uint32_t hi) { lo_ = lo, hi_ = hi, bits_.assign((hi - lo + 1) / 2, 0); }
    bool has(int64_t a) const {
        if (a >= lo_ && a < hi_ && !(a & 1)) return bits_[size_t(a - lo_) >> 1];
        return a >= 0 && a <= 0xFFFFFFFF && extra_.count(uint32_t(a));
    }
    bool add(uint32_t a) {
        bool fresh;
        if (a >= lo_ && a < hi_ && !(a & 1)) {
            uint8_t& b = bits_[(a - lo_) >> 1];
            fresh = !b, b = 1;
        } else {
            fresh = extra_.insert(a).second;
        }
        n_ += fresh;
        return fresh;
    }
    size_t size() const { return n_; }
    std::vector<uint32_t> sorted() const;
private:
    uint32_t lo_ = 0, hi_ = 0;
    std::vector<uint8_t> bits_;
    USet extra_;
    size_t n_ = 0;
};

// A set of ints laid out as CPython 3.13's set (Objects/setobject.c: linear probes, perturbation,
// resizes, set_merge), so that iterating it gives the Python's order: discovery pushes
// `f.calls | f.tails` onto its work stack in that order, and the order decides which function
// claims shared code first.
class PySet {
public:
    PySet() { table_.assign(8, kEmpty); }
    bool add(uint32_t key);
    bool count(uint32_t key) const;
    size_t size() const { return used_; }
    template <class F> void each(F f) const { for (int64_t k : table_) if (k != kEmpty) f(uint32_t(k)); }
    // a | b: a copy of a, then b merged in (set_or).
    static PySet merged(const PySet& a, const PySet& b);
    std::vector<uint32_t> values() const { std::vector<uint32_t> v; each([&](uint32_t k) { v.push_back(k); }); return v; }
private:
    static constexpr int64_t kEmpty = -1;
    std::vector<int64_t> table_;
    size_t fill_ = 0, used_ = 0;
    size_t mask() const { return table_.size() - 1; }
    static void insert_clean(std::vector<int64_t>& t, uint32_t key);
    void resize(size_t minused);
    void merge(const PySet& o);
};

struct Function {
    uint32_t entry = 0;
    USet code, tables, slot_only;
    PySet calls, tails;
    std::vector<std::pair<uint32_t, const char*>> unresolved;
    bool bad = false;
};

struct Switch { std::vector<uint32_t> targets; int64_t table = 0, size = 0; };
using Switches = std::unordered_map<uint32_t, std::vector<uint32_t>>;
using RegState = std::array<int64_t, 16>;    // -1: unknown

class Program {
public:
    Program(const FlatImage& img, std::vector<uint32_t> seeds);

    const FlatImage& img;
    uint32_t lo, hi;
    std::vector<std::unique_ptr<Function>> funcs;   // insertion (dict) order
    std::unordered_map<uint32_t, size_t> func_index;
    AddrSet code, data, tables;
    Switches switches;

    std::vector<uint32_t> sorted_code() const { return code.sorted(); }
    // Body._resolve for one function: {site: (candidates, how)}.
    std::map<uint32_t, Target> resolve(const Function&, const USet& volatile_slots) const;

private:
    struct Lit { int kind = 0; uint32_t v = 0, slot = 0; };      // 0 none, 1 lit, 2 ptr
    struct Val;
    using VP = std::shared_ptr<const Val>;

    std::vector<uint32_t> pending_;
    USet rejected_, data_addrs_, lits_;
    std::optional<USet> indexed_;
    std::vector<uint32_t> code_order_;       // prog.code in the order it grew (incremental scans)
    size_t scanned_ = 0, lit_scanned_ = 0;

    Insn insn(int64_t a) const { return img.insn(uint32_t(a)); }
    bool inside(int64_t a) const { return lo <= a && a < hi && !(a & 1); }
    bool contains(int64_t a, int64_t size = 2) const { return img.base <= a && a + size <= int64_t(img.end()); }
    bool has_func(uint32_t a) const { return func_index.count(a); }

    Lit literal_for(int64_t at, int reg, int limit = 24) const;
    std::optional<Switch> abs_switch(uint32_t jmp) const;
    std::optional<Switch> byte_switch(uint32_t jmp) const;
    std::optional<Switch> byte_switch_offset(uint32_t jmp) const;
    std::optional<Switch> byte_targets(uint32_t jmp, std::optional<uint32_t> tab, int64_t k, int idx,
                                       std::optional<uint32_t> base) const;
    std::optional<Switch> mova_switch(uint32_t jmp, std::optional<uint32_t> before = std::nullopt) const;
    VP jump_value(uint32_t jump, int window = 16) const;
    std::optional<Switch> relative_word_switch(uint32_t jump) const;
    std::optional<Switch> branch_table_switch(uint32_t jump) const;
    std::optional<uint32_t> mova_base(uint32_t jmp) const;
    std::optional<Switch> record_switch(uint32_t jmp) const;
    std::optional<int64_t> switch_bound(int64_t at, int size) const;
    std::optional<int64_t> skipped_bra(int64_t a) const;
    bool out_of_range(int64_t b) const;
    std::optional<int64_t> reg_const(int64_t at, int reg) const;
    std::optional<Switch> braf_switch(uint32_t braf) const;
    std::unordered_map<uint32_t, RegState> constants(const USet& code, uint32_t entry, const USet& wanted,
                                                     const Switches* local) const;
    std::pair<std::unique_ptr<Function>, USet> descend(uint32_t entry, bool commit);
    void walk(Function& f, uint32_t a, USet& data, Switches& sw, std::vector<uint32_t>& work,
              std::vector<std::pair<uint32_t, bool>>& pending) const;
    void run();
    bool boundary(int64_t a) const;
    const USet& data_addresses();
    const USet& indexed_tables();
    int pointer_seeds();
    bool through_pointers(const USet& code) const;
    const USet& literal_values();
    bool is_text(int64_t a) const;
    bool is_pointers(int64_t a) const;
    int address_taken();
    int prologue_seeds();
    bool after_pointer(int64_t a) const;
    int take(uint32_t c, size_t at_least = 0);
    std::vector<std::pair<uint32_t, uint32_t>> gaps() const;
    void push_pending(const Function& f);
    friend struct Back;
};

}  // namespace sf3::gen
