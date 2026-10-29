// SF3 recomp: running a generated module set in a generic build (MIT). See x64_set.cpp.
#pragma once
#include <string>

// Loads DIR/modules.sf3m and every DIR/<name>.sf3c it names, and installs them as the runtime's
// modules (sat_set_module_set). Call before saturn_main. False with why when the set is missing,
// stale (another ABI) or damaged: the caller regenerates it. Nothing is installed then.
bool sf3_x64_install_set(const std::string& dir, std::string& why);
