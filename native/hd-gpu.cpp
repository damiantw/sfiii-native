#include "hd-gpu.h"
#include "gpu-shader.h"
#include <cstring>

namespace sf3 {
static constexpr uint32_t scene_bytes=8*1024*1024;
SDL_Renderer* HdGpu::create_renderer(SDL_Window* window) {
    const char* requested=std::getenv("SF3_GPU_BACKEND");
    for(const char* backend:{"vulkan","direct3d12","metal"}) {
        if(requested && *requested && std::strcmp(requested,backend)) continue;
        auto props=SDL_CreateProperties();
        SDL_SetStringProperty(props,SDL_PROP_GPU_DEVICE_CREATE_NAME_STRING,backend);
        SDL_SetBooleanProperty(props,SDL_PROP_GPU_DEVICE_CREATE_SHADERS_SPIRV_BOOLEAN,true);
        SDL_SetBooleanProperty(props,SDL_PROP_GPU_DEVICE_CREATE_SHADERS_MSL_BOOLEAN,true);
        SDL_SetBooleanProperty(props,SDL_PROP_GPU_DEVICE_CREATE_SHADERS_DXIL_BOOLEAN,true);
        SDL_SetBooleanProperty(props,SDL_PROP_GPU_DEVICE_CREATE_DEBUGMODE_BOOLEAN,std::getenv("SF3_GPU_DEBUG")!=nullptr);
        SDL_SetBooleanProperty(props,SDL_PROP_GPU_DEVICE_CREATE_PREFERLOWPOWER_BOOLEAN,std::getenv("SF3_GPU_LOW_POWER")!=nullptr);
        SDL_SetBooleanProperty(props,SDL_PROP_GPU_DEVICE_CREATE_VULKAN_REQUIRE_HARDWARE_ACCELERATION_BOOLEAN,std::getenv("SF3_GPU_ALLOW_SOFTWARE")==nullptr);
        SDL_SetBooleanProperty(props,SDL_PROP_GPU_DEVICE_CREATE_D3D12_ALLOW_FEWER_RESOURCE_SLOTS_BOOLEAN,true);
        // The presentation shader does not use these optional Vulkan features.
        SDL_SetBooleanProperty(props,SDL_PROP_GPU_DEVICE_CREATE_FEATURE_CLIP_DISTANCE_BOOLEAN,false);
        SDL_SetBooleanProperty(props,SDL_PROP_GPU_DEVICE_CREATE_FEATURE_DEPTH_CLAMPING_BOOLEAN,false);
        SDL_SetBooleanProperty(props,SDL_PROP_GPU_DEVICE_CREATE_FEATURE_INDIRECT_DRAW_FIRST_INSTANCE_BOOLEAN,false);
        SDL_SetBooleanProperty(props,SDL_PROP_GPU_DEVICE_CREATE_FEATURE_ANISOTROPY_BOOLEAN,false);
        device_=SDL_CreateGPUDeviceWithProperties(props);SDL_DestroyProperties(props);
        if(!device_) continue;
        auto* renderer=SDL_CreateGPURenderer(device_,window);
        if(renderer) return renderer;
        SDL_DestroyGPUDevice(device_);device_=nullptr;
    }
    return nullptr;
}
bool HdGpu::upload(SDL_GPUBuffer* buffer,const std::vector<uint32_t>& words) {
    auto size=uint32_t(words.size()*4);
    SDL_GPUTransferBufferCreateInfo ti{};ti.usage=SDL_GPU_TRANSFERBUFFERUSAGE_UPLOAD;ti.size=size;
    auto* transfer=SDL_CreateGPUTransferBuffer(device_,&ti);
    if(!transfer) return false;
    void* mapped=SDL_MapGPUTransferBuffer(device_,transfer,false);
    if(!mapped) {SDL_ReleaseGPUTransferBuffer(device_,transfer);return false;}
    std::memcpy(mapped,words.data(),size);SDL_UnmapGPUTransferBuffer(device_,transfer);
    auto* command=SDL_AcquireGPUCommandBuffer(device_);
    if(!command) {SDL_ReleaseGPUTransferBuffer(device_,transfer);return false;}
    auto* copy=SDL_BeginGPUCopyPass(command);
    SDL_GPUTransferBufferLocation source{transfer,0};SDL_GPUBufferRegion dest{buffer,0,size};
    SDL_UploadToGPUBuffer(copy,&source,&dest,true);SDL_EndGPUCopyPass(copy);
    bool ok=SDL_SubmitGPUCommandBuffer(command);SDL_ReleaseGPUTransferBuffer(device_,transfer);
    return ok;
}
bool HdGpu::initialize(SDL_Renderer* renderer,const HdAssets& assets,const std::string& dir) {
    renderer_=renderer;
    if(!device_ || SDL_GetGPURendererDevice(renderer)!=device_) return SDL_SetError("GPU shader renderer not available");
    if(assets.assets_.empty()) return SDL_SetError("No HD asset pack loaded");
    FragmentShader code;if(!code.read(device_,dir,"hd-assets"))return false;
    SDL_GPUShaderCreateInfo si{};si.code=code.bytes.data();si.code_size=code.bytes.size();si.entrypoint=code.entry;
    si.format=code.format;si.stage=SDL_GPU_SHADERSTAGE_FRAGMENT;si.num_samplers=1;si.num_storage_buffers=2;
    shader_=SDL_CreateGPUShader(device_,&si);if(!shader_) return false;
    std::vector<uint32_t> art;
    for(const auto& asset:assets.assets_) {offsets_.push_back(uint32_t(art.size()));art.insert(art.end(),asset.replacement.px.begin(),asset.replacement.px.end());}
    if(art.size()>UINT32_MAX/4) return SDL_SetError("HD pack exceeds GPU buffer limit");
    SDL_GPUBufferCreateInfo bi{};bi.usage=SDL_GPU_BUFFERUSAGE_GRAPHICS_STORAGE_READ;bi.size=uint32_t(art.size()*4);
    art_=SDL_CreateGPUBuffer(device_,&bi);bi.size=scene_bytes;scene_=SDL_CreateGPUBuffer(device_,&bi);
    if(!art_ || !scene_ || !upload(art_,art)) return false;
    SDL_GPUBuffer* buffers[]{scene_,art_};SDL_GPURenderStateCreateInfo ri{};
    ri.fragment_shader=shader_;ri.num_storage_buffers=2;ri.storage_buffers=buffers;
    state_=SDL_CreateGPURenderState(renderer,&ri);if(!state_) return false;
    white_=SDL_CreateTexture(renderer,SDL_PIXELFORMAT_ARGB8888,SDL_TEXTUREACCESS_STATIC,1,1);
    output_=SDL_CreateTexture(renderer,SDL_PIXELFORMAT_ARGB8888,SDL_TEXTUREACCESS_TARGET,1440,1080);
    if(!white_ || !output_) return false;
    uint32_t white=0xFFFFFFFF;SDL_UpdateTexture(white_,nullptr,&white,4);
    SDL_SetTextureBlendMode(white_,SDL_BLENDMODE_NONE);SDL_SetTextureBlendMode(output_,SDL_BLENDMODE_BLEND);
    SDL_SetTextureScaleMode(output_,SDL_SCALEMODE_LINEAR);
    ready_=true;return true;
}
SDL_Texture* HdGpu::render(const Frame& frame,const HdAssets& assets) {
    if(!ready_) return nullptr;
    auto* old_target=SDL_GetRenderTarget(renderer_);
    if(!SDL_FlushRenderer(renderer_)) return nullptr;
    size_t pixels=size_t(frame.w)*frame.h;
    bool valid=frame.hd && frame.hd->visible.size()==pixels;
    size_t count=valid?frame.hd->quads.size():0,quad_offset=4+pixels*8;
    if((quad_offset+count*32)*4>scene_bytes) {SDL_SetError("HD scene exceeds GPU buffer limit");return nullptr;}
    std::vector<uint32_t> data(quad_offset+count*32);
    data[0]=frame.w;data[1]=frame.h;data[2]=uint32_t(quad_offset);data[3]=uint32_t(count);
    if(valid) {
        for(size_t i=0;i<pixels;++i) {
            auto at=4+i*8;data[at]=frame.hd->visible[i];
            if(frame.hd->effects.size()==pixels) {const auto& e=frame.hd->effects[i];data[at+1]=e.second;
                for(int c=0;c<3;++c) data[at+2+c]=uint32_t(int32_t(e.offset[c]));
                data[at+5]=e.ratio;data[at+6]=e.flags;}
        }
        std::unordered_map<const HdTexture*,const HdAssets::Asset*> matches;
        for(size_t i=0;i<count;++i) {
            auto at=quad_offset+i*32;const auto& q=frame.hd->quads[i];data[at+22]=UINT32_MAX;
            if(!q.texture) continue;
            auto [it,inserted]=matches.emplace(q.texture.get(),nullptr);if(inserted) it->second=assets.match(*q.texture);
            auto* a=it->second;if(!a) continue;
            std::memcpy(data.data()+at,q.xy,32);std::memcpy(data.data()+at+8,q.shade,48);
            data[at+20]=q.hflip;data[at+21]=q.vflip;
            data[at+22]=offsets_[a-assets.assets_.data()];data[at+23]=a->replacement.w;data[at+24]=a->replacement.h;
            std::memcpy(data.data()+at+25,a->uv,16);
        }
    }
    if(!upload(scene_,data)) return nullptr;
    if(!SDL_SetRenderTarget(renderer_,output_)) return nullptr;
    SDL_SetRenderDrawColor(renderer_,0,0,0,0);SDL_RenderClear(renderer_);
    SDL_SetGPURenderState(renderer_,state_);
    bool ok=SDL_RenderTexture(renderer_,white_,nullptr,nullptr);
    SDL_SetGPURenderState(renderer_,nullptr);SDL_SetRenderTarget(renderer_,old_target);
    return ok?output_:nullptr;
}
void HdGpu::release() {
    ready_=false;
    if(renderer_) SDL_FlushRenderer(renderer_);
    if(state_) SDL_DestroyGPURenderState(state_);
    if(white_) SDL_DestroyTexture(white_);if(output_) SDL_DestroyTexture(output_);
    if(device_) {if(scene_) SDL_ReleaseGPUBuffer(device_,scene_);if(art_) SDL_ReleaseGPUBuffer(device_,art_);if(shader_) SDL_ReleaseGPUShader(device_,shader_);}
    state_=nullptr;white_=output_=nullptr;scene_=art_=nullptr;shader_=nullptr;offsets_.clear();
}
void HdGpu::destroy_device() {if(device_) SDL_DestroyGPUDevice(device_);device_=nullptr;}
}
