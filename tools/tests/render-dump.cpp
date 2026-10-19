// Local diagnostic only: recompose a native video dump without running game code.
#include "saturn.h"
#include "video.h"
#include "hd-presentation.h"
#include <fstream>
#include <iterator>
#include <cstring>
#include <cstdio>
#include <chrono>
#ifdef SF3_GPU_DIAGNOSTIC
#include "hd-gpu.h"
#endif

int main(int argc, char** argv) {
    if (argc < 3 || argc > 11) { std::fprintf(stderr, "usage: render_dump dump.bin output.png [--redraw] [--hd] [--assets PACK] [--bench] [--raster-bench] [--render-scale 1|2|4]\n"); return 2; }
    bool redraw=false, hd=false;
    bool bench=false,raster_bench=false;
    std::string pack;
    for(int i=3;i<argc;++i) {
        if(std::string(argv[i])=="--redraw") redraw=true;
        else if(std::string(argv[i])=="--hd") hd=true;
        else if(std::string(argv[i])=="--assets" && i+1<argc) pack=argv[++i];
        else if(std::string(argv[i])=="--bench") bench=true;
        else if(std::string(argv[i])=="--raster-bench") raster_bench=true;
        else if(std::string(argv[i])=="--render-scale" && i+1<argc) {
            const std::string value=argv[++i];
            if(value!="1" && value!="2" && value!="4") return 2;
            vdp1_render_scale(std::stoi(value));
        }
        else return 2;
    }
    std::ifstream input(argv[1], std::ios::binary);
    std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(input)), {});
    constexpr size_t v2 = 0x80000 + 0x40000 + 0x20;
    if (bytes.size() != v2 + sizeof g_vdp2_vram + sizeof g_vdp2_cram + sizeof g_vdp2_regs) {
        std::fprintf(stderr, "unexpected native video dump size: %zu\n", bytes.size()); return 2;
    }
    vdp1_init();
    vdp1_hd_collect(!pack.empty());
    std::memcpy(g_vdp1_vram, bytes.data(), sizeof g_vdp1_vram);
    vdp1_reg_write(0, (bytes[0xc0000] << 8) | bytes[0xc0001], 2);
    if (redraw) {
        vdp1_reg_write(4, 1, 2);
    } else {
        for (unsigned i = 0; i < 0x40000; i += 2)
            vdp1_fb_write(i, (bytes[0x80000+i] << 8) | bytes[0x80001+i], 2);
    }
    vdp1_vblank_out();
    std::memcpy(g_vdp2_vram, bytes.data()+v2, sizeof g_vdp2_vram);
    std::memcpy(g_vdp2_cram, bytes.data()+v2+sizeof g_vdp2_vram, sizeof g_vdp2_cram);
    std::memcpy(g_vdp2_regs, bytes.data()+v2+sizeof g_vdp2_vram+sizeof g_vdp2_cram, sizeof g_vdp2_regs);
    Frame frame;
    vdp2_compose(frame);
    if(raster_bench) {
        const auto begin=std::chrono::steady_clock::now();
        for(int i=0;i<10;++i) {vdp1_reg_write(4,1,2);vdp1_vblank_out();vdp2_compose(frame);}
        const auto elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count();
        std::printf("Internal %dx: %.2f ms/draw+compose, %dx%d (CPU raster; excludes upload/presentation)\n",vdp1_render_scale(),elapsed/10,frame.w,frame.h);
    }
    sf3::HdPresentation presentation;
    sf3::HdAssets assets;
    if(!pack.empty()) { std::printf("Loaded %zu HD assets\n",assets.load(pack));presentation.assets(&assets); }
