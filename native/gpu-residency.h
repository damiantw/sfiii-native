// Bounded, deterministic working set for immutable replacement artwork.
#pragma once
#include <algorithm>
#include <cstddef>
#include <vector>
namespace sf3 {
template<class Size>
std::vector<size_t> retain_gpu_materials(const std::vector<size_t>& needed,
                                       const std::vector<size_t>& resident,size_t limit,Size size) {
    std::vector<size_t> working=needed;
    size_t words=0;
    for(auto index:needed) {
        size_t count=size(index);
        // A visible frame can exceed the soft limit; do not wrap arithmetic or
        // retain optional older materials in that case.
        if(count>limit || words>limit-count){words=limit;break;}
        words+=count;
    }
    for(auto index:resident) {
        if(std::binary_search(needed.begin(),needed.end(),index))continue;
        size_t count=size(index);
        if(count && count<=limit-words){working.push_back(index);words+=count;}
    }
    std::sort(working.begin(),working.end());
    return working;
}
}
