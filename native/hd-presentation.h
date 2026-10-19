// Optional presentation filter. Never writes Saturn memory or game state.
#pragma once
#include "video.h"
#include "hd-assets.h"
#include <algorithm>

namespace sf3 {
class HdPresentation {
    Frame input_, stages_[2], output_;
    unsigned updates_ = 0;
    const HdAssets* assets_=nullptr;
    static uint32_t blend(uint32_t a, uint32_t b, unsigned weight) {
        unsigned other = 256-weight;
        return ((((a&0xFF00FF)*other+(b&0xFF00FF)*weight)>>8)&0xFF00FF)
             | ((((a&0x00FF00)*other+(b&0x00FF00)*weight)>>8)&0x00FF00);
    }
    static void expand(const Frame& from, Frame& to) {
        to.w=from.w*2; to.h=from.h*2; to.px.resize(to.w*to.h);
        for (int y=0; y<from.h; ++y) for (int x=0; x<from.w; ++x) {
            auto get=[&](int xx,int yy) { return from.px[std::clamp(yy,0,from.h-1)*from.w+std::clamp(xx,0,from.w-1)]; };
            const uint32_t center=get(x,y), horizontal[]={get(x-1,y),get(x+1,y)}, vertical[]={get(x,y-1),get(x,y+1)};
            for (int yy=0; yy<2; ++yy) for (int xx=0; xx<2; ++xx) {
                uint32_t color=center;
                // Continue a shared contour into a corner only when both opposite
                // neighbors disagree. Flat areas and isolated details stay intact.
                if (horizontal[xx]==vertical[yy] && horizontal[xx]!=horizontal[1-xx]
                    && vertical[yy]!=vertical[1-yy]) color=horizontal[xx];
                to.px[(y*2+yy)*to.w+x*2+xx]=color;
            }
        }
    }
public:
    void assets(const HdAssets* value) { assets_=value;output_.px.clear(); }
    const Frame& frame(const Frame& source) {
        bool same_scene=source.hd ? input_.hd && input_.hd->fingerprint==source.hd->fingerprint : !input_.hd;
        if (same_scene && source.w==input_.w && source.h==input_.h && source.px==input_.px && !output_.px.empty()) return output_;
        if (source.w<=0 || source.h<=0 || source.px.size()!=size_t(source.w)*source.h) return source;
        input_=source;
        const Frame* working=&input_;
        for (int pass=0; !assets_ && pass<2 && working->w*2<=1440 && working->h*2<=1080; ++pass) {
            expand(*working,stages_[pass]); working=&stages_[pass];
        }
        output_.w=1440; output_.h=1080; output_.px.resize(1440*1080);
        struct Sample { int at, next; unsigned weight; };
        Sample columns[1440];
        auto sample=[](int i,int count,int length) {
            // Center-aligned fixed-point coordinates, clamped at the image border.
            int pos=std::clamp(int((int64_t(2*i+1)*length*128)/count)-128,0,(length-1)*256);
            return Sample{pos/256,std::min(pos/256+1,length-1),unsigned(pos&255)};
        };
        for (int x=0;x<1440;++x) columns[x]=sample(x,1440,working->w);
        for (int y=0;y<1080;++y) {
            auto sy=sample(y,1080,working->h);
            const auto* top=working->px.data()+sy.at*working->w;
            const auto* bottom=working->px.data()+sy.next*working->w;
            for (int x=0;x<1440;++x) {
                auto sx=columns[x];
                output_.px[y*1440+x]=blend(blend(top[sx.at],top[sx.next],sx.weight),
                                           blend(bottom[sx.at],bottom[sx.next],sx.weight),sy.weight);
            }
        }
        if(assets_) assets_->apply(input_,output_);
        ++updates_;
        return output_;
    }
    unsigned updates() const { return updates_; }
};
}
