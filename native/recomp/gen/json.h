// SF3 recomp, on-console generator: a small JSON reader for revision profiles and inventories, and
// Python's json.dumps(sort_keys=True, separators=(',', ':')) for content IDs (MIT).
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace sf3::gen::json {

struct Value {
    enum Kind { Null, Bool, Number, String, Array, Object } kind = Null;
    bool b = false;
    std::string s;                                      // String: decoded UTF-8; Number: its text
    std::vector<Value> items;                           // Array
    std::vector<std::pair<std::string, Value>> fields;  // Object, in file order

    const Value* find(const std::string& k) const {
        for (auto& [n, v] : fields) if (n == k) return &v;
        return nullptr;
    }
    const Value& at(const std::string& k) const {
        auto* v = find(k);
        if (!v) throw std::runtime_error("missing JSON field: " + k);
        return *v;
    }
    bool has(const std::string& k) const { return find(k) != nullptr; }
    const std::string& str() const {
        if (kind != String) throw std::runtime_error("JSON value is not a string");
        return s;
    }
    int64_t integer() const {
        if (kind != Number || s.find_first_of(".eE") != std::string::npos) throw std::runtime_error("JSON value is not an integer");
        return std::stoll(s);
    }
    bool truthy() const {
        switch (kind) {
        case Null: return false;
        case Bool: return b;
        case Number: return std::stod(s) != 0;
        case String: return !s.empty();
        case Array: return !items.empty();
        case Object: return !fields.empty();
        }
        return false;
    }
};

class Parser {
public:
    explicit Parser(const std::string& t) : t_(t) {
        if (t_.compare(0, 3, "\xEF\xBB\xBF") == 0) p_ = 3;   // utf-8-sig
    }
    Value parse() {
        Value v = value();
        ws();
        if (p_ != t_.size()) fail("trailing data");
        return v;
    }
private:
    const std::string& t_;
    size_t p_ = 0;
    [[noreturn]] void fail(const char* m) { throw std::runtime_error(std::string("JSON: ") + m + " at " + std::to_string(p_)); }
    void ws() { while (p_ < t_.size() && (t_[p_] == ' ' || t_[p_] == '\n' || t_[p_] == '\r' || t_[p_] == '\t')) ++p_; }
    bool lit(const char* w) {
        size_t n = strlen(w);
        if (t_.compare(p_, n, w) == 0) { p_ += n; return true; }
        return false;
    }
    static void utf8(std::string& o, uint32_t c) {
        if (c < 0x80) o += char(c);
        else if (c < 0x800) o += char(0xC0 | c >> 6), o += char(0x80 | (c & 63));
        else if (c < 0x10000) o += char(0xE0 | c >> 12), o += char(0x80 | (c >> 6 & 63)), o += char(0x80 | (c & 63));
        else o += char(0xF0 | c >> 18), o += char(0x80 | (c >> 12 & 63)), o += char(0x80 | (c >> 6 & 63)), o += char(0x80 | (c & 63));
    }
    uint32_t hex4() {
        if (p_ + 4 > t_.size()) fail("bad escape");
        uint32_t v = uint32_t(std::stoul(t_.substr(p_, 4), nullptr, 16));
        p_ += 4;
        return v;
    }
    std::string string() {
        if (t_[p_] != '"') fail("expected string");
        ++p_;
        std::string o;
        while (true) {
            if (p_ >= t_.size()) fail("unterminated string");
            char c = t_[p_++];
            if (c == '"') return o;
            if (c != '\\') { o += c; continue; }
            char e = t_[p_++];
            switch (e) {
            case '"': o += '"'; break;
            case '\\': o += '\\'; break;
            case '/': o += '/'; break;
            case 'b': o += '\b'; break;
            case 'f': o += '\f'; break;
            case 'n': o += '\n'; break;
            case 'r': o += '\r'; break;
            case 't': o += '\t'; break;
            case 'u': {
                uint32_t c1 = hex4();
                if (c1 >= 0xD800 && c1 < 0xDC00 && t_.compare(p_, 2, "\\u") == 0) {
                    p_ += 2;
                    uint32_t c2 = hex4();
                    c1 = 0x10000 + ((c1 - 0xD800) << 10) + (c2 - 0xDC00);
                }
                utf8(o, c1);
                break;
            }
            default: fail("bad escape");
            }
        }
    }
    Value value() {
        ws();
        if (p_ >= t_.size()) fail("unexpected end");
        Value v;
        char c = t_[p_];
        if (c == '{') {
            v.kind = Value::Object;
            ++p_;
            ws();
            if (t_[p_] == '}') { ++p_; return v; }
            while (true) {
                ws();
                std::string k = string();
                ws();
                if (t_[p_++] != ':') fail("expected ':'");
                v.fields.emplace_back(std::move(k), value());
                ws();
                if (t_[p_] == ',') { ++p_; continue; }
                if (t_[p_] == '}') { ++p_; return v; }
                fail("expected ',' or '}'");
            }
        }
        if (c == '[') {
            v.kind = Value::Array;
            ++p_;
            ws();
            if (t_[p_] == ']') { ++p_; return v; }
            while (true) {
                v.items.push_back(value());
                ws();
                if (t_[p_] == ',') { ++p_; continue; }
                if (t_[p_] == ']') { ++p_; return v; }
                fail("expected ',' or ']'");
            }
        }
        if (c == '"') { v.kind = Value::String; v.s = string(); return v; }
        if (lit("true")) { v.kind = Value::Bool; v.b = true; return v; }
        if (lit("false")) { v.kind = Value::Bool; return v; }
        if (lit("null")) return v;
        size_t s = p_;
        while (p_ < t_.size() && strchr("+-0123456789.eE", t_[p_])) ++p_;
        if (s == p_) fail("unexpected character");
        v.kind = Value::Number;
        v.s = t_.substr(s, p_ - s);
        return v;
    }
};

inline Value parse(const std::string& text) { return Parser(text).parse(); }

// json.dumps(v, sort_keys=True, separators=(',', ':')) with ensure_ascii (integers as written).
inline void dump_sorted(const Value& v, std::string& o) {
    auto str = [&](const std::string& s) {
        o += '"';
        for (size_t i = 0; i < s.size();) {
            uint8_t c = uint8_t(s[i]);
            uint32_t cp = c;
            size_t n = 1;
            if (c >= 0xF0) cp = c & 7, n = 4;
            else if (c >= 0xE0) cp = c & 15, n = 3;
            else if (c >= 0xC0) cp = c & 31, n = 2;
            for (size_t k = 1; k < n && i + k < s.size(); ++k) cp = cp << 6 | (uint8_t(s[i + k]) & 63);
            i += n;
            char b[16];
            if (cp == '"') o += "\\\"";
            else if (cp == '\\') o += "\\\\";
            else if (cp == '\n') o += "\\n";
            else if (cp == '\r') o += "\\r";
            else if (cp == '\t') o += "\\t";
            else if (cp == '\b') o += "\\b";
            else if (cp == '\f') o += "\\f";
            else if (cp < 0x20) { snprintf(b, sizeof b, "\\u%04x", cp); o += b; }
            else if (cp < 0x80) o += char(cp);
            else if (cp < 0x10000) { snprintf(b, sizeof b, "\\u%04x", cp); o += b; }
            else {
                uint32_t x = cp - 0x10000;
                snprintf(b, sizeof b, "\\u%04x\\u%04x", 0xD800 + (x >> 10), 0xDC00 + (x & 0x3FF));
                o += b;
            }
        }
        o += '"';
    };
    switch (v.kind) {
    case Value::Null: o += "null"; break;
    case Value::Bool: o += v.b ? "true" : "false"; break;
    case Value::Number: o += v.s; break;
    case Value::String: str(v.s); break;
    case Value::Array:
        o += '[';
        for (size_t i = 0; i < v.items.size(); ++i) { if (i) o += ','; dump_sorted(v.items[i], o); }
        o += ']';
        break;
    case Value::Object: {
        std::map<std::string, const Value*> s;
        for (auto& [k, x] : v.fields) s[k] = &x;     // a repeated key keeps the last, as Python's dict
        o += '{';
        bool first = true;
        for (auto& [k, x] : s) {
            if (!first) o += ',';
            first = false;
            str(k);
            o += ':';
            dump_sorted(*x, o);
        }
        o += '}';
        break;
    }
    }
}

}  // namespace sf3::gen::json
