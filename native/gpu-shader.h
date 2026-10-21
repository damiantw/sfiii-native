// SDL fragment shader formats; Metal resource slots follow SDL's buffer table.
#pragma once
#include <SDL3/SDL_gpu.h>
#include <filesystem>
#include <fstream>
#include <vector>
#include <iterator>
#include <string>
namespace sf3 {
struct FragmentShader {
    std::vector<uint8_t> bytes;
    SDL_GPUShaderFormat format=SDL_GPU_SHADERFORMAT_INVALID;
    const char* entry="main";
    bool read(SDL_GPUDevice* device,const std::string& directory,const char* name) {
        const auto available=SDL_GetGPUShaderFormats(device);
        const char* extension=nullptr;
        if(available&SDL_GPU_SHADERFORMAT_SPIRV) {format=SDL_GPU_SHADERFORMAT_SPIRV;extension=".spv";}
        else if(available&SDL_GPU_SHADERFORMAT_DXIL) {format=SDL_GPU_SHADERFORMAT_DXIL;extension=".dxil";}
        else if(available&SDL_GPU_SHADERFORMAT_MSL) {format=SDL_GPU_SHADERFORMAT_MSL;extension=".msl";entry="fragmentMain";}
        if(!extension)return SDL_SetError("No supported fragment shader format");
        std::ifstream file(std::filesystem::path(directory)/(std::string(name)+extension),std::ios::binary);
        bytes.assign(std::istreambuf_iterator<char>(file),{});
        if(bytes.empty())return SDL_SetError("Shader missing in %s",directory.c_str());
        if(format==SDL_GPU_SHADERFORMAT_MSL)bytes.push_back(0);
        return true;
    }
};
}
