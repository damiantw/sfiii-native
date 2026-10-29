// SF3 recomp, on-console generator: a C++ port of saturn-recomp's recomp/discover.py (MIT).
// Every pass, helper and iteration order follows the Python: see discovery.h.
#include "discovery.h"

#include <algorithm>
#include <cstring>

namespace sf3::gen {
namespace {

bool op_in(const Insn& i, std::initializer_list<const char*> ops) {
    for (const char* o : ops) if (!strcmp(i.op, o)) return true;
    return false;
}
bool is_flow(const Insn& i) {
    return op_in(i, {"bt", "bf", "bt/s", "bf/s", "bra", "bsr", "jmp", "jsr", "rts", "rte", "braf", "bsrf"});
}
bool is_stop(const Insn& i) { return op_in(i, {"bra", "jmp", "rts", "rte", "braf"}); }
bool has(std::string_view f, const char* s) { return f.find(s) != std::string_view::npos; }

// discover._writes as a bit mask of registers.
uint32_t writes(const Insn& ins) {
    std::string_view f = ins.fmt;
    uint32_t out = 0;
    auto add = [&](int r) { if (r >= 0) out |= 1u << r; };
    std::string_view first = f.substr(0, f.find(' '));
    if (f.ends_with("Rn") && ins.n >= 0) add(ins.n);
    else if (f.ends_with(",r0") || ins.is("mova")) add(0);
    else if (ins.is("movt") || ins.is("dt") || (first == ins.op && f.ends_with("Rn"))) add(ins.n);
    if (has(f, "@Rm+") && ins.m >= 0) add(ins.m);
    if (has(f, "@-Rn") && ins.n >= 0) add(ins.n);
    return out;
}
bool writes_reg(const Insn& ins, int r) { return r >= 0 && (writes(ins) >> r & 1); }

void transfer(const FlatImage& img, const Insn& ins, RegState& st) {
    if (op_in(ins, {"jsr", "bsr", "bsrf"})) {
        for (int r = 0; r < 8; ++r) st[r] = -1;
        return;
    }
    if (ins.target && (ins.is("mov.l") || ins.is("mov.w")) && ins.size) {
        auto v = img.literal(ins);
        st[ins.n] = v ? int64_t(*v) : -1;
        return;
    }
    if (ins.is("mova")) { st[0] = *ins.target; return; }
    if (ins.is("mov") && ins.imm) { st[ins.n] = uint32_t(*ins.imm); return; }
    if (ins.is("mov") && ins.fmt == "mov Rm,Rn") { st[ins.n] = st[ins.m]; return; }
    if (ins.is("add") && ins.imm) {
        int64_t v = st[ins.n];
        st[ins.n] = v < 0 ? -1 : int64_t(uint32_t(v + *ins.imm));
        return;
    }
    uint32_t w = writes(ins);
    for (int r = 0; r < 16; ++r) if (w >> r & 1) st[r] = -1;
}

bool is_prologue(uint32_t w) {
    return ((w & 0xFF0F) == 0x2F06 && 8 <= ((w >> 4) & 15) && ((w >> 4) & 15) <= 14) || w == 0x4F22 ||
           (w & 0xFF80) == 0x7F80;
}

int64_t floordiv(int64_t a, int64_t b) { int64_t q = a / b; return (a % b != 0 && ((a < 0) != (b < 0))) ? q - 1 : q; }

std::vector<uint32_t> sorted_of(const USet& s) {
    std::vector<uint32_t> v(s.begin(), s.end());
    std::sort(v.begin(), v.end());
    return v;
}

const std::pair<const char*, int> kLoads[] = {
    {"mov.b @(r0,Rm),Rn", 1}, {"mov.w @(r0,Rm),Rn", 2}, {"mov.l @(r0,Rm),Rn", 4}};
int load_size(std::string_view f) {
    for (auto& [s, n] : kLoads) if (f == s) return n;
    return 0;
}

}  // namespace

std::vector<uint32_t> AddrSet::sorted() const {
    std::vector<uint32_t> out;
    out.reserve(n_);
    std::vector<uint32_t> ex(extra_.begin(), extra_.end());
    std::sort(ex.begin(), ex.end());
    size_t e = 0;
    for (size_t i = 0; i < bits_.size(); ++i) {
        if (!bits_[i]) continue;
        uint32_t a = lo_ + uint32_t(i) * 2;
        while (e < ex.size() && ex[e] < a) out.push_back(ex[e++]);
        out.push_back(a);
    }
    while (e < ex.size()) out.push_back(ex[e++]);
    return out;
}

bool PySet::count(uint32_t key) const {
    size_t m = mask(), i = key & m, perturb = key;
    while (true) {
        size_t probes = (i + 9 <= m) ? 9 : 0;
        size_t j = i;
        do {
            if (table_[j] == kEmpty) return false;
            if (table_[j] == int64_t(key)) return true;
            ++j;
        } while (probes--);
        perturb >>= 5;
        i = (i * 5 + 1 + perturb) & m;
    }
}

bool PySet::add(uint32_t key) {
    size_t m = mask(), i = key & m, perturb = key;
    while (true) {
        size_t probes = (i + 9 <= m) ? 9 : 0;
        size_t j = i;
        do {
            if (table_[j] == kEmpty) {
                table_[j] = key;
                ++fill_, ++used_;
                if (fill_ * 5 >= m * 3) resize(used_ > 50000 ? used_ * 2 : used_ * 4);
                return true;
            }
            if (table_[j] == int64_t(key)) return false;
            ++j;
        } while (probes--);
        perturb >>= 5;
        i = (i * 5 + 1 + perturb) & m;
    }
}

void PySet::insert_clean(std::vector<int64_t>& t, uint32_t key) {
    size_t m = t.size() - 1, i = key & m, perturb = key;
    while (true) {
        if (t[i] == kEmpty) { t[i] = key; return; }
        if (i + 9 <= m)
            for (size_t j = 1; j <= 9; ++j)
                if (t[i + j] == kEmpty) { t[i + j] = key; return; }
        perturb >>= 5;
        i = (i * 5 + 1 + perturb) & m;
    }
}

void PySet::resize(size_t minused) {
    size_t n = 8;
    while (n <= minused) n <<= 1;
    std::vector<int64_t> t(n, kEmpty);
    for (int64_t k : table_) if (k != kEmpty) insert_clean(t, uint32_t(k));
    table_ = std::move(t);
    fill_ = used_;
}

void PySet::merge(const PySet& o) {
    if (&o == this || o.used_ == 0) return;
    if ((fill_ + o.used_) * 5 >= mask() * 3) resize((used_ + o.used_) * 2);
    if (fill_ == 0 && mask() == o.mask() && o.fill_ == o.used_) {
        table_ = o.table_;
        fill_ = o.fill_, used_ = o.used_;
        return;
    }
    if (fill_ == 0) {
        fill_ = used_ = o.used_;
        for (int64_t k : o.table_) if (k != kEmpty) insert_clean(table_, uint32_t(k));
        return;
    }
    for (int64_t k : o.table_) if (k != kEmpty) add(uint32_t(k));
}

PySet PySet::merged(const PySet& a, const PySet& b) {
    PySet r;
    r.merge(a);
    r.merge(b);
    return r;
}

// _back: up to `count` addresses walking back from `at`, over a skipped `bra`.
struct Back {
    const Program& p;
    int64_t a;
    int count;
    Back(const Program& p, int64_t at, int count) : p(p), a(at - 2), count(count) {}
    bool next(int64_t& out) {
        if (count <= 0) return false;
        if (p.inside(a - 2) && p.insn(a - 2).is("bra")) {
            auto c = p.skipped_bra(a - 2);
            if (c) a = p.insn(*c).delay ? *c + 2 : *c;
        }
        out = a;
        a -= 2;
        --count;
        return true;
    }
};

struct Program::Val {
    char k;               // 'l' lit, 'm' mask, 'w' word, 'a' add
    int64_t v = 0;
    VP a, b;              // word: a = base; add: a, b
    std::optional<int64_t> m;
};

Program::Program(const FlatImage& image, std::vector<uint32_t> seeds) : img(image), lo(image.base), hi(image.end()) {
    code.init(lo, hi), data.init(lo, hi), tables.init(lo, hi);
    pending_ = seeds.empty() ? std::vector<uint32_t>{img.base} : std::move(seeds);
    run();
}

Program::Lit Program::literal_for(int64_t at, int reg, int limit) const {
    int64_t a = at - 2;
    int want = reg;
    for (int i = 0; i < limit; ++i) {
        if (!inside(a) || data.has(a)) return {};
        Insn ins = insn(a);
        if (is_flow(ins)) return {};
        if (writes_reg(ins, want)) {
            if (ins.is("mov.l") && ins.size == 4 && ins.target) {
                auto v = img.literal(ins);
                return v ? Lit{1, *v, *ins.target} : Lit{};
            }
            if (ins.is("mov.l") && (ins.fmt == "mov.l @Rm,Rn" || ins.fmt == "mov.l @(disp,Rm),Rn")) {
                Lit inner = literal_for(a, ins.m, limit);
                if (inner.kind) return {2, inner.v, 0};
                return {};
            }
            if (ins.is("mov") && ins.fmt == "mov Rm,Rn") {
                want = ins.m;
                a -= 2;
                continue;
            }
            return {};
        }
        a -= 2;
    }
    return {};
}

std::optional<Switch> Program::abs_switch(uint32_t jmp) const {
    Insn j = insn(jmp);
    int64_t at = int64_t(jmp) - 2;
    {
        Insn x = insn(at);
        if (!x.is("mov.l") && !writes_reg(x, j.n)) at -= 2;
    }
    Insn ld = insn(at);
    if (!ld.is("mov.l") || ld.fmt != "mov.l @(r0,Rm),Rn" || ld.n != j.n) return {};
    Lit lit = literal_for(at, ld.m);
    if (lit.kind != 1) return {};
    int64_t table = lit.v;
    if (at != int64_t(jmp) - 2) {
        auto near = [&](int64_t v) { return !(v & 1) && std::llabs(v - int64_t(jmp)) < 0x1000 && inside(v); };
        int k = 0;
        while (k < 256 && contains(table + 4 * k, 4) && near(img.u32(uint32_t(table + 4 * k)))) ++k;
        if (k < 2) return {};
        Switch s{{}, table, 4 * k};
        for (int i = 0; i < k; ++i) s.targets.push_back(img.u32(uint32_t(table + 4 * i)));
        return s;
    }
    std::optional<int64_t> n;
    int64_t a = int64_t(jmp) - 4;
    for (int i = 0; i < 8; ++i) {
        Insn ins = insn(a);
        if (ins.is("cmp/hs") && ins.m == 0) {
            Insn nxt = insn(a + 2);
            for (int64_t b = a - 2; b > a - 12; b -= 2) {
                Insn k = insn(b);
                if (k.is("mov") && k.imm && k.n == ins.n) {
                    if (op_in(nxt, {"bf", "bf/s"})) n = floordiv(*k.imm, 4) + 1;
                    else n.reset();
                    break;
                }
            }
            break;
        }
        a -= 2;
    }
    if (!n || *n == 0 || *n > 1024 || !contains(table, 4 * *n)) return {};
    Switch s{{}, table, 4 * *n};
    for (int64_t k = 0; k < *n; ++k) s.targets.push_back(img.u32(uint32_t(table + 4 * k)));
    return s;
}

std::optional<Switch> Program::byte_switch(uint32_t jmp) const {
    Insn t1 = insn(int64_t(jmp) - 10), add1 = insn(int64_t(jmp) - 8), ldb = insn(int64_t(jmp) - 6),
         t2 = insn(int64_t(jmp) - 4), add2 = insn(int64_t(jmp) - 2);
    Insn j = insn(jmp);
    if (!(t1.is("mov.l") && t1.size == 4 && add1.is("add") && add1.fmt == "add Rm,Rn" && add1.n == t1.n &&
          ldb.fmt == "mov.b @Rm,Rn" && ldb.m == t1.n && t2.is("mov.l") && t2.size == 4 && t2.n == j.n &&
          add2.fmt == "add Rm,Rn" && add2.n == j.n && add2.m == ldb.n))
        return {};
    return byte_targets(jmp, img.literal(t1), 0, add1.m, img.literal(t2));
}

std::optional<Switch> Program::byte_switch_offset(uint32_t jmp) const {
    Insn t1 = insn(int64_t(jmp) - 12), addk = insn(int64_t(jmp) - 10), add1 = insn(int64_t(jmp) - 8),
         ldb = insn(int64_t(jmp) - 6), t2 = insn(int64_t(jmp) - 4), add2 = insn(int64_t(jmp) - 2);
    Insn j = insn(jmp);
    if (!(t1.is("mov.l") && t1.size == 4 && addk.is("add") && addk.imm && add1.fmt == "add Rm,Rn" &&
          add1.m == t1.n && add1.n == addk.n && ldb.fmt == "mov.b @Rm,Rn" && ldb.m == add1.n && t2.is("mov.l") &&
          t2.size == 4 && t2.n == j.n && add2.fmt == "add Rm,Rn" && add2.n == j.n && add2.m == ldb.n))
        return {};
    return byte_targets(jmp, img.literal(t1), *addk.imm, addk.n, img.literal(t2));
}

std::optional<Switch> Program::byte_targets(uint32_t jmp, std::optional<uint32_t> tab, int64_t k, int idx,
                                            std::optional<uint32_t> base) const {
    std::optional<int64_t> n;
    for (int64_t a = int64_t(jmp) - 12; a > int64_t(jmp) - 40; a -= 2) {
        Insn ins = insn(a);
        if (ins.is("cmp/ge") && ins.n == idx) {
            for (int64_t b = a - 2; b > a - 12; b -= 2) {
                Insn mv = insn(b);
                if (mv.is("mov") && mv.imm && mv.n == ins.m) {
                    n = *mv.imm;
                    break;
                }
            }
            break;
        }
    }
    if (!tab || !base || !n || *n == 0 || *n > 256) return {};
    int64_t start = (int64_t(*tab) + k) & 0xFFFFFFFF;
    if (!contains(start, *n)) return {};
    Switch s;
    for (int64_t i = 0; i < *n; ++i) {
        int v = img.data[size_t(start - img.base + i)];
        s.targets.push_back(uint32_t(int64_t(*base) + (v & 0x80 ? v - 256 : v)));
    }
    int64_t lo_ = start & ~int64_t(1);
    s.table = lo_;
    s.size = ((start + *n + 1) & ~int64_t(1)) - lo_;
    return s;
}

std::optional<Switch> Program::mova_switch(uint32_t jmp, std::optional<uint32_t> before) const {
    Insn j = insn(jmp);
    std::optional<std::pair<int64_t, Insn>> load, mova;
    bool rel = false;
    int64_t end = before ? *before : jmp;
    for (int64_t a = end - 2; a > end - 16; a -= 2) {
        if (!inside(a)) return {};
        Insn ins = insn(a);
        if (is_stop(ins) || ins.delay) return {};
        if (load_size(ins.fmt) && ins.m != 0 && !load) load = std::make_pair(a, ins);
        else if (ins.is("mova") && load) {
            mova = std::make_pair(a, ins);
            break;
        }
    }
    if (!load || !mova) return {};
    auto& [la, ld] = *load;
    int size = load_size(ld.fmt);
    std::vector<Insn> between;
    for (int64_t b = la + 2; b < end; b += 2) between.push_back(insn(b));
    if (before) between.push_back(insn(int64_t(*before) + 2));
    bool add_rel = false, clobbered = false;
    for (auto& i : between) {
        if (i.fmt == "add Rm,Rn" && i.n == 0 && i.m == ld.n) add_rel = true;
        if (writes_reg(i, ld.n)) clobbered = true;
    }
    if (j.n == 0 && add_rel) rel = true;
    else if (j.n != ld.n || size != 4 || clobbered) return {};
    int64_t table = *mova->second.target;
    auto n = switch_bound(mova->first, size);
    int64_t lim = (n && *n) ? *n : 1024;
    std::vector<uint32_t> entries;
    std::optional<int64_t> first_after;
    for (int64_t k = 0; k < lim; ++k) {
        int64_t ea = table + k * size;
        if (!contains(ea, size) || (first_after && ea >= *first_after)) break;
        int64_t v = size == 1 ? img.data[size_t(ea - img.base)] : size == 2 ? img.u16(uint32_t(ea)) : img.u32(uint32_t(ea));
        if (rel) {
            int bits = 8 * size;
            v = (table + ((v >> (bits - 1)) ? v - (int64_t(1) << bits) : v)) & 0xFFFFFFFF;
        }
        if (!inside(v)) {
            if (n && *n) return {};
            break;
        }
        entries.push_back(uint32_t(v));
        if (v > table && (!first_after || v < *first_after)) first_after = v;
    }
    if (entries.empty() || (n && *n && int64_t(entries.size()) != *n)) return {};
    int64_t span = int64_t(entries.size()) * size;
    return Switch{entries, table & ~int64_t(1), ((table + span + 1) & ~int64_t(1)) - (table & ~int64_t(1))};
}

Program::VP Program::jump_value(uint32_t jump, int window) const {
    int64_t start = jump;
    while (start > int64_t(jump) - 2 * window && contains(start - 2) && !is_flow(insn(start - 2))) start -= 2;
    std::array<VP, 16> regs{};
    std::map<int64_t, std::pair<int, VP>> gbr;
    auto mk = [](Val v) { return std::make_shared<const Val>(std::move(v)); };
    auto get = [&](int r) -> VP { return r >= 0 ? regs[r] : nullptr; };
    for (int64_t a = start; a < jump; a += 2) {
        Insn ins = insn(a);
        std::string_view f = ins.fmt;
        if (f == "mov.l @T,Rn" || f == "mov.w @T,Rn") {
            auto v = img.literal(ins);
            regs[ins.n] = v ? mk({'l', int64_t(*v)}) : nullptr;
        } else if (f == "mov #imm,Rn") {
            regs[ins.n] = mk({'l', int64_t(uint32_t(*ins.imm))});
        } else if (f == "and #imm,r0") {
            regs[0] = mk({'m', *ins.imm});
        } else if (f == "and Rm,Rn") {
            VP lit;
            for (VP x : {get(ins.n), get(ins.m)}) if (x && x->k == 'l') { lit = x; break; }
            regs[ins.n] = lit ? mk({'m', lit->v}) : nullptr;
        } else if (f == "mov.w @(r0,Rm),Rn") {
            VP index = regs[0];
            Val w{'w'};
            w.a = get(ins.m);
            if (index && index->k == 'm') w.m = index->v;
            regs[ins.n] = mk(std::move(w));
        } else if (f == "mov Rm,Rn") {
            regs[ins.n] = get(ins.m);
        } else if (f == "add Rm,Rn") {
            Val s{'a'};
            s.a = get(ins.n), s.b = get(ins.m);
            regs[ins.n] = mk(std::move(s));
        } else if (f.ends_with("r0,@(disp,gbr)")) {
            int size = ins.is("mov.b") ? 1 : ins.is("mov.w") ? 2 : 4;
            int64_t at = *ins.disp;
            for (auto it = gbr.begin(); it != gbr.end();) {
                if (it->first + it->second.first <= at || at + size <= it->first) ++it;
                else it = gbr.erase(it);
            }
            gbr[at] = {size, regs[0]};
        } else if (f.starts_with("mov.w @(disp,gbr)")) {
            auto it = gbr.find(*ins.disp);
            VP value = (it != gbr.end() && it->second.first == 2) ? it->second.second : nullptr;
            bool keeps = value && (value->k == 'w' || (value->k == 'm' && value->v < 0x8000));
            regs[0] = keeps ? value : nullptr;
        } else {
            if (f.ends_with(",gbr") || (has(f, "@(r0,gbr)") && !ins.is("tst.b"))) gbr.clear();
            uint32_t w = writes(ins);
            for (int r = 0; r < 16; ++r) if (w >> r & 1) regs[r] = nullptr;
        }
    }
    return get(insn(jump).n);
}

std::optional<Switch> Program::relative_word_switch(uint32_t jump) const {
    VP target = jump_value(jump);
    if (!target || target->k != 'a') return {};
    std::optional<int64_t> table;
    VP word;
    for (VP x : {target->a, target->b}) if (x && x->k == 'l') { table = x->v; break; }
    for (VP x : {target->a, target->b}) if (x && x->k == 'w' && x->a && x->a->k == 'l') { word = x; break; }
    if (!table || !word || !(0 <= *table - word->a->v && *table - word->a->v <= 2)) return {};
    int64_t span = 2048, k = 0;
    std::vector<uint32_t> targets;
    if (word->m) span = *word->m + 2 - (*table - word->a->v);
    while (k < span && contains(*table + k, 2)) {
        int64_t offset = img.u16(uint32_t(*table + k));
        int64_t t = *table + offset;
        if ((offset & 0x8001) || offset <= k || !inside(t) || insn(t).fmt.starts_with(".word")) break;
        targets.push_back(uint32_t(t));
        span = std::min(span, offset);
        k += 2;
    }
    if (targets.empty()) return {};
    if (k >= 2048 && std::find(targets.begin(), targets.end(), *table + k) == targets.end()) return {};
    for (uint32_t t : targets) if (*table <= t && t < *table + k) return {};
    return Switch{targets, *table, k};
}

std::optional<Switch> Program::branch_table_switch(uint32_t jump) const {
    VP target = jump_value(jump);
    if (!target || target->k != 'a') return {};
    std::vector<int64_t> lits;
    for (VP x : {target->a, target->b}) if (x && x->k == 'l') lits.push_back(x->v);
    if (lits.size() != 1) return {};
    int64_t table = lits[0];
    std::vector<uint32_t> targets;
    while (inside(table + 4 * int64_t(targets.size())) && contains(table + 4 * int64_t(targets.size()), 4)) {
        int64_t a = table + 4 * int64_t(targets.size());
        if (!insn(a).is("bra") || img.u16(uint32_t(a + 2)) != 0x0009) break;
        targets.push_back(uint32_t(a));
    }
    if (targets.size() < 2) return {};
    return Switch{targets, table, 0};
}

std::optional<uint32_t> Program::mova_base(uint32_t jmp) const {
    if (insn(jmp).n != 0) return {};
    bool added = false;
    for (int64_t a = int64_t(jmp) - 2; a > int64_t(jmp) - 14; a -= 2) {
        if (!inside(a)) return {};
        Insn ins = insn(a);
        if (is_stop(ins) || ins.delay) return {};
        if (ins.is("mova")) {
            if (added && inside(*ins.target)) return *ins.target;
            return {};
        }
        if (ins.fmt == "add Rm,Rn" && ins.n == 0) added = true;
        else if (writes_reg(ins, 0)) return {};
    }
    return {};
}

std::optional<Switch> Program::record_switch(uint32_t jmp) const {
    Insn j = insn(jmp);
    std::optional<int64_t> ld;
    for (int64_t a = int64_t(jmp) - 2; a > int64_t(jmp) - 24; a -= 2) {
        if (!inside(a)) return {};
        Insn ins = insn(a);
        if (is_stop(ins) || ins.delay) return {};
        if ((ins.fmt == "mov.l @Rm+,Rn" || ins.fmt == "mov.l @Rm,Rn") && ins.m == 0 && ins.n == j.n) {
            ld = a;
            break;
        }
        if (writes_reg(ins, j.n)) return {};
    }
    if (!ld) return {};
    Insn add = insn(*ld - 2), mova = insn(*ld - 4);
    if (!(add.fmt == "add Rm,Rn" && add.n == 0 && mova.is("mova"))) return {};
    int idx = add.m;
    int64_t scale = 1;
    std::optional<int64_t> mask;
    for (int64_t a = *ld - 6; a > *ld - 30; a -= 2) {
        Insn ins = insn(a);
        if (is_stop(ins)) return {};
        if (ins.n == idx && ins.is("shll")) scale *= 2;
        else if (ins.n == idx && ins.is("shll2")) scale *= 4;
        else if (ins.n == idx && ins.fmt == "add Rm,Rn" && ins.m == idx) scale *= 2;
        else if (ins.n == idx && ins.fmt == "mov Rm,Rn") idx = ins.m;
        else if (ins.is("and") && ins.imm && idx == 0) {
            mask = *ins.imm;
            break;
        } else if (writes_reg(ins, idx)) return {};
    }
    if (!mask || *mask > 1023) return {};
    int64_t table = *mova.target;
    std::vector<int64_t> offsets;
    for (int64_t v = 0; v <= *mask; ++v) if ((v & ~*mask) == 0) offsets.push_back(v * scale);
    Switch s;
    for (int64_t o : offsets) {
        if (!contains(table + o, 4)) return {};
        uint32_t t = img.u32(uint32_t(table + o));
        if (!inside(t)) return {};
        s.targets.push_back(t);
    }
    int64_t low = *mask & -*mask;
    int64_t stride = scale * (low ? low : 1);
    s.table = table & ~int64_t(1);
    s.size = ((table + offsets.back() + stride + 1) & ~int64_t(1)) - (table & ~int64_t(1));
    return s;
}

std::optional<int64_t> Program::switch_bound(int64_t at, int size) const {
    bool scaled = false;
    Back it(*this, at, 11);
    int64_t a;
    while (it.next(a)) {
        if (!inside(a)) return {};
        Insn ins = insn(a);
        if (is_stop(ins)) return {};
        if (op_in(ins, {"shll", "shll2"}) || (ins.fmt == "add Rm,Rn" && ins.m == ins.n)) scaled = true;
        if (op_in(ins, {"cmp/hi", "cmp/hs"}) && a + 2 < at && out_of_range(a + 2)) {
            auto k = reg_const(a, ins.m);
            if (!k) return {};
            return ins.is("cmp/hi") ? *k + 1 : *k;
        }
        if (ins.is("and")) {
            std::optional<int64_t> m = ins.imm ? std::optional<int64_t>(*ins.imm) : reg_const(a, ins.m);
            if (!m || *m >= 4096) return {};
            return scaled ? *m + 1 : floordiv(*m, size) + 1;
        }
    }
    return {};
}

std::optional<int64_t> Program::skipped_bra(int64_t a) const {
    for (int64_t c : {a - 4, a - 2}) {
        if (inside(c)) {
            Insn ins = insn(c);
            if (op_in(ins, {"bt", "bf", "bt/s", "bf/s"}) && ins.target && int64_t(*ins.target) == a + 4 &&
                ins.delay == (c == a - 4))
                return c;
        }
    }
    return {};
}

bool Program::out_of_range(int64_t b) const {
    Insn ins = insn(b);
    if (op_in(ins, {"bt", "bt/s"})) return true;
    if (op_in(ins, {"bf", "bf/s"})) {
        int64_t bra = int64_t(*ins.target) - 4;
        return inside(bra) && insn(bra).is("bra") && skipped_bra(bra) == b;
    }
    return false;
}

std::optional<int64_t> Program::reg_const(int64_t at, int reg) const {
    Back it(*this, at, 5);
    int64_t a;
    while (it.next(a)) {
        if (!inside(a)) return {};
        Insn ins = insn(a);
        if (is_stop(ins)) return {};
        if (writes_reg(ins, reg)) {
            if (ins.is("mov") && ins.imm) return int64_t(uint32_t(*ins.imm));
            if ((ins.is("mov.w") || ins.is("mov.l")) && ins.target && ins.size) {
                auto v = img.literal(ins);
                if (v) return int64_t(*v);
                return {};
            }
            return {};
        }
    }
    return {};
}

std::optional<Switch> Program::braf_switch(uint32_t braf) const {
    Insn ld = insn(int64_t(braf) - 2), mova = insn(int64_t(braf) - 4);
    if (!mova.is("mova") || !(ld.is("mov.w") || ld.is("mov.l")) || !has(ld.fmt, "@(r0,")) return {};
    int size = ld.is("mov.w") ? 2 : 4;
    int64_t table = *mova.target;
    std::optional<int64_t> n;
    int64_t a = int64_t(braf) - 6;
    for (int i = 0; i < 8; ++i) {
        Insn ins = insn(a);
        if (ins.is("cmp/hs") && ins.n == 0) {
            for (int64_t b = a - 2; b > a - 12; b -= 2) {
                Insn j = insn(b);
                if (j.is("mov") && j.imm && j.n == ins.m) {
                    n = *j.imm;
                    break;
                }
            }
            break;
        }
        a -= 2;
    }
    if (!n || *n <= 0 || *n > 1024) return {};
    int64_t base = int64_t(braf) + 4;
    Switch s{{}, table, *n * size};
    for (int64_t k = 0; k < *n; ++k) {
        int64_t ea = table + k * size;
        if (!contains(ea, size)) return {};
        int64_t v = size == 2 ? img.u16(uint32_t(ea)) : img.u32(uint32_t(ea));
        if (size == 2 && (v & 0x8000)) v -= 0x10000;
        if (size == 4 && (v & 0x80000000)) v -= int64_t(1) << 32;
        s.targets.push_back(uint32_t(base + v));
    }
    return s;
}

std::unordered_map<uint32_t, RegState> Program::constants(const USet& code_, uint32_t entry, const USet& wanted,
                                                          const Switches* local) const {
    std::unordered_map<uint32_t, RegState> state, out;
    RegState none;
    none.fill(-1);
    state[entry] = none;
    std::vector<uint32_t> work{entry};
    std::vector<uint32_t> succ;
    while (!work.empty()) {
        uint32_t a = work.back();
        work.pop_back();
        RegState st = state[a];
        Insn ins = img.insn(a);
        if (wanted.count(a)) out[a] = st;
        transfer(img, ins, st);
        succ.clear();
        if (ins.delay) {
            Insn slot = img.insn(a + 2);
            if (op_in(ins, {"jsr", "bsr", "bsrf"})) {
                RegState st2 = state[a];
                transfer(img, slot, st2);
                transfer(img, ins, st2);
                st = st2;
                succ = {a + 4};
            } else {
                transfer(img, slot, st);
                if (op_in(ins, {"bt/s", "bf/s"})) succ = {*ins.target, a + 4};
                else if (ins.is("bra")) succ = {*ins.target};
            }
        } else if (op_in(ins, {"bt", "bf"})) {
            succ = {*ins.target, a + 2};
        } else if (!op_in(ins, {"rts", "rte", "jmp", "braf"})) {
            succ = {a + 2};
        }
        if (op_in(ins, {"braf", "jmp"})) {
            succ.clear();
            const std::vector<uint32_t>* found = nullptr;
            if (local) {
                auto it = local->find(a);
                if (it != local->end() && !it->second.empty()) found = &it->second;
            }
            if (!found) {
                auto it = switches.find(a);
                if (it != switches.end()) found = &it->second;
            }
            if (found) succ = *found;
            if (succ.empty() && ins.is("jmp")) {
                int64_t v = state[a][ins.n];
                if (v >= 0 && code_.count(uint32_t(v))) succ = {uint32_t(v)};
            }
        }
        for (uint32_t t : succ) {
            if (!code_.count(t)) continue;
            auto old = state.find(t);
            if (old == state.end()) {
                state[t] = st;
                work.push_back(t);
            } else {
                RegState merged;
                for (int r = 0; r < 16; ++r) merged[r] = old->second[r] == st[r] ? st[r] : -1;
                if (merged != old->second) {
                    old->second = merged;
                    work.push_back(t);
                }
            }
        }
    }
    return out;
}

std::pair<std::unique_ptr<Function>, USet> Program::descend(uint32_t entry, bool commit) {
    auto f = std::make_unique<Function>();
    f->entry = entry;
    USet ldata;
    Switches sw;
    std::vector<uint32_t> work{entry};
    std::vector<std::pair<uint32_t, bool>> pending;
    while (true) {
        while (!work.empty()) {
            uint32_t a = work.back();
            work.pop_back();
            walk(*f, a, ldata, sw, work, pending);
        }
        if (pending.empty()) break;
        USet wanted;
        for (auto& [at, _] : pending) wanted.insert(at);
        auto consts = constants(f->code, entry, wanted, &sw);
        for (auto& [at, is_jsr] : pending) {
            auto it = consts.find(at);
            int n = img.insn(at).n;
            int64_t v = (it == consts.end() || n < 0) ? -1 : it->second[n];
            if (v < 0) f->unresolved.push_back({at, is_jsr ? "jsr" : "jmp"});
            else if (is_jsr) f->calls.add(uint32_t(v));
            else if ((has_func(uint32_t(v)) && v != entry) || !inside(v)) f->tails.add(uint32_t(v));
            else work.push_back(uint32_t(v));
        }
        pending.clear();
        if (work.empty()) break;
    }
    if (!f->bad)
        for (uint32_t a : f->code) if (ldata.count(a)) { f->bad = true; break; }
    if (commit) {
        auto copy = std::make_unique<Function>(*f);
        auto it = func_index.find(entry);
        if (it == func_index.end()) {
            func_index[entry] = funcs.size();
            funcs.push_back(std::move(copy));
        } else {
            funcs[it->second] = std::move(copy);
        }
        for (uint32_t a : sorted_of(f->code)) if (code.add(a)) code_order_.push_back(a);
        for (uint32_t a : ldata) data.add(a);
        for (auto& [k, v] : sw) switches[k] = v;
        for (uint32_t a : f->tables) tables.add(a);
    }
    return {std::move(f), std::move(ldata)};
}

void Program::walk(Function& f, uint32_t a, USet& ldata, Switches& sw, std::vector<uint32_t>& work,
                   std::vector<std::pair<uint32_t, bool>>& pending) const {
    auto code_literal = [&](const Insn& ins) {
        if (ins.target && (ins.is("mov.w") || ins.is("mov.l")) && ins.size)
            for (int k = 0; k < ins.size; k += 2) ldata.insert(*ins.target + k);
    };
    auto mark = [&](const Switch& s) {
        for (int64_t k = 0; k < s.size; k += 2) {
            ldata.insert(uint32_t(s.table + k));
            f.tables.insert(uint32_t(s.table + k));
        }
    };
    while (true) {
        if (f.code.count(a) && !f.slot_only.count(a)) return;
        if (!inside(a)) { f.bad = true; return; }
        if (data.has(a) || ldata.count(a)) { f.bad = true; return; }
        Insn ins = img.insn(a);
        if (ins.is(".word")) { f.bad = true; return; }
        f.slot_only.erase(a);
        f.code.insert(a);
        code_literal(ins);
        if (ins.is("lds") && ins.fmt == "lds Rm,pr" && ins.m == 0 && f.code.count(a - 2)) {
            Insn previous = img.insn(a - 2);
            if (previous.is("mova") && inside(*previous.target)) work.push_back(*previous.target);
        }
        if (ins.delay) {
            uint32_t slot = a + 2;
            if (inside(slot) && !data.has(slot)) {
                Insn s = img.insn(slot);
                if (s.is(".word") || s.is("trapa") || is_flow(s)) {
                    f.bad = true;
                } else {
                    if (!f.code.count(slot)) f.slot_only.insert(slot);
                    f.code.insert(slot);
                    code_literal(s);
                }
            }
        }
        if (op_in(ins, {"bt", "bf"})) {
            work.push_back(*ins.target);
            a += 2;
        } else if (op_in(ins, {"bt/s", "bf/s"})) {
            work.push_back(*ins.target);
            a += 4;
        } else if (ins.is("bsr")) {
            f.calls.add(*ins.target);
            a += 4;
        } else if (ins.is("bsrf")) {
            f.unresolved.push_back({a, "bsrf"});
            a += 4;
        } else if (ins.is("jsr")) {
            Lit r = literal_for(a, ins.n);
            if (r.kind == 1) {
                f.calls.add(r.v);
            } else if (r.kind == 2) {
            } else {
                auto s = relative_word_switch(a);
                if (!s) s = branch_table_switch(a);
                if (s) {
                    sw[a] = s->targets;
                    for (uint32_t t : s->targets) f.calls.add(t);
                    mark(*s);
                } else {
                    pending.push_back({a, true});
                }
            }
            a += 4;
        } else if (ins.is("bra")) {
            uint32_t t = *ins.target;
            if (has_func(t) && t != f.entry) {
                f.tails.add(t);
            } else {
                work.push_back(t);
                if (inside(t) && !sw.count(t) && img.insn(t).is("jmp")) {
                    auto s = mova_switch(t, a);
                    if (s) {
                        sw[t] = s->targets;
                        mark(*s);
                        work.insert(work.end(), s->targets.begin(), s->targets.end());
                    }
                }
            }
            return;
        } else if (ins.is("jmp")) {
            Lit r = literal_for(a, ins.n);
            if (sw.count(a)) {
            } else if (r.kind == 1) {
                uint32_t t = r.v;
                if ((has_func(t) && t != f.entry) || !inside(t)) f.tails.add(t);
                else work.push_back(t);
            } else if (r.kind == 2) {
            } else {
                std::optional<Switch> s = abs_switch(a);
                if (!s) s = byte_switch(a);
                if (!s) s = byte_switch_offset(a);
                if (!s) s = mova_switch(a);
                if (!s) s = relative_word_switch(a);
                if (!s) s = branch_table_switch(a);
                if (!s) s = record_switch(a);
                if (s) {
                    sw[a] = s->targets;
                    mark(*s);
                    work.insert(work.end(), s->targets.begin(), s->targets.end());
                } else {
                    pending.push_back({a, false});
                    auto t = mova_base(a);
                    if (t) {
                        work.push_back(*t);
                        if (*t > a) work.push_back(a + 4);
                    }
                }
            }
            return;
        } else if (ins.is("braf")) {
            auto s = braf_switch(a);
            if (s) {
                sw[a] = s->targets;
                mark(*s);
                work.insert(work.end(), s->targets.begin(), s->targets.end());
            } else {
                f.unresolved.push_back({a, "braf"});
            }
            return;
        } else if (op_in(ins, {"rts", "rte"})) {
            return;
        } else {
            a += 2;
        }
    }
}

void Program::push_pending(const Function& f) {
    // `for t in f.calls | f.tails`, in CPython's set order
    PySet::merged(f.calls, f.tails).each([&](uint32_t t) {
        if (!has_func(t) && inside(t)) pending_.push_back(t);
    });
}

void Program::run() {
    while (true) {
        while (!pending_.empty()) {
            uint32_t e = pending_.back();
            pending_.pop_back();
            if (has_func(e) || !inside(e)) continue;
            auto [f, _] = descend(e, true);
            auto all = PySet::merged(f->calls, f->tails).values();
            std::sort(all.begin(), all.end());
            for (uint32_t t : all)
                if (!has_func(t) && inside(t)) pending_.push_back(t);
        }
        int added = pointer_seeds();
        if (!added) added = prologue_seeds();
        if (!added) added = address_taken();
        if (!added) break;
    }
}

bool Program::boundary(int64_t a) const {
    while (a - 2 >= lo && contains(a - 2) && !code.has(a - 2) && !data.has(a - 2) &&
           (img.u16(uint32_t(a - 2)) == 0 || img.u16(uint32_t(a - 2)) == 9))
        a -= 2;
    int64_t p = a - 2;
    if (data.has(p)) return true;
    int64_t q = a - 4;
    if (code.has(q)) {
        Insn i = insn(q);
        return op_in(i, {"rts", "rte", "bra", "jmp"});
    }
    return p < lo || !contains(p);
}

const USet& Program::data_addresses() {
    static const char* base_m[] = {"@Rm,", "@Rm+", "@(disp,Rm)", "@(r0,Rm)"};
    static const char* base_n[] = {"@Rn", "@-Rn", "@(disp,Rn)", "@(r0,Rn)"};
    for (size_t i = scanned_; i < code_order_.size(); ++i) {
        uint32_t a = code_order_[i];
        Insn ins = img.insn(a);
        if (!ins.is("mov.l") || ins.size != 4 || !ins.target) continue;
        auto v = img.literal(ins);
        if (!v) continue;
        int r = ins.n;
        uint32_t b = a + 2;
        for (int k = 0; k < 8; ++k) {
            if (!code.has(b)) break;
            Insn j = img.insn(b);
            if (is_flow(j)) break;
            bool hit = false;
            if (j.m == r) for (auto s : base_m) if (has(j.fmt, s)) hit = true;
            if (!hit && j.n == r) for (auto s : base_n) if (has(j.fmt, s)) hit = true;
            if (hit) {
                data_addrs_.insert(*v);
                break;
            }
            if (writes_reg(j, r)) break;
            b += 2;
        }
    }
    scanned_ = code_order_.size();
    return data_addrs_;
}

const USet& Program::indexed_tables() {
    if (!indexed_) {
        indexed_.emplace();
        for (int64_t a = img.base; a < int64_t(img.end()) - 1; a += 2) {
            uint32_t w = img.u16(uint32_t(a));
            if (w >> 12 != 0xD) continue;
            auto v = img.literal(insn(a));
            if (!v || !(lo <= *v && *v < hi)) continue;
            int r = (w >> 8) & 15;
            int64_t stop = std::min<int64_t>(a + 18, int64_t(img.end()) - 1);
            for (int64_t b = a + 2; b < stop; b += 2) {
                Insn j = insn(b);
                if (is_flow(j)) break;
                if (j.m == r && has(j.fmt, "@(r0,Rm)")) {
                    indexed_->insert(*v);
                    break;
                }
                if (writes_reg(j, r)) break;
            }
        }
    }
    return *indexed_;
}

int Program::pointer_seeds() {
    USet data_addrs = data_addresses();
    for (uint32_t v : indexed_tables()) data_addrs.insert(v);
    USet cands, tabled;
    std::vector<int64_t> words;
    for (uint32_t a : data.sorted()) if (!(a & 3) && data.has(int64_t(a) + 2)) words.push_back(a);
    for (auto [start, n] : gaps())
        for (int64_t w = (int64_t(start) + 3) & ~int64_t(3); w < int64_t(start) + n - 3; w += 4) words.push_back(w);
    auto into = [&](int64_t w) { return contains(w, 4) && lo <= img.u32(uint32_t(w)) && img.u32(uint32_t(w)) < hi; };
    std::sort(words.begin(), words.end());
    for (int64_t a : words) {
        if (!contains(a, 4)) continue;
        uint32_t v = img.u32(uint32_t(a));
        if (inside(v) && !code.has(v) && !data.has(v) && !rejected_.count(v) && !data_addrs.count(v)) {
            cands.insert(v);
            if (into(a - 4) || into(a + 4)) tabled.insert(v);
        }
    }
    const USet& literals = literal_values();
    for (uint32_t v : literals)
        if (inside(v) && !code.has(v) && !data.has(v) && !rejected_.count(v) && !data_addrs.count(v)) cands.insert(v);
    int added = 0;
    for (uint32_t v : sorted_of(cands)) {
        if (!boundary(v) && !(!(v & 1) && is_prologue(img.u16(v))) && !literals.count(v) && !tabled.count(v)) continue;
        if (is_text(v) || is_pointers(v)) {
            rejected_.insert(v);
            continue;
        }
        auto [f, d] = descend(v, false);
        bool clash = f->bad;
        if (!clash) for (uint32_t a : f->code) if (data.has(a)) { clash = true; break; }
        if (!clash) for (uint32_t a : d) if (code.has(a)) { clash = true; break; }
        if (clash || through_pointers(f->code)) {
            rejected_.insert(v);
            continue;
        }
        bool weak = !boundary(v) && !is_prologue(img.u16(v));
        bool empty = literals.count(v) && contains(v, 4) && img.u32(v) == 0x000B0009;
        if (weak && f->code.size() < 8 && !empty) continue;
        descend(v, true);
        push_pending(*f);
        ++added;
    }
    return added;
}

bool Program::through_pointers(const USet& c) const {
    for (uint32_t a : c) if (!(a & 3) && c.count(a + 6) && is_pointers(a)) return true;
    return false;
}

const USet& Program::literal_values() {
    for (size_t i = lit_scanned_; i < code_order_.size(); ++i) {
        uint32_t a = code_order_[i];
        Insn ins = img.insn(a);
        if (ins.is("mov.l") && ins.size == 4 && ins.target) {
            auto v = img.literal(ins);
            if (v) lits_.insert(*v);
        } else if (ins.is("mova")) {
            for (uint32_t b = a + 2; b < a + 10; b += 2) {
                Insn j = img.insn(b);
                if (j.is("mov.l") && ((j.m == 0 && j.fmt.starts_with("mov.l Rm,@")) || j.fmt == "mov.l r0,@(disp,gbr)")) {
                    lits_.insert(*ins.target);
                    break;
                }
                if (writes_reg(j, 0) || is_stop(j)) break;
            }
        }
    }
    lit_scanned_ = code_order_.size();
    return lits_;
}

bool Program::is_text(int64_t a) const {
    for (int64_t k = 0; k < 64; ++k) {
        if (!contains(a + k, 1)) return false;
        int c = img.data[size_t(a + k - img.base)];
        if (c == 0) {
            if (k >= 3) return true;
            int64_t end = (a + k + 4) & ~int64_t(3);
            if (!(k > 0 && contains(a + k, end - a - k))) return false;
            for (int64_t i = a + k; i < end; ++i) if (img.data[size_t(i - img.base)]) return false;
            return true;
        }
        if (!((0x20 <= c && c < 0x7F) || c == 9 || c == 10 || c == 13)) return false;
    }
    return false;
}

bool Program::is_pointers(int64_t a) const {
    if ((a & 3) || !contains(a, 8)) return false;
    for (int k : {0, 4}) {
        uint32_t v = img.u32(uint32_t(a + k));
        if (!(lo <= v && v < hi)) return false;
    }
    return true;
}

int Program::address_taken() {
    int added = 0;
    std::vector<uint32_t> snap;
    for (uint32_t a : data.sorted()) if (!tables.has(a)) snap.push_back(a);
    for (uint32_t a : snap) {
        if ((a & 3) || !data.has(int64_t(a) + 2) || !contains(a, 4)) continue;
        uint32_t v = img.u32(a);
        if (code.has(v) && !has_func(v) && !rejected_.count(v)) {
            auto [f, d] = descend(v, false);
            if (f->bad) {
                rejected_.insert(v);
                continue;
            }
            descend(v, true);
            ++added;
        }
    }
    return added;
}

int Program::prologue_seeds() {
    int added = 0;
    for (auto [start, n] : gaps()) {
        int64_t end = int64_t(start) + n;
        int64_t a = start;
        while (a < end && (img.u16(uint32_t(a)) == 9 || img.u16(uint32_t(a)) == 0)) a += 2;
        std::vector<int64_t> cands;
        if (a < end && boundary(a)) cands.push_back(a);
        for (int64_t p = int64_t(start) + 4; p < end; p += 2) {
            if (op_in(insn(p - 4), {"rts", "rte", "bra", "jmp"})) {
                int64_t q = p;
                while (q < end && (img.u16(uint32_t(q)) == 9 || img.u16(uint32_t(q)) == 0)) q += 2;
                cands.push_back(q);
            }
        }
        for (int64_t c : cands) {
            if (c >= end || code.has(c) || has_func(uint32_t(c))) continue;
            bool pro = false;
            for (int k : {0, 2, 4}) if (c + k < end && is_prologue(img.u16(uint32_t(c + k)))) { pro = true; break; }
            if (!pro) continue;
            added += take(uint32_t(c));
        }
    }
    if (added) return added;
    for (auto [start, n] : gaps()) {
        for (int64_t c = start; c < int64_t(start) + n - 3; c += 2) {
            if (img.u16(uint32_t(c)) != 0x2FE6 || img.u16(uint32_t(c + 2)) != 0x4F22) continue;
            int64_t e = c;
            while (e - 2 >= start) {
                uint32_t w = img.u16(uint32_t(e - 2));
                if (!((w & 0xFF0F) == 0x2F06 && 8 <= ((w >> 4) & 15) && ((w >> 4) & 15) <= 13)) break;
                e -= 2;
            }
            bool after = e == start || !(img.u16(uint32_t(e - 2)) & 0xFF) || after_pointer(e);
            if (!after || code.has(e) || has_func(uint32_t(e))) continue;
            added += take(uint32_t(e), 8);
        }
    }
    return added;
}

bool Program::after_pointer(int64_t a) const {
    return !(a & 3) && contains(a - 4, 4) && inside(img.u32(uint32_t(a - 4)));
}

int Program::take(uint32_t c, size_t at_least) {
    if (rejected_.count(c)) return 0;
    auto [f, d] = descend(c, false);
    bool clash = f->bad;
    if (!clash) for (uint32_t a : f->code) if (data.has(a)) { clash = true; break; }
    if (!clash) for (uint32_t a : d) if (code.has(a)) { clash = true; break; }
    if (clash || f->code.size() < at_least) {
        rejected_.insert(c);
        return 0;
    }
    descend(c, true);
    push_pending(*f);
    return 1;
}

std::vector<std::pair<uint32_t, uint32_t>> Program::gaps() const {
    std::vector<std::pair<uint32_t, uint32_t>> out;
    std::optional<uint32_t> start;
    for (uint32_t a = lo; a < hi; a += 2) {
        bool known = code.has(a) || data.has(a);
        if (!known && !start) start = a;
        else if (known && start) {
            out.push_back({*start, a - *start});
            start.reset();
        }
    }
    if (start) out.push_back({*start, hi - *start});
    return out;
}

std::map<uint32_t, Target> Program::resolve(const Function& f, const USet& vol) const {
    std::map<uint32_t, Target> out;
    std::vector<uint32_t> need;
    for (uint32_t a : f.code) {
        Insn ins = img.insn(a);
        if (!op_in(ins, {"jmp", "braf", "jsr", "bsrf"})) continue;
        auto sw = switches.find(a);
        if (sw != switches.end()) {
            Target t{{}, "switch"};
            USet seen;
            for (uint32_t v : sw->second) if (seen.insert(v).second) t.cands.push_back(v);
            out[a] = t;
            continue;
        }
        if (ins.is("jmp") || ins.is("jsr")) {
            Lit lit = literal_for(a, ins.n);
            if (lit.kind == 1 && !vol.count(lit.slot)) { out[a] = {{lit.v}, "literal"}; continue; }
            if (lit.kind == 1) { out[a] = {{}, "unresolved"}; continue; }
            if (lit.kind == 2) { out[a] = {{}, "pointer"}; continue; }
        }
        need.push_back(a);
    }
    if (!need.empty()) {
        USet wanted(need.begin(), need.end());
        auto consts = constants(f.code, f.entry, wanted, nullptr);
        for (uint32_t a : need) {
            Insn ins = img.insn(a);
            auto it = consts.find(a);
            int64_t v = (it == consts.end() || ins.n < 0) ? -1 : it->second[ins.n];
            if (v < 0) out[a] = {{}, "unresolved"};
            else if (ins.is("braf") || ins.is("bsrf")) out[a] = {{uint32_t(a + 4 + v)}, "constant"};
            else out[a] = {{uint32_t(v)}, "constant"};
        }
    }
    return out;
}

}  // namespace sf3::gen
