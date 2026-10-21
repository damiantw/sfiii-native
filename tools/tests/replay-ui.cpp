// Exercise the actual native UI with SDL dummy devices, without game code or assets.
#include SF3_HOST_SOURCE
#include "state.h"
#include <filesystem>
#include <fstream>

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    namespace fs = std::filesystem;
    auto root = fs::path(argv[1]);
    fs::create_directories(root);
    g_cfg.out = root.string();
    g_cfg.record_input = (root / "input.txt").string();
    g_cfg.settings = (root / "settings.ini").string();
    { std::ofstream f(g_cfg.record_input); f << "100:START,110:,700:A,"; }
    if (!host_open()) return 3;
    aspect_set(false);
    resolution_set(1); // Start repeatably; fixture preferences may be retained.
    State state;
    uint64_t line = 0, frame = 600;
    state(line); state(frame); state.loading = true;
    video_state(state);
    Frame picture; picture.w=320; picture.h=240; picture.px.assign(320*240, 0x102030);
    present(picture);
    SDL_Event event{};
    event.type=SDL_EVENT_KEY_DOWN; event.key.scancode=SDL_SCANCODE_F5;
    on_event(event);
    auto checkpoint = sf3_replay::latest(std::getenv("SF3_REPLAY_ROOT"));
    if (sf3_replay::verify(checkpoint, std::getenv("SF3_REPLAY_SEED")) != 600) return 4;
    auto click = [&](int button) {
        SDL_Event mouse{}; mouse.type=SDL_EVENT_MOUSE_BUTTON_DOWN; mouse.button.button=SDL_BUTTON_LEFT;
        auto rect = replay_bar_button(button);
        SDL_RenderCoordinatesToWindow(g_ren, rect.x+rect.w/2, rect.y+rect.h/2, &mouse.button.x, &mouse.button.y);
        on_event(mouse);
    };
    auto initial_pixels=picture.px;
    click(5);
    if(vdp1_render_scale()!=2 || picture.px!=initial_pixels)return 20;
    click(6);if(vdp1_render_scale()!=4)return 21;
    click(7);if(vdp1_render_scale()!=5 || choice_at(M_RESOLUTION)!=3)return 41;
    load_settings(g_cfg.settings);if(vdp1_render_scale()!=5)return 42;
    for(int i=0;i<4+kRenderScaleCount;++i) {
        auto a=replay_bar_button(i);
        if(a.x<0 || a.x+a.w>g_out_w)return 43;
        if(i && replay_bar_button(i-1).x+replay_bar_button(i-1).w>a.x)return 44;
    }
    click(4);if(vdp1_render_scale()!=1)return 22;
    click(5);
    click(0);
    auto second = sf3_replay::latest(std::getenv("SF3_REPLAY_ROOT"));
    if (second == checkpoint) return 5;
    event.key.scancode=SDL_SCANCODE_F8;
    on_event(event);
    click(2);
    auto work = fs::path(std::getenv("SF3_CONTROLLER_DIR"));
    std::ifstream pointer(work / "last-capture.txt");
    std::string capture_path((std::istreambuf_iterator<char>(pointer)), {});
    for (const char* file : {"game.png", "window.png", "context.txt", "capture.json", "input.txt", "wram-high.bin", "wram-low.bin", "dump-600.bin"})
        if (!fs::exists(fs::path(capture_path) / file)) return 12;
    if (fs::file_size(fs::path(capture_path) / "wram-high.bin") != 0x100000) return 13;
    if (fs::file_size(fs::path(capture_path) / "dump-600.bin") != 0x141220) return 14;
    click(3);
    if (!g_menu_open) return 6;
    auto layout = menu_layout();
    bool save=false, load=false, has_capture=false;
    for (auto& row : layout.rows) { save |= row.id==M_REPLAY_SAVE; load |= row.id==M_REPLAY_LOAD; has_capture |= row.id==M_CAPTURE; }
    if (!save || !load || !has_capture) return 7;
    auto resolution_row=std::find_if(layout.rows.begin(),layout.rows.end(),[](const MenuRow& r){return r.id==M_RESOLUTION;});
    if(resolution_row==layout.rows.end() || resolution_row->control!=Control::Choice)return 27;
    auto aspect_row=std::find_if(layout.rows.begin(),layout.rows.end(),[](const MenuRow& r){return r.id==M_ASPECT;});
    if(aspect_row==layout.rows.end() || aspect_row->control!=Control::Choice || choice_count(M_ASPECT)!=2)return 36;
    menu_adjust(M_ASPECT,1);if(!vdp1_widescreen() || choice_at(M_ASPECT)!=1 || picture.px!=initial_pixels)return 37;
    load_settings(g_cfg.settings);if(!vdp1_widescreen())return 38;
    resolution_set(1);if(g_gpu_active && !vdp1_gpu_active())return 39;
    aspect_set(false);if(vdp1_widescreen() || vdp1_gpu_active())return 40;
    resolution_set(2);
    for(const auto& row:layout.rows)if(std::string(menu_label(row.id)).find("HD")!=std::string::npos)return 28;
    menu_adjust(M_RESOLUTION,1);if(vdp1_render_scale()!=4)return 29;
    {std::ofstream saved(g_cfg.settings);saved<<"[display]\ninternal_scale = 1\n";}
    load_settings(g_cfg.settings);if(vdp1_render_scale()!=4)return 30;
    menu_adjust(M_RESOLUTION,1);if(vdp1_render_scale()!=5)return 45;
    menu_adjust(M_RESOLUTION,1);if(vdp1_render_scale()!=1)return 31;
    menu_adjust(M_RESOLUTION,1);if(vdp1_render_scale()!=2)return 32;
    upload_frame(picture);
    if(vdp1_gpu_active()) {
        float w=0,h=0;if(!g_gpu_tex || !SDL_GetTextureSize(g_gpu_tex,&w,&h) || w!=640 || h!=480)return 33;
        Frame readback;if(!g_gpu.capture(readback) || readback.w!=640 || readback.h!=480)return 34;
        for(auto p:readback.px)if(p!=0x102030)return 35;
    }
    menu_activate(M_REPLAY_SAVE);
    menu_activate(M_CAPTURE);
    draw(false);
    SDL_Surface* surface = SDL_RenderReadPixels(g_ren, nullptr);
    if (!surface) return 8;
    SDL_Surface* rgb = SDL_ConvertSurface(surface, SDL_PIXELFORMAT_XRGB8888);
    if (!rgb) return 9;
    Frame capture; capture.w=rgb->w; capture.h=rgb->h; capture.px.resize(rgb->w*rgb->h);
    for (int y=0; y<rgb->h; ++y) std::memcpy(capture.px.data()+y*rgb->w, (uint8_t*)rgb->pixels+y*rgb->pitch, rgb->w*4);
    write_png((root / "menu.png").string(), capture);
    SDL_DestroySurface(rgb); SDL_DestroySurface(surface);
    menu_close();
    bool stopped=false;
    try { click(1); } catch (...) { stopped=true; }
    if (!stopped || !fs::exists(root / "reload-request.txt")) return 10;
    fs::remove(root / "reload-request.txt");
    auto last = sf3_replay::latest(std::getenv("SF3_REPLAY_ROOT"));
    { std::ofstream changed(last / "input.txt", std::ios::app); changed << "damaged"; }
    stopped=false;
    try { click(1); } catch (...) { stopped=true; }
    if (stopped || fs::exists(root / "reload-request.txt")) return 11;
    std::printf("PASS: F5/F8, toolbar save/load/capture, menu, capture files, reload, damaged load keeps running\n");
    return 0;
}
