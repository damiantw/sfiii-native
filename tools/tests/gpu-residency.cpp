#include "gpu-residency.h"
#include <cstdio>
#include <cstdlib>
#include <limits>
static void check(bool value){if(!value)std::exit(1);}
int main() {
    using V=std::vector<size_t>;
    auto words=[](size_t index){return index<4?size_t(4):size_t(0);};
    check(sf3::retain_gpu_materials(V{1},V{0,1},8,words)==V({0,1}));
    check(sf3::retain_gpu_materials(V{2},V{0,1},8,words)==V({0,2}));
    check(sf3::retain_gpu_materials(V{2,3},V{0,1},8,words)==V({2,3}));
    check(sf3::retain_gpu_materials(V{},V{0,1},8,words)==V({0,1}));
    check(sf3::retain_gpu_materials(V{0},V{0,4},8,words)==V({0}));
    check(sf3::retain_gpu_materials(V{0,1,2},V{3},8,words)==V({0,1,2}));
    check(sf3::retain_gpu_materials(V{0},V{1},0,words)==V({0}));
    auto huge=[](size_t){return std::numeric_limits<size_t>::max();};
    check(sf3::retain_gpu_materials(V{0,1},V{2},8,huge)==V({0,1}));
    std::puts("PASS: animation retention, exact/full budget, eviction, empty frame, missing pixels, oversized frame and overflow");
}
