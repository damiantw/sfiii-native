#pragma once
#include <SDL3/SDL.h>
#include <array>
#include <cstdint>
#include <filesystem>
#include <string>

namespace sf3 {
struct Control {
    const char *name;
    const char *sdl;
    uint16_t bit;
};
inline constexpr std::array<Control, 13> controls = {{{"UP", "dpup", 0x1000},
                                                      {"DOWN", "dpdown", 0x2000},
                                                      {"LEFT", "dpleft", 0x4000},
                                                      {"RIGHT", "dpright", 0x8000},
                                                      {"START", "start", 0x0800},
                                                      {"A", "x", 0x0400},
                                                      {"B", "a", 0x0100},
                                                      {"C", "b", 0x0200},
                                                      {"X", "y", 0x0040},
                                                      {"Y", "lefttrigger", 0x0020},
                                                      {"Z", "righttrigger", 0x0010},
                                                      {"L", "leftshoulder", 0x0008},
                                                      {"R", "rightshoulder", 0x0080}}};
void controller_hints();          // before SDL initialization
bool single_player_controllers(); // all connected pads drive SFIII's player 1
std::filesystem::path controller_directory();
void load_controller_mappings(); // database, then personal overrides
std::string controller_guid(SDL_JoystickID id);
std::string make_mapping(SDL_JoystickID id, const std::array<std::string, 13> &inputs);
void store_mapping(const std::filesystem::path &path, const std::string &mapping);
uint16_t default_controller_buttons(SDL_Gamepad *pad);
} // namespace sf3
