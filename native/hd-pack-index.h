// Immutable replacement-pack startup index. Replacement pixels remain lazy.
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

namespace sf3::pack_index {
inline constexpr const char* filename="materials.sf3idx";
inline constexpr uint64_t fnv_offset=14695981039346656037ull,fnv_prime=1099511628211ull;
inline constexpr uint64_t max_bytes=512ull*1024*1024,max_manifest=16ull*1024*1024;
inline constexpr uint32_t max_entries=100000;
struct Entry {
    int w=0,h=0,hw=0,hh=0;bool character=false;
    std::array<float,4> uv{0,0,1,1};
    std::string replacement_path;
    std::vector<uint32_t> original;
};
inline uint64_t hash(const void* data,size_t size,uint64_t value=fnv_offset) {
    auto bytes=static_cast<const unsigned char*>(data);
    for(size_t i=0;i<size;++i)value=(value^bytes[i])*fnv_prime;
    return value;
}
inline uint32_t u32(const unsigned char* p) {
    return uint32_t(p[0])|(uint32_t(p[1])<<8)|(uint32_t(p[2])<<16)|(uint32_t(p[3])<<24);
}
inline uint64_t u64(const unsigned char* p) {return u32(p)|(uint64_t(u32(p+4))<<32);}
inline bool safe_path(const std::string& path) {
    constexpr const char* suffix="/replacement.rgba";
    constexpr size_t suffix_size=17;
    if(path.size()<=suffix_size || path.size()>240 || path.compare(path.size()-suffix_size,suffix_size,suffix))return false;
    const size_t length=path.size()-suffix_size;
    auto alnum=[](unsigned char c){return (c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9');};
    if(!(alnum(path[0]) || path[0]=='_' || path[0]=='-') || path[length-1]=='.')return false;
    for(size_t i=0;i<length;++i)if(!(alnum(path[i]) || path[i]=='_' || path[i]=='-' || path[i]=='.'))return false;
    // A single relative directory; separators, drives, dot segments and ADS cannot occur.
    return true;
}
inline bool read(const std::filesystem::path& root,std::vector<Entry>& result) {
    // Only the index and its small invalidation marker are opened on this path.
    // A pack publisher must update manifest.json whenever immutable materials change.
    std::ifstream file(root/filename,std::ios::binary|std::ios::ate);
    if(!file)return false;
    const auto end=file.tellg();
    if(end<64 || uint64_t(end)>max_bytes)return false;
    file.seekg(0);unsigned char header[64];
    if(!file.read(reinterpret_cast<char*>(header),sizeof header))return false;
    if(std::memcmp(header,"SF3HDIX1",8) || u32(header+8)!=1 || u32(header+12)!=64
       || u64(header+16)!=uint64_t(end) || u32(header+44) || u64(header+56))return false;
    const uint32_t count=u32(header+40);
    const uint64_t manifest_size=u64(header+48);
    if(count>max_entries || uint64_t(count)*48>uint64_t(end)-64 || manifest_size>max_manifest)return false;
    std::ifstream manifest(root/"manifest.json",std::ios::binary|std::ios::ate);
    if(!manifest || manifest.tellg()!=std::streamoff(manifest_size))return false;
    manifest.seekg(0);uint64_t manifest_hash=fnv_offset,remaining=manifest_size;
    unsigned char buffer[16384];
    while(remaining) {
        const size_t n=size_t(std::min<uint64_t>(remaining,sizeof buffer));
        if(!manifest.read(reinterpret_cast<char*>(buffer),n))return false;
        manifest_hash=hash(buffer,n,manifest_hash);remaining-=n;
    }
    if(manifest_hash!=u64(header+24))return false;
    remaining=uint64_t(end)-64;uint64_t body_hash=fnv_offset;
    auto take=[&](void* target,size_t n) {
        if(n>remaining || !file.read(static_cast<char*>(target),n))return false;
        body_hash=hash(target,n,body_hash);remaining-=n;return true;
    };
    std::vector<Entry> entries;entries.reserve(count);
    for(uint32_t i=0;i<count;++i) {
        unsigned char record[48];if(!take(record,sizeof record))return false;
        const uint32_t w=u32(record),h=u32(record+4),hw=u32(record+8),hh=u32(record+12);
        const uint32_t flags=u32(record+16),length=u32(record+20),bytes=u32(record+24);
        if(w<1 || h<1 || w>1024 || h>1024 || hw<w || hh<h || hw>4096 || hh>4096
           || flags>1 || u32(record+28) || length<18 || length>240
           || bytes!=uint64_t(w)*h*4 || uint64_t(length)+bytes>remaining)return false;
        Entry e;e.w=int(w);e.h=int(h);e.hw=int(hw);e.hh=int(hh);e.character=bool(flags);
        for(size_t c=0;c<4;++c) {
            uint32_t bits=u32(record+32+c*4);std::memcpy(&e.uv[c],&bits,4);
            if(!std::isfinite(e.uv[c]) || e.uv[c]<0 || e.uv[c]>1)return false;
        }
        if(e.uv[2]<=e.uv[0] || e.uv[3]<=e.uv[1])return false;
        e.replacement_path.resize(length);
        if(!take(e.replacement_path.data(),length) || !safe_path(e.replacement_path))return false;
        e.original.resize(size_t(w)*h);
        if(!take(e.original.data(),bytes))return false;
        for(auto& pixel:e.original) {
            const auto* rgba=reinterpret_cast<const unsigned char*>(&pixel);
            pixel=(uint32_t(rgba[3])<<24)|(uint32_t(rgba[0])<<16)|(uint32_t(rgba[1])<<8)|rgba[2];
        }
        entries.push_back(std::move(e));
    }
    if(remaining || body_hash!=u64(header+32))return false;
    result=std::move(entries);return true;
}
}
