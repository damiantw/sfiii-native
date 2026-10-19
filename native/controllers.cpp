#include "controllers.h"
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace sf3 {
bool single_player_controllers() {
    static const bool enabled = [] {
        const char *value = std::getenv("SF3_SINGLE_PLAYER_CONTROLLERS");
        return !value || std::string(value) != "0";
    }();
    return enabled;
}

void controller_hints() {
    // SDL's native USB/Bluetooth drivers; respect explicit user overrides.
    SDL_SetHintWithPriority(SDL_HINT_JOYSTICK_HIDAPI, "1", SDL_HINT_DEFAULT);
    SDL_SetHintWithPriority(SDL_HINT_JOYSTICK_HIDAPI_PS5, "1", SDL_HINT_DEFAULT);
}

std::filesystem::path controller_directory() {
    if (const char *configured = std::getenv("SF3_CONTROLLER_DIR"))
        return configured;
    auto base = std::filesystem::path(SDL_GetBasePath());
    if (base.filename().empty())
        base = base.parent_path();
    if (std::filesystem::exists(base / "gamecontrollerdb.txt"))
        return base;
    if (std::filesystem::exists(base.parent_path() / "gamecontrollerdb.txt"))
        return base.parent_path();
    return base;
}

void load_controller_mappings() {
    for (const char *name : {"gamecontrollerdb.txt", "controller-mappings.txt"}) {
        auto path = controller_directory() / name;
        if (!std::filesystem::exists(path))
            continue;
        int loaded = SDL_AddGamepadMappingsFromFile(path.string().c_str());
        std::fprintf(stderr, "controllers: %s: %d mappings%s%s\n", path.string().c_str(), loaded,
                     loaded < 0 ? ": " : "", loaded < 0 ? SDL_GetError() : "");
    }
}

std::string controller_guid(SDL_JoystickID id) {
    char guid[33];
    SDL_GUIDToString(SDL_GetJoystickGUIDForID(id), guid, sizeof guid);
    return guid;
}

std::string make_mapping(SDL_JoystickID id, const std::array<std::string, 13> &inputs) {
    const char *device_name = SDL_GetJoystickNameForID(id);
    std::string name = device_name ? device_name : "USB controller";
    for (char &c : name)
        if (c == ',' || c == '\n' || c == '\r')
            c = ' ';
    std::string line = controller_guid(id) + "," + name + " (SFIII),";
    for (size_t i = 0; i < controls.size(); ++i)
        if (!inputs[i].empty())
            line += std::string(controls[i].sdl) + ":" + inputs[i] + ",";
    return line + "platform:" + SDL_GetPlatform() + ",";
}

void store_mapping(const std::filesystem::path &path, const std::string &mapping) {
    std::string guid = mapping.substr(0, 32), text, line;
    std::ifstream old(path);
    while (std::getline(old, line))
        if (line.substr(0, 33) != guid + ",")
            text += line + "\n";
    old.close();
    text += mapping + "\n";
    auto temporary = path;
    temporary += ".tmp";
    {
        std::ofstream out(temporary, std::ios::binary);
        out << text;
        if (!out)
            throw std::runtime_error("Cannot write controller mappings");
    }
    // Filesystem rename replaces an existing regular file atomically on supported hosts.
    std::filesystem::rename(temporary, path);
}

uint16_t default_controller_buttons(SDL_Gamepad *pad) {
    uint16_t held = 0;
    for (auto &control : controls) {
        bool down;
        if (std::string(control.sdl) == "lefttrigger")
            down = SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_LEFT_TRIGGER) > 16383;
        else if (std::string(control.sdl) == "righttrigger")
            down = SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER) > 16383;
        else
            down = SDL_GetGamepadButton(pad, SDL_GetGamepadButtonFromString(control.sdl));
        if (down)
            held |= control.bit;
    }
    auto x = SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_LEFTX),
         y = SDL_GetGamepadAxis(pad, SDL_GAMEPAD_AXIS_LEFTY);
    if (x > 16383)
        held |= 0x8000;
    if (x < -16383)
        held |= 0x4000;
    if (y > 16383)
        held |= 0x2000;
    if (y < -16383)
        held |= 0x1000;
    if ((held & 0xC000) == 0xC000)
        held &= ~0xC000;
    if ((held & 0x3000) == 0x3000)
        held &= ~0x3000;
    return held;
}
} // namespace sf3
