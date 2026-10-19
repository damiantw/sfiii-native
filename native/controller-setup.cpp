#include "controllers.h"
#include <algorithm>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <set>
#include <vector>
#ifdef _WIN32
#include <conio.h>
#endif

static std::vector<SDL_JoystickID> devices() {
    SDL_PumpEvents();
    int count = 0;
    SDL_JoystickID *ids = SDL_GetJoysticks(&count);
    std::vector<SDL_JoystickID> result;
    if (ids)
        result.assign(ids, ids + count);
    SDL_free(ids);
    return result;
}

static void list() {
    auto ids = devices();
    if (ids.empty())
        std::cout
            << "No controllers detected. Connect one with USB or pair it in Windows Bluetooth settings.\n";
    for (size_t i = 0; i < ids.size(); ++i) {
        auto id = ids[i];
        SDL_Joystick *joystick = SDL_OpenJoystick(id);
        if (!joystick)
            continue;
        std::cout << i + 1 << ". " << SDL_GetJoystickName(joystick) << "\n   GUID "
                  << sf3::controller_guid(id) << "; " << SDL_GetNumJoystickButtons(joystick) << " buttons; "
                  << SDL_GetNumJoystickAxes(joystick) << " axes; " << SDL_GetNumJoystickHats(joystick)
                  << " hats; " << (SDL_IsGamepad(id) ? "mapped" : "needs setup") << "\n";
        SDL_CloseJoystick(joystick);
    }
}

static bool console_skip() {
#ifdef _WIN32
    if (_kbhit()) {
        int key = _getch();
        if (key == 's' || key == 'S')
            return true;
        if (key == 27 || key == 'q' || key == 'Q')
            throw std::runtime_error("Setup cancelled; no mapping saved");
    }
#endif
    return false;
}

static std::string capture(SDL_Joystick *joystick, const std::vector<Sint16> &rest) {
    const auto id = SDL_GetJoystickID(joystick);
    // Release digital controls before accepting a new press.
    for (;;) {
        if (console_skip())
            return {};
        SDL_PumpEvents();
        if (!SDL_JoystickConnected(joystick))
            throw std::runtime_error("Controller disconnected; no mapping saved");
        bool held = false;
        for (int i = 0; i < SDL_GetNumJoystickButtons(joystick); ++i)
            held |= SDL_GetJoystickButton(joystick, i);
        for (int i = 0; i < SDL_GetNumJoystickHats(joystick); ++i)
            held |= SDL_GetJoystickHat(joystick, i) != SDL_HAT_CENTERED;
        for (int i = 0; i < (int)rest.size(); ++i)
            held |= std::abs(SDL_GetJoystickAxis(joystick, i) - rest[i]) > 8000;
        if (!held)
            break;
        SDL_Delay(10);
    }
    SDL_FlushEvents(SDL_EVENT_JOYSTICK_AXIS_MOTION, SDL_EVENT_JOYSTICK_BUTTON_UP);
    for (;;) {
        if (!SDL_JoystickConnected(joystick))
            throw std::runtime_error("Controller disconnected; no mapping saved");
        if (console_skip())
            return {};
        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_EVENT_JOYSTICK_BUTTON_DOWN && event.jbutton.which == id)
                return "b" + std::to_string(event.jbutton.button);
            if (event.type == SDL_EVENT_JOYSTICK_HAT_MOTION && event.jhat.which == id) {
                int value = event.jhat.value;
                if (value == 1 || value == 2 || value == 4 || value == 8)
                    return "h" + std::to_string(event.jhat.hat) + "." + std::to_string(value);
            }
            if (event.type == SDL_EVENT_JOYSTICK_AXIS_MOTION && event.jaxis.which == id) {
                int axis = event.jaxis.axis, value = event.jaxis.value;
                if (axis < (int)rest.size() && std::abs(value - rest[axis]) > 20000)
                    return (rest[axis] < -20000 && value > 16000 ? "a"
                            : value < 0                          ? "-a"
                                                                 : "+a") +
                           std::to_string(axis);
            }
        }
        SDL_Delay(5);
    }
}

