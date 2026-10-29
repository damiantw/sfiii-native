// SF3 recomp: binding a module's generated x86-64 code cache at startup (MIT). See x64_rt.cpp.
#pragma once
#include <cstdint>
#include "saturn/sh2.h"

// Loads $SF3_X64_DIR/<name>.sf3c, checks its entries are addrs[0..n), and fills fn[] with them.
// Exits the process with a message on any mismatch (a stale or foreign cache).
bool sf3_x64_bind(const char* name, const uint32_t* addrs, SH2Func* fn, uint32_t n, uint8_t* ran);
