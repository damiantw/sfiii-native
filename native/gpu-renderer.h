// Original-texture GPU geometry rendering. No replacement-art pack.
#pragma once
#include "video.h"
#include <SDL3/SDL.h>
#include <SDL3/SDL_gpu.h>
#include <string>
namespace sf3 {
class GpuRenderer {
    SDL_GPUDevice* device_=nullptr;
    SDL_Renderer* renderer_=nullptr;
    SDL_GPUBuffer *scene_=nullptr,*textures_=nullptr;
    SDL_GPUShader* shader_=nullptr;
    SDL_GPURenderState* state_=nullptr;
    SDL_Texture *white_=nullptr,*output_=nullptr,*filtered_=nullptr;
    bool aa_=false,filtered_valid_=false;
    int width_=0,height_=0;
    std::vector<uint32_t> last_scene_,last_textures_;
    uint64_t submissions_=0,cache_hits_=0;
    bool upload(SDL_GPUBuffer*,const std::vector<uint32_t>&);
public:
    SDL_Renderer* create_renderer(SDL_Window*);
    bool initialize(SDL_Renderer*,const std::string& shader_dir);
    SDL_Texture* render(const Frame&,int scale);
    void antialiasing(bool enabled) {if(aa_!=enabled){aa_=enabled;filtered_valid_=false;last_scene_.clear();}}
    bool antialiasing()const{return aa_;}
    bool capture(Frame&);
    bool wait();
    uint64_t submissions()const{return submissions_;}
    uint64_t cache_hits()const{return cache_hits_;}
    bool ready()const{return state_!=nullptr;}
    const char* backend()const{return device_?SDL_GetGPUDeviceDriver(device_):"none";}
    const char* adapter()const{return device_?SDL_GetStringProperty(SDL_GetGPUDeviceProperties(device_),SDL_PROP_GPU_DEVICE_NAME_STRING,"unknown"):"none";}
    void release();
    void destroy_device();
};
}
