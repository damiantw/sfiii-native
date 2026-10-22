#pragma once
struct SDL_Window;
namespace sf3 {
// Use the executable's optional branding resource. Headless/non-Windows hosts
// and builds without an icon retain their platform default.
bool set_app_icon(SDL_Window* window);
}
