// SF3 recomp, on-console generator: the backend interface (MIT).
//
// A backend turns one discovered function into host code in a Cache. The first backend,
// X64ThunkBackend, emits a 17-byte thunk per function (16-byte aligned) that enters the interpreter
// (sh2_interp_call(c, entry)). With it the whole load/mprotect/dispatch path runs before any
// real code generation exists, so it is a correct baseline to diff the real backend against.
// The real x86-64 backend (PLAN P1) does the same work as emit.py: registers in SH2Context,
// ld/st through relocated service calls, SH2_POLL at the same safe points, folded literals.
#pragma once
#include "code_cache.h"
#include "discover.h"

namespace sf3::gen {

class Backend {
public:
    virtual ~Backend() = default;
    virtual uint32_t id() const = 0;                       // CacheHeader::backend
    virtual void emit(const Image&, const Function&, Cache&) = 0;   // appends code + entry + relocs
};

class X64ThunkBackend final : public Backend {
public:
    uint32_t id() const override { return 1; }
    void emit(const Image&, const Function&, Cache&) override;
};

// Discover from seeds, then emit every function with the backend.
Cache build_cache(const Image&, const std::vector<uint32_t>& seeds, Backend&);

}  // namespace sf3::gen
