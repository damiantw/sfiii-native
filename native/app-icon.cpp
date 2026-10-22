#include "app-icon.h"
#include <SDL3/SDL.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif

bool sf3::set_app_icon(SDL_Window* window) {
#ifdef _WIN32
    if (!window) return false;
    auto hwnd=static_cast<HWND>(SDL_GetPointerProperty(SDL_GetWindowProperties(window),SDL_PROP_WINDOW_WIN32_HWND_POINTER,nullptr));
    if (!hwnd) return false;
    auto instance=GetModuleHandleW(nullptr);
    auto large=static_cast<HICON>(LoadImageW(instance,MAKEINTRESOURCEW(1),IMAGE_ICON,GetSystemMetrics(SM_CXICON),GetSystemMetrics(SM_CYICON),LR_SHARED));
    auto small=static_cast<HICON>(LoadImageW(instance,MAKEINTRESOURCEW(1),IMAGE_ICON,GetSystemMetrics(SM_CXSMICON),GetSystemMetrics(SM_CYSMICON),LR_SHARED));
    if (!large || !small) return false;
    SendMessageW(hwnd,WM_SETICON,ICON_BIG,reinterpret_cast<LPARAM>(large));
    SendMessageW(hwnd,WM_SETICON,ICON_SMALL,reinterpret_cast<LPARAM>(small));
    return SendMessageW(hwnd,WM_GETICON,ICON_BIG,0)==reinterpret_cast<LRESULT>(large)
        && SendMessageW(hwnd,WM_GETICON,ICON_SMALL,0)==reinterpret_cast<LRESULT>(small);
#else
    (void)window;
    return false;
#endif
}
