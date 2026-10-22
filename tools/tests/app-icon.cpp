#include "app-icon.h"
#include <SDL3/SDL.h>
#include <cstdio>
int main() {
    if(!SDL_Init(SDL_INIT_VIDEO))return 1;
    auto* window=SDL_CreateWindow("Application icon test",64,64,SDL_WINDOW_HIDDEN);
    bool passed=window && sf3::set_app_icon(window);
    SDL_DestroyWindow(window);SDL_Quit();
    std::puts(passed ? "PASS: embedded application resource assigned to native large and small window icons" : "FAIL: icon resource or native window icon assignment unavailable");
    return passed ? 0 : 1;
}
