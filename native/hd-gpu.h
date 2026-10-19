// GPU presentation only. Original Saturn memory and framebuffer remain untouched.
#pragma once
#include "hd-assets.h"
#include <SDL3/SDL.h>
#include <SDL3/SDL_gpu.h>

namespace sf3 {
class HdGpu {
    SDL_GPUDevice* device_=nullptr;
    SDL_Renderer* renderer_=nullptr;
    SDL_GPUBuffer *scene_=nullptr,*art_=nullptr;
    SDL_GPUShader* shader_=nullptr;
    SDL_GPURenderState* state_=nullptr;
    SDL_Texture *white_=nullptr,*output_=nullptr;
    std::vector<uint32_t> offsets_;
    bool ready_=false;
    bool upload(SDL_GPUBuffer*,const std::vector<uint32_t>&);
public:
    // Backend can be explicitly selected with SF3_GPU_BACKEND=vulkan/direct3d12.
    SDL_Renderer* create_renderer(SDL_Window* window);
    bool initialize(SDL_Renderer*,const HdAssets&,const std::string& shader_dir);
    SDL_Texture* render(const Frame&,const HdAssets&);
    bool ready() const {return ready_;}
    const char* backend() const {return device_?SDL_GetGPUDeviceDriver(device_):"none";}
    const char* adapter() const {return device_?SDL_GetStringProperty(SDL_GetGPUDeviceProperties(device_),SDL_PROP_GPU_DEVICE_NAME_STRING,"unknown"):"none";}
    // Call before destroying the renderer. Device is owned by this class.
    void release();
    void destroy_device();
};
}
