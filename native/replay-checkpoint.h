#pragma once
#include <cstdint>
#include <filesystem>
#include <string>

namespace sf3_replay {
// Throws std::runtime_error on incomplete, incompatible or corrupted checkpoints.
std::filesystem::path save(const std::filesystem::path& root, const std::filesystem::path& seed,
                           const std::filesystem::path& recording, uint64_t frame);
uint64_t verify(const std::filesystem::path& checkpoint, const std::filesystem::path& seed);
std::filesystem::path latest(const std::filesystem::path& root);
void request_load(const std::filesystem::path& root, const std::filesystem::path& seed,
                  const std::filesystem::path& request);
}
