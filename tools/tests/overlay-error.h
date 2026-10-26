#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdlib>

// Straight-alpha storage can retain arbitrary RGB at alpha zero. Compare the
// displayed result over both extreme backgrounds, and alpha independently.
// The blend is affine in the background, so these bound every background RGB.
inline int overlay_error(uint32_t got,uint32_t want) {
    int ga=int(got>>24),wa=int(want>>24),error=std::abs(ga-wa);
    for(int sh=0;sh<24;sh+=8) {
        int gc=int((got>>sh)&255),wc=int((want>>sh)&255);
        for(int bg:{0,255}) {
            int g=(gc*ga+bg*(255-ga)+127)/255;
            int w=(wc*wa+bg*(255-wa)+127)/255;
            error=std::max(error,std::abs(g-w));
        }
    }
    return error;
}
