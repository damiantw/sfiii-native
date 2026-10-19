#include "hd-presentation.h"
#include <cstdio>
#include <chrono>

int main() {
    sf3::HdPresentation hd;
    Frame f; f.w=320; f.h=240; f.px.assign(320*240,0x123456);
    auto original=f.px;
    const auto& flat=hd.frame(f);
    if(flat.w!=1440 || flat.h!=1080 || flat.px.size()!=1440*1080) return 1;
    for(auto p:flat.px) if(p!=0x123456) return 2;
    hd.frame(f); if(hd.updates()!=1 || f.px!=original) return 3;
    // A diagonal contour, an isolated white detail, and extreme image borders.
    for(int y=0;y<f.h;++y) for(int x=0;x<f.w;++x) f.px[y*f.w+x]=x<y ? 0xFFFFFF : 0;
    f.px[160+120*f.w]=0xFF0000;
    auto before=f.px;
    const auto& contour=hd.frame(f);
    if(contour.px.front()!=0 || contour.px.back()!=0 || f.px!=before || hd.updates()!=2) return 4;
    unsigned blends=0;
    for(auto p:contour.px) blends+=p!=0 && p!=0xFFFFFF && p!=0xFF0000;
    if(!blends) return 5;
    // 480-line sources must also stay bounded and preserve uniform colours.
    f.w=640;f.h=480;f.px.assign(f.w*f.h,0xABCDEF);
    for(auto p:hd.frame(f).px) if(p!=0xABCDEF) return 6;
    f.w=320;f.h=240;f.px.resize(f.w*f.h);
    auto start=std::chrono::steady_clock::now();
    for(int i=0;i<60;++i) { f.px[0]=i; hd.frame(f); }
    auto ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
    std::printf("PASS: 1080p dimensions, flat colours, borders, contours, source immutability, caching, 480-line input; %.2f ms/changing frame\n",ms/60);
}
