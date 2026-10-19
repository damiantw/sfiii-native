// SDL virtual controllers only; no game data or physical button presses.
#include "controllers.h"
#include <chrono>
#include <fstream>
#include <iostream>
#include <stdexcept>

static int checks;
static void check(bool value, const char *why) {
    ++checks;
    if (!value)
        throw std::runtime_error(std::string(why) + ": " + SDL_GetError());
}
static void update() {
    SDL_UpdateJoysticks();
    SDL_UpdateGamepads();
    SDL_PumpEvents();
}
static SDL_JoystickID attach(const char *name, SDL_JoystickType type, int axes, int hats, int buttons,
                             Uint16 vendor = 0, Uint16 product = 0) {
    SDL_VirtualJoystickDesc desc;
    SDL_INIT_INTERFACE(&desc);
    desc.name = name;
    desc.type = type;
    desc.naxes = axes;
    desc.nhats = hats;
    desc.nbuttons = buttons;
    desc.vendor_id = vendor;
    desc.product_id = product;
    auto id = SDL_AttachVirtualJoystick(&desc);
    check(id != 0, "attach virtual controller");
    return id;
}
static void standardized(const char *name, Uint16 vendor, Uint16 product) {
    auto id = attach(name, SDL_JOYSTICK_TYPE_GAMEPAD, SDL_GAMEPAD_AXIS_COUNT, 0, SDL_GAMEPAD_BUTTON_COUNT,
                     vendor, product);
    auto joy = SDL_OpenJoystick(id);
    check(joy, "open virtual joystick");
    SDL_SetJoystickVirtualAxis(joy, SDL_GAMEPAD_AXIS_LEFT_TRIGGER, -32768);
    SDL_SetJoystickVirtualAxis(joy, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER, -32768);
    update();
    auto pad = SDL_OpenGamepad(id);
    check(pad, "open standardized gamepad");
    check(sf3::default_controller_buttons(pad) == 0, "neutral pad");
    for (auto &control : sf3::controls) {
        bool trigger = std::string(control.sdl).find("trigger") != std::string::npos;
        auto axis = std::string(control.sdl) == "lefttrigger" ? SDL_GAMEPAD_AXIS_LEFT_TRIGGER
                                                              : SDL_GAMEPAD_AXIS_RIGHT_TRIGGER;
        auto button = SDL_GetGamepadButtonFromString(control.sdl);
        if (trigger)
            SDL_SetJoystickVirtualAxis(joy, axis, 32767);
        else
            SDL_SetJoystickVirtualButton(joy, button, true);
        update();
        check(sf3::default_controller_buttons(pad) == control.bit, control.name);
        if (trigger)
            SDL_SetJoystickVirtualAxis(joy, axis, -32768);
        else
            SDL_SetJoystickVirtualButton(joy, button, false);
        update();
        check(sf3::default_controller_buttons(pad) == 0, "button release");
    }
    SDL_SetJoystickVirtualAxis(joy, SDL_GAMEPAD_AXIS_LEFTX, 8000);
    update();
    check(sf3::default_controller_buttons(pad) == 0, "stick deadzone");
    SDL_SetJoystickVirtualAxis(joy, SDL_GAMEPAD_AXIS_LEFTX, 24000);
    update();
    check(sf3::default_controller_buttons(pad) == 0x8000, "left stick right");
    SDL_SetJoystickVirtualAxis(joy, SDL_GAMEPAD_AXIS_LEFTX, 0);
    SDL_SetJoystickVirtualButton(joy, SDL_GAMEPAD_BUTTON_DPAD_UP, true);
    SDL_SetJoystickVirtualButton(joy, SDL_GAMEPAD_BUTTON_DPAD_DOWN, true);
    update();
    check(sf3::default_controller_buttons(pad) == 0, "opposite directions neutralize");
    SDL_DetachVirtualJoystick(id);
    update();
    check(!SDL_GamepadConnected(pad), "disconnect detected");
    SDL_CloseGamepad(pad);
    SDL_CloseJoystick(joy);
    std::cout << "PASS standardized path: " << name << "\n";
}
static void raw(bool axes) {
    auto name = axes ? "SFIII generic axis USB test" : "SFIII Saturn six-face USB test";
    auto id = attach(name, SDL_JOYSTICK_TYPE_UNKNOWN, axes ? 2 : 0, axes ? 0 : 1, 9, 0x1209,
                     axes ? 0x5f32 : 0x5f31);
    auto joy = SDL_OpenJoystick(id);
    check(joy, "raw joystick");
    update();
    std::array<std::string, 13> input;
    if (axes) {
        input[0] = "-a1";
        input[1] = "+a1";
        input[2] = "-a0";
        input[3] = "+a0";
    } else {
        input[0] = "h0.1";
        input[1] = "h0.4";
        input[2] = "h0.8";
        input[3] = "h0.2";
    }
    input[4] = "b8";
    for (int i = 5; i < 13; ++i)
        input[i] = "b" + std::to_string(i - 5);
    auto mapping = sf3::make_mapping(id, input);
    check(SDL_AddGamepadMapping(mapping.c_str()) >= 0, "install raw mapping");
    update();
    auto pad = SDL_OpenGamepad(id);
    check(pad, "raw pad promoted to SDL gamepad");
    check(sf3::default_controller_buttons(pad) == 0, "raw pad neutral");
    for (int i = 0; i < 13; ++i) {
        if (i < 4) {
            if (axes)
                SDL_SetJoystickVirtualAxis(joy, i < 2 ? 1 : 0, (i == 0 || i == 2) ? -32768 : 32767);
            else
                SDL_SetJoystickVirtualHat(joy, 0, i == 0 ? 1 : i == 1 ? 4 : i == 2 ? 8 : 2);
        } else
            SDL_SetJoystickVirtualButton(joy, i == 4 ? 8 : i - 5, true);
        update();
        check(sf3::default_controller_buttons(pad) == sf3::controls[i].bit, sf3::controls[i].name);
        if (i < 4) {
            if (axes)
                SDL_SetJoystickVirtualAxis(joy, i < 2 ? 1 : 0, 0);
            else
                SDL_SetJoystickVirtualHat(joy, 0, 0);
        } else
            SDL_SetJoystickVirtualButton(joy, i == 4 ? 8 : i - 5, false);
        update();
        check(sf3::default_controller_buttons(pad) == 0, "raw release");
    }
    if (!axes) {
        SDL_SetJoystickVirtualHat(joy, 0, 3);
        update();
        check(sf3::default_controller_buttons(pad) == 0x9000, "hat diagonal");
    }
    auto directory =
        std::filesystem::temp_directory_path() /
        ("sf3-input-check-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::create_directory(directory);
    auto file = directory / "controller-mappings.txt";
    {
        std::ofstream out(file);
        out << "# keep comment\n11111111111111111111111111111111,Other controller,a:b0,platform:Windows,\n";
    }
    sf3::store_mapping(file, mapping);
    sf3::store_mapping(file, mapping);
    std::ifstream in(file);
    std::string text((std::istreambuf_iterator<char>(in)), {});
    check(text.find("# keep comment") != std::string::npos, "preserve other settings");
    auto at = text.find(sf3::controller_guid(id));
    check(at != std::string::npos && text.find(sf3::controller_guid(id), at + 1) == std::string::npos,
          "replace own GUID without duplicates");
    check(SDL_AddGamepadMappingsFromFile(file.string().c_str()) >= 0, "reload saved mapping file");
    in.close();
    std::filesystem::remove(file);
    std::filesystem::remove(directory);
    auto old_guid = sf3::controller_guid(id);
    SDL_DetachVirtualJoystick(id);
    update();
    check(!SDL_GamepadConnected(pad), "raw unplug");
    SDL_CloseGamepad(pad);
    SDL_CloseJoystick(joy);
    auto again = attach(name, SDL_JOYSTICK_TYPE_UNKNOWN, axes ? 2 : 0, axes ? 0 : 1, 9, 0x1209,
                        axes ? 0x5f32 : 0x5f31);
    update();
    check(sf3::controller_guid(again) == old_guid, "reconnect GUID stable");
    check(SDL_IsGamepad(again), "mapping survives reconnect");
    SDL_DetachVirtualJoystick(again);
    std::cout << "PASS mapped raw USB path: " << name << "\n";
}
int main() {
    sf3::controller_hints();
    if (!SDL_Init(SDL_INIT_GAMEPAD)) {
        std::cerr << SDL_GetError() << "\n";
        return 1;
    }
    try {
        standardized("DualSense standardized virtual test", 0x054c, 0x0ce6);
        standardized("Xbox standardized virtual test", 0x045e, 0x02ea);
        raw(false);
        raw(true);
        std::cout << "PASS " << checks
                  << " controller checks. Physical USB/Bluetooth devices still need user verification.\n";
    } catch (const std::exception &error) {
        std::cerr << "FAIL " << error.what() << "\n";
        SDL_Quit();
        return 1;
    }
    SDL_Quit();
    return 0;
}
