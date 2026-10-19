#include "replay-checkpoint.h"
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <chrono>
#include <sstream>
#include <array>
#include <vector>

namespace sf3_replay {
namespace fs = std::filesystem;
namespace {
const std::array<const char*, 6> files = {
    "point.txt", "input.txt", "seed/context.json", "seed/build-id.txt", "seed/disc-id.txt", "seed/backup.bin"};
std::string read(const fs::path& p) {
    std::ifstream f(p, std::ios::binary);
    if (!f) throw std::runtime_error("Missing checkpoint file: " + p.string());
    return std::string(std::istreambuf_iterator<char>(f), {});
}
void write(const fs::path& p, const std::string& text) {
    std::ofstream f(p, std::ios::binary | std::ios::trunc);
    if (!f || !f.write(text.data(), text.size()) || !f.flush())
        throw std::runtime_error("Cannot write checkpoint file: " + p.string());
}
std::string digest(const fs::path& p) {
    // Integrity check for local files, not authentication. Build/disc IDs are SHA-256.
    std::ifstream f(p, std::ios::binary);
    if (!f) throw std::runtime_error("Cannot read checkpoint file: " + p.string());
    uint64_t h = 14695981039346656037ull;
    char block[65536];
    while (f) { f.read(block, sizeof block); for (std::streamsize i=0; i<f.gcount(); ++i) h = (h ^ (uint8_t)block[i]) * 1099511628211ull; }
    if (!f.eof()) throw std::runtime_error("Cannot finish reading checkpoint file");
    std::ostringstream s; s << std::hex << h; return s.str();
}
uint64_t number(const std::string& text) {
    if (text.empty() || text.find_first_not_of("0123456789") != std::string::npos)
        throw std::runtime_error("Invalid replay frame");
    size_t end = 0;
    auto n = std::stoull(text, &end);
    if (end != text.size()) throw std::runtime_error("Invalid replay frame");
    return n;
}
}

fs::path latest(const fs::path& root) {
    auto name = read(root / "latest.txt");
    if (name.empty() || name.find_first_not_of("0123456789-") != std::string::npos)
        throw std::runtime_error("No valid latest replay checkpoint");
    return root / name;
}

uint64_t verify(const fs::path& checkpoint, const fs::path& seed) {
    std::istringstream sums(read(checkpoint / "checksums.txt"));
    std::string name, hash;
    std::vector<std::string> expected_files(files.begin(), files.end());
    for (const char* optional : {"seed/settings.ini", "seed/backup.bin.cartridge"})
        if (fs::exists(checkpoint / optional)) expected_files.emplace_back(optional);
    unsigned found = 0;
    while (sums >> name >> hash) {
        // Only fixed filenames: never follow a path supplied by the checksum file.
        if (found >= expected_files.size()) throw std::runtime_error("Unexpected replay checkpoint entries");
        const std::string expected = expected_files[found];
        if (name != expected) throw std::runtime_error("Invalid replay checkpoint manifest");
        if (digest(checkpoint / name) != hash) throw std::runtime_error("Replay checkpoint is damaged: " + name);
        ++found;
    }
    if (found != expected_files.size())
        throw std::runtime_error("Incomplete replay checkpoint manifest");
    for (const char* id : {"build-id.txt", "disc-id.txt"})
        if (read(checkpoint / "seed" / id) != read(seed / id))
            throw std::runtime_error("Replay checkpoint belongs to a different native build or disc");
    auto point = read(checkpoint / "point.txt");
    if (point.substr(0, 11) != "SF3REPLAY1\n") throw std::runtime_error("Unsupported replay checkpoint format");
    auto frame = number(point.substr(11));
    if (!frame) throw std::runtime_error("Cannot resume replay frame zero");
    return frame;
}

fs::path save(const fs::path& root, const fs::path& seed, const fs::path& recording, uint64_t frame) {
    if (!frame) throw std::runtime_error("Wait until gameplay starts before saving a checkpoint");
    for (const char* f : {"context.json", "build-id.txt", "disc-id.txt", "backup.bin"}) read(seed / f);
    // Keep only presses before the handover frame. The runtime uses the same exclusive limit.
    std::istringstream script(read(recording));
    std::string token, filtered;
    while (std::getline(script, token, ',')) {
        auto first = token.find_first_not_of(" \r\n\t");
        if (first == std::string::npos) continue;
        token.erase(0, first);
        auto colon = token.find(':');
        if (colon == std::string::npos) throw std::runtime_error("Incomplete controller recording");
        if (number(token.substr(0, colon)) < frame) filtered += token + ',';
    }
    auto stamp = std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    auto name = std::to_string(stamp) + "-" + std::to_string(frame);
    auto path = root / name;
    fs::create_directories(path / "seed");
    try {
        for (const char* f : {"context.json", "build-id.txt", "disc-id.txt", "backup.bin", "settings.ini", "backup.bin.cartridge"})
            if (fs::exists(seed / f)) fs::copy_file(seed / f, path / "seed" / f);
        write(path / "point.txt", "SF3REPLAY1\n" + std::to_string(frame));
        write(path / "input.txt", filtered);
        std::string sums;
        for (const char* f : files) sums += std::string(f) + ' ' + digest(path / f) + '\n';
        if (fs::exists(path / "seed/settings.ini")) sums += "seed/settings.ini " + digest(path / "seed/settings.ini") + '\n';
        if (fs::exists(path / "seed/backup.bin.cartridge")) sums += "seed/backup.bin.cartridge " + digest(path / "seed/backup.bin.cartridge") + '\n';
        write(path / "checksums.txt", sums);
        verify(path, seed);
        write(root / "latest.txt.part", name);
        fs::rename(root / "latest.txt.part", root / "latest.txt");
    } catch (...) {
        // Keep incomplete evidence but never advertise it as the latest checkpoint.
        throw;
    }
    return path;
}

void request_load(const fs::path& root, const fs::path& seed, const fs::path& request) {
    auto path = latest(root);
    verify(path, seed);
    write(request, fs::absolute(path).string());
}
}