#ifdef SF3_GPU_DIAGNOSTIC
    if(pack.empty() || !SDL_Init(SDL_INIT_VIDEO)) return 3;
    sf3::HdGpu gpu;auto* renderer=gpu.create_renderer(nullptr);
    std::string shader_dir=std::string(SDL_GetBasePath())+"shaders";
    if(!renderer || !gpu.initialize(renderer,assets,shader_dir)) {std::fprintf(stderr,"GPU init: %s\n",SDL_GetError());return 4;}
    std::printf("GPU backend=%s adapter=%s\n",gpu.backend(),gpu.adapter());
    auto* scratch=SDL_CreateTexture(renderer,SDL_PIXELFORMAT_ARGB8888,SDL_TEXTUREACCESS_TARGET,1440,1080);
    if(!scratch || !SDL_SetRenderTarget(renderer,scratch)) return 5;
    auto* texture=gpu.render(frame,assets);
    if(!texture || !SDL_SetRenderTarget(renderer,texture)) {std::fprintf(stderr,"GPU render: %s\n",SDL_GetError());return 5;}
    auto* readback=SDL_RenderReadPixels(renderer,nullptr);
    if(!readback) {std::fprintf(stderr,"GPU readback: %s\n",SDL_GetError());return 6;}
    auto* converted=SDL_ConvertSurface(readback,SDL_PIXELFORMAT_ARGB8888);
    if(!converted) return 7;
    Frame actual;actual.w=1440;actual.h=1080;actual.px.resize(1440*1080);
    for(int y=0;y<1080;++y) std::memcpy(actual.px.data()+y*1440,(uint8_t*)converted->pixels+y*converted->pitch,1440*4);
    const auto& expected=assets.overlay(frame);size_t bad=0,different=0;int maximum=0;
    write_png((std::string(argv[2])+".cpu-overlay.png").c_str(),expected);
    for(size_t i=0;i<actual.px.size();++i) {
        if(!(expected.px[i]>>24) && !(actual.px[i]>>24)) continue;
        int error=0;for(int sh=0;sh<32;sh+=8) error=std::max(error,std::abs(int((actual.px[i]>>sh)&255)-int((expected.px[i]>>sh)&255)));
        maximum=std::max(maximum,error);bad+=error>2;different+=error>0;
    }
    write_png((std::string(argv[2])+".gpu-overlay.png").c_str(),actual);
    std::printf("GPU/CPU overlay: %zu pixels differ, %zu exceed 2/255, maximum channel error %d\n",different,bad,maximum);
    SDL_DestroySurface(converted);SDL_DestroySurface(readback);SDL_SetRenderTarget(renderer,scratch);
    auto begin=std::chrono::steady_clock::now();
    for(int i=0;i<60;++i) {if(!gpu.render(frame,assets)) return 8;SDL_FlushRenderer(renderer);}
    SDL_WaitForGPUIdle(SDL_GetGPURendererDevice(renderer));
    std::printf("GPU upload/projection/sampling/composition: %.3f ms/frame (60 frames, synchronized batch)\n",std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count()/60);
    // Exercise shader branches beyond this particular captured game's lighting.
    for(int test=0;test<4 && frame.hd;++test) {
        Frame variant=frame;variant.hd=std::make_shared<HdScene>(*frame.hd);
        variant.hd->geometry+=100+test;
        if(test==0) for(auto& q:variant.hd->quads) {
            q.hflip=!q.hflip;q.vflip=!q.vflip;
            for(int n=0;n<12;++n) q.shade[n]=float((n%5)-2)*4;
        }
        if(test==1) {
            variant.hd->effects.resize(variant.px.size());
            for(size_t i=0;i<variant.px.size();++i) {
                if(i%7==0) variant.hd->visible[i]=0;
                auto& e=variant.hd->effects[i];e.flags=uint8_t(1|(i%3==0?2:0)|(i%5==0?4:0));
                e.second=0x304060;e.ratio=uint8_t(i%32);e.offset[0]=-7;e.offset[1]=11;e.offset[2]=-2;
            }
        }
        if(test==2) for(auto& q:variant.hd->quads) for(auto& xy:q.xy) xy=0;
        if(test==3) variant.hd.reset();
        auto* result=gpu.render(variant,assets);
        if(!result || !SDL_SetRenderTarget(renderer,result)) return 10;
        auto* surface=SDL_RenderReadPixels(renderer,nullptr);
        if(!surface) return 11;
        auto* rgba=SDL_ConvertSurface(surface,SDL_PIXELFORMAT_ARGB8888);
        if(!rgba) return 12;
        const auto& reference=assets.overlay(variant);size_t errors=0;
        for(int y=0;y<1080;++y) for(int x=0;x<1440;++x) {
            uint32_t got=((uint32_t*)((uint8_t*)rgba->pixels+y*rgba->pitch))[x],want=reference.px[y*1440+x];
            if(!(got>>24) && !(want>>24)) continue;
            int difference=0;for(int sh=0;sh<32;sh+=8) difference=std::max(difference,std::abs(int((got>>sh)&255)-int((want>>sh)&255)));
            errors+=difference>2;
        }
        SDL_DestroySurface(rgba);SDL_DestroySurface(surface);SDL_SetRenderTarget(renderer,scratch);
        std::printf("GPU variant %d (flips/Gouraud, effects/occlusion, degenerate, absent metadata): %zu pixels exceed 2/255\n",test,errors);
        if(errors) return 13;
    }
    gpu.release();SDL_DestroyTexture(scratch);SDL_DestroyRenderer(renderer);gpu.destroy_device();SDL_Quit();
    if(bad) return 9;
#endif
    write_png(argv[2], hd ? presentation.frame(frame) : frame);
    if(!pack.empty()) std::printf("HD replacement pixels: %zu; recorded quads: %zu\n",assets.last_pixels(),frame.hd ? frame.hd->quads.size() : 0);
    if(bench) {
        auto start=std::chrono::steady_clock::now();
        for(int i=0;i<30;++i) {frame.px[0]^=1;presentation.frame(frame);}
        auto ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
        std::printf("HD full presentation benchmark: %.2f ms/changing frame (30 frames, excludes SDL upload)\n",ms/30);
        if(frame.hd) {
            start=std::chrono::steady_clock::now();
            for(int i=0;i<10;++i) {frame.px[0]^=1;++frame.hd->geometry;presentation.frame(frame);}
            ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
            std::printf("HD reprojection benchmark: %.2f ms/frame (10 forced geometry changes, excludes SDL upload)\n",ms/10);
        }
    }
    return 0;
}
