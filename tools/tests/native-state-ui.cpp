// Exercise native state UI requests with synthetic machine data only.
#include SF3_HOST_SOURCE
#include "state.h"
#include <filesystem>
#include <fstream>
extern const bool g_sh2_native_states=true;

int main(int argc,char** argv) {
    if(argc!=2)return 2;
    namespace fs=std::filesystem;
    const fs::path root=argv[1];fs::create_directories(root);
    auto environment=[](const char* k,const std::string& v){
#ifdef _WIN32
        _putenv_s(k,v.c_str());
#else
        setenv(k,v.c_str(),1);
#endif
    };
    environment("SF3_STATE_ROOT",root.string());environment("SF3_STATE_ID","synthetic-build:synthetic-disc");
    g_cfg.out=root.string();g_cfg.settings=(root/"settings.ini").string();
    std::vector<char> sector(2352);std::memcpy(sector.data()+16+0x20,"TEST STATE V1.00",16);
    {std::ofstream f(root/"disc.bin",std::ios::binary);f.write(sector.data(),sector.size());}
    {std::ofstream f(root/"disc.cue");f<<"FILE \"disc.bin\" BINARY\n TRACK 01 MODE1/2352\n INDEX 01 00:00:00\n";}
    if(!cdrom_open((root/"disc.cue").string()))return 3;
    if(!host_open())return 4;
    state_enable();state_init();
    Frame picture;picture.w=320;picture.h=240;picture.px.assign(320*240,0x123456);present(picture);
    auto click=[](int button) {
        SDL_Event e{};e.type=SDL_EVENT_MOUSE_BUTTON_DOWN;e.button.button=SDL_BUTTON_LEFT;
        auto r=replay_bar_button(button);
        SDL_RenderCoordinatesToWindow(g_ren,r.x+r.w/2,r.y+r.h/2,&e.button.x,&e.button.y);on_event(e);
    };
    SDL_Event key{};key.type=SDL_EVENT_KEY_DOWN;key.key.scancode=SDL_SCANCODE_F5;on_event(key);
    if(!state_save_busy() || !g_state_requested)return 5;
    state_native_point(g_master,0x06001000);state_finish();
    const auto slot=root/"latest.satstate";
    if(!fs::exists(slot) || state_save_busy())return 6;
    state_check_file(slot.string());
    auto first=fs::file_size(slot);
    // Toolbar overwrites an existing quick slot atomically on Windows.
    click(0);if(!state_save_busy())return 7;
    state_native_point(g_master,0x06001000);state_finish();
    if(fs::file_size(slot)!=first)return 8;
    bool stopped=false;try {click(1);}catch(...){stopped=true;}
    if(!stopped || !fs::exists(root/"native-state-request.txt"))return 9;
    fs::remove(root/"native-state-request.txt");
    {std::fstream f(slot,std::ios::binary|std::ios::in|std::ios::out);f.seekp(100);f.put('\xff');}
    key.key.scancode=SDL_SCANCODE_F9;on_event(key);
    if(fs::exists(root/"native-state-request.txt"))return 10;
    auto layout=menu_layout();bool save=false,load=false,replay=false;
    for(auto& r:layout.rows){save|=r.id==M_STATE_SAVE;load|=r.id==M_STATE_LOAD;replay|=r.id==M_REPLAY_LOAD;}
    if(!save || !load || !replay)return 11;
    std::printf("PASS: native F5, toolbar save/load, overwrite, damaged F9 keeps running, native and legacy menu entries\n");
    return 0;
}