static void setup() {
    list();
    auto ids = devices();
    if (ids.empty())
        return;
    std::cout << "Controller number (Enter cancels): " << std::flush;
    std::string answer;
    std::getline(std::cin, answer);
    if (answer.empty())
        return;
    size_t selected = std::stoul(answer);
    if (selected < 1 || selected > ids.size())
        throw std::runtime_error("Invalid controller number");
    SDL_Joystick *joystick = SDL_OpenJoystick(ids[selected - 1]);
    if (!joystick)
        throw std::runtime_error(SDL_GetError());
    std::cout
        << "Bind the controls by their SATURN labels. This works even when Windows calls the device a "
           "joystick.\n"
           "Release each control after pressing it. Centre sticks and release triggers before each step.\n"
           "S skips an unavailable button; Q or Esc cancels without saving.\n";
    std::cout << "Centre sticks and release all controls, then press Enter on the keyboard." << std::flush;
    std::getline(std::cin, answer);
    SDL_PumpEvents();
    std::vector<Sint16> rest;
    for (int i = 0; i < SDL_GetNumJoystickAxes(joystick); ++i)
        rest.push_back(SDL_GetJoystickAxis(joystick, i));
    std::array<std::string, 13> inputs;
    std::set<std::string> used;
    for (size_t i = 0; i < inputs.size();) {
        std::cout << "\nPress SATURN " << sf3::controls[i].name << ": " << std::flush;
        auto input = capture(joystick, rest);
        if (!input.empty() && used.count(input)) {
            std::cout << "Already bound. Try another control.\n";
            continue;
        }
        inputs[i] = input;
        if (!input.empty())
            used.insert(input);
        std::cout << (input.empty() ? "skipped" : input) << std::endl;
        // Allow axis/trigger travel to return before taking the next baseline.
        SDL_Delay(250);
        ++i;
    }
    auto mapping = sf3::make_mapping(ids[selected - 1], inputs);
    if (SDL_AddGamepadMapping(mapping.c_str()) < 0)
        throw std::runtime_error(SDL_GetError());
    auto path = sf3::controller_directory() / "controller-mappings.txt";
    sf3::store_mapping(path, mapping);
    SDL_CloseJoystick(joystick);
    std::cout << "\nSaved " << path.string()
              << ". Restart the game to use it. Run Controller Test to check every button.\n";
}

static void test() {
    if (!SDL_InitSubSystem(SDL_INIT_VIDEO))
        throw std::runtime_error(SDL_GetError());
    SDL_Window *window = nullptr;
    SDL_Renderer *renderer = nullptr;
    if (!SDL_CreateWindowAndRenderer("SFIII Controller Test - close to finish", 900, 600,
                                     SDL_WINDOW_RESIZABLE, &window, &renderer))
        throw std::runtime_error(SDL_GetError());
    bool run = true;
    std::vector<std::pair<SDL_JoystickID, SDL_Gamepad *>> open;
    while (run) {
        SDL_Event event;
        while (SDL_PollEvent(&event))
            if (event.type == SDL_EVENT_QUIT ||
                (event.type == SDL_EVENT_KEY_DOWN && event.key.key == SDLK_ESCAPE))
                run = false;
        for (auto it = open.begin(); it != open.end();) {
            if (!SDL_GamepadConnected(it->second)) {
                SDL_CloseGamepad(it->second);
                it = open.erase(it);
            } else
                ++it;
        }
        for (auto id : devices())
            if (SDL_IsGamepad(id) &&
                std::none_of(open.begin(), open.end(), [&](auto &item) { return item.first == id; })) {
                if (auto pad = SDL_OpenGamepad(id))
                    open.push_back({id, pad});
            }
        SDL_SetRenderDrawColor(renderer, 18, 22, 30, 255);
        SDL_RenderClear(renderer);
        SDL_SetRenderScale(renderer, 2, 2);
        SDL_SetRenderDrawColor(renderer, 240, 240, 240, 255);
        SDL_RenderDebugText(renderer, 10, 10, "SFIII: SATURN button labels (green = pressed)");
        if (open.empty())
            SDL_RenderDebugText(renderer, 10, 35, "Connect a controller, or run Controller Setup first.");
        float y = 35;
        for (auto &[id, pad] : open) {
            SDL_SetRenderDrawColor(renderer, 240, 240, 240, 255);
            SDL_RenderDebugText(renderer, 10, y, SDL_GetGamepadName(pad));
            y += 14;
            auto bits = sf3::default_controller_buttons(pad);
            float x = 10;
            for (auto &control : sf3::controls) {
                if (bits & control.bit)
                    SDL_SetRenderDrawColor(renderer, 70, 245, 130, 255);
                else
                    SDL_SetRenderDrawColor(renderer, 130, 140, 155, 255);
                SDL_RenderDebugText(renderer, x, y, control.name);
                x += (std::string(control.name).size() + 2) * 8;
                if (x > 400) {
                    x = 10;
                    y += 14;
                }
            }
            y += 35;
        }
        SDL_SetRenderScale(renderer, 1, 1);
        SDL_RenderPresent(renderer);
        SDL_Delay(16);
    }
    for (auto &item : open)
        SDL_CloseGamepad(item.second);
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
}

int main(int argc, char **argv) {
    sf3::controller_hints();
    if (!SDL_Init(SDL_INIT_GAMEPAD)) {
        std::cerr << SDL_GetError() << std::endl;
        return 1;
    }
    sf3::load_controller_mappings();
    try {
        std::string mode = argc > 1 ? argv[1] : "--setup";
        if (mode == "--list")
            list();
        else if (mode == "--test")
            test();
        else if (mode == "--setup")
            setup();
        else
            throw std::runtime_error("Use --list, --setup or --test");
    } catch (const std::exception &error) {
        std::cerr << error.what() << std::endl;
        SDL_Quit();
        return 1;
    }
    SDL_Quit();
    return 0;
}
