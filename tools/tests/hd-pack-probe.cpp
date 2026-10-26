// Read-only startup benchmark; do not render or modify local artwork packs.
#include "hd-assets.h"
#include <chrono>
#include <cstdio>

int main(int argc,char** argv) {
    if(argc!=2)return 2;
    auto start=std::chrono::steady_clock::now();
    sf3::HdAssets assets;auto count=assets.load(argv[1]);
    double milliseconds=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
    std::printf("{\"materials\":%zu,\"milliseconds\":%.3f,\"replacement_bytes_loaded\":%zu,\"indexed\":%s}\n",
        count,milliseconds,assets.cached_replacement_bytes(),assets.loaded_from_index()?"true":"false");
    return count?0:1;
}
