#include "hd-assets.h"
#include <chrono>
#include <cstdio>
#include <cstring>
#include <stdexcept>

namespace fs=std::filesystem;
using Bytes=std::vector<unsigned char>;
static void require(bool value,const char* what) {if(!value)throw std::runtime_error(what);}
static void put32(Bytes& b,size_t at,uint32_t n) {for(unsigned i=0;i<4;++i)b[at+i]=static_cast<unsigned char>(n>>(8*i));}
static void put64(Bytes& b,size_t at,uint64_t n) {for(unsigned i=0;i<8;++i)b[at+i]=static_cast<unsigned char>(n>>(8*i));}
static void write(const fs::path& path,const Bytes& b) {
    std::ofstream out(path,std::ios::binary);out.write(reinterpret_cast<const char*>(b.data()),b.size());
    require(bool(out),"write fixture");
}
static void text(const fs::path& path,const char* value) {std::ofstream f(path);f<<value;require(bool(f),"write descriptor");}
static void material(const fs::path& root,const char* name,bool character,uint32_t original,uint32_t replacement) {
    auto dir=root/name;fs::create_directories(dir);
    text(dir/"asset.txt",character?"SF3HDASSET1\n1 1\n4 4\n0.25 0 0.75 1\ncharacter\n":"SF3HDASSET1\n1 1\n4 4\n");
    auto rgba=[](uint32_t p){return Bytes{static_cast<unsigned char>(p>>16),static_cast<unsigned char>(p>>8),static_cast<unsigned char>(p),static_cast<unsigned char>(p>>24)};};
    write(dir/"original.rgba",rgba(original));Bytes enhanced;
    for(int i=0;i<16;++i) {auto p=rgba(replacement);enhanced.insert(enhanced.end(),p.begin(),p.end());}
    write(dir/"replacement.rgba",enhanced);
}
static Bytes index_bytes() {
    Bytes body;
    for(unsigned i=0;i<2;++i) {
        std::string path=std::string(i?"character":"world")+"/replacement.rgba";
        size_t at=body.size();body.resize(at+48);put32(body,at,1);put32(body,at+4,1);
        put32(body,at+8,4);put32(body,at+12,4);put32(body,at+16,i);put32(body,at+20,unsigned(path.size()));put32(body,at+24,4);
        const float uv[]={i?0.25f:0.f,0.f,i?0.75f:1.f,1.f};
        for(unsigned c=0;c<4;++c){uint32_t bits;std::memcpy(&bits,uv+c,4);put32(body,at+32+c*4,bits);}
        body.insert(body.end(),path.begin(),path.end());
        body.insert(body.end(),{static_cast<unsigned char>(i?240:248),0,0,255});
    }
    Bytes result(64);std::copy_n("SF3HDIX1",8,result.begin());put32(result,8,1);put32(result,12,64);
    put64(result,16,64+body.size());put64(result,24,sf3::pack_index::hash("{}",2));
    put64(result,32,sf3::pack_index::hash(body.data(),body.size()));put32(result,40,2);put64(result,48,2);
    result.insert(result.end(),body.begin(),body.end());return result;
}
static void rehash(Bytes& b) {put64(b,16,b.size());put64(b,32,sf3::pack_index::hash(b.data()+64,b.size()-64));}
static std::vector<uint32_t> render(sf3::HdAssets& assets,unsigned command,unsigned frame) {
    Frame source;source.w=source.h=2;source.px.assign(4,0x010203);source.hd=std::make_shared<HdScene>();
    source.hd->visible.assign(4,1);source.hd->effects.resize(4);source.hd->geometry=frame*8+command;
    auto texture=std::make_shared<HdTexture>();texture->w=texture->h=1;texture->rgba={frame?0xFFF00000:0xFFF80000};
    HdQuad q;const float xy[]={0,0,1,0,1,1,0,1};std::copy(xy,xy+8,q.xy);q.texture=texture;
    q.gpu_eligible=true;q.gpu_flags=command<<16;source.hd->quads.push_back(q);
    Frame output;output.w=output.h=8;output.px.assign(64,0x010203);assets.apply(source,output);return output.px;
}
int main(int argc,char** argv) {
    if(argc!=2)return 2;
    try {
        auto root=fs::path(argv[1])/"synthetic-pack-index";
        require(!fs::exists(root),"use a fresh external fixture directory");fs::create_directories(root);
        material(root,"world",false,0xFFF80000,0xFF00AA00);material(root,"character",true,0xFFF00000,0xFF0000CC);
        text(root/"manifest.json","{}");sf3::HdAssets directory;
        require(directory.load(root.string())==2 && !directory.loaded_from_index(),"directory fallback");
        std::vector<std::vector<uint32_t>> expected;
        for(unsigned frame=0;frame<2;++frame)for(unsigned command=0;command<3;++command)expected.push_back(render(directory,command,frame));
        const auto valid=index_bytes();write(root/sf3::pack_index::filename,valid);
        sf3::HdAssets indexed;
        require(indexed.load(root.string())==2 && indexed.loaded_from_index(),"valid index accepted");
        require(!indexed.cached_replacement_bytes(),"index does not eagerly load replacements");
        size_t at=0;
        for(unsigned frame=0;frame<2;++frame)for(unsigned command=0;command<3;++command)
            require(render(indexed,command,frame)==expected[at++],"index/directory exact rendering equality");
        require(indexed.cached_replacement_bytes()==128,"indexed matching lazily loads both materials");
        auto reject=[&](const Bytes& bytes,const char* what) {
            write(root/sf3::pack_index::filename,bytes);
            require(indexed.load(root.string())==2 && !indexed.loaded_from_index(),what);
            require(!indexed.cached_replacement_bytes(),"invalid index discards partial cached entries");
            size_t n=0;
            for(unsigned f=0;f<2;++f)for(unsigned c=0;c<3;++c)
                require(render(indexed,c,f)==expected[n++],"bad index fallback preserves rendering");
        };
        for(size_t size:{size_t(0),size_t(8),size_t(63),size_t(64),valid.size()-1})reject(Bytes(valid.begin(),valid.begin()+size),"truncated index fallback");
        auto b=valid;put32(b,8,2);reject(b,"wrong version fallback");
        b=valid;b.back()^=1;reject(b,"body corruption fallback");
        b=valid;put32(b,64,0xffffffff);rehash(b);reject(b,"dimension overflow fallback");
        b=valid;put32(b,80,2);rehash(b);reject(b,"unknown flag fallback");
        b=valid;put32(b,96,0x7fc00000);rehash(b);reject(b,"nonfinite UV fallback");
        b=valid;put32(b,40,0xffffffff);reject(b,"entry count bound");
        b=valid;put64(b,48,sf3::pack_index::max_manifest+1);reject(b,"manifest size bound");
        b=valid;b[112]='.';b[113]='.';rehash(b);reject(b,"path traversal fallback");
        b=valid;b.push_back(0);rehash(b);reject(b,"trailing bytes fallback");
        write(root/sf3::pack_index::filename,valid);text(root/"manifest.json","[]");
        require(indexed.load(root.string())==2 && !indexed.loaded_from_index(),"changed manifest fallback");
        text(root/"manifest.json","{}");
        std::vector<sf3::pack_index::Entry> unchanged(1);unchanged[0].w=77;
        b=valid;b.back()^=1;write(root/sf3::pack_index::filename,b);
        require(!sf3::pack_index::read(root,unchanged) && unchanged.size()==1 && unchanged[0].w==77,"parser does not expose partial results");
        for(const char* path:{"../replacement.rgba","./replacement.rgba","C:/replacement.rgba","safe/../replacement.rgba","safe\\replacement.rgba","safe:/replacement.rgba","safe./replacement.rgba"})
            require(!sf3::pack_index::safe_path(path),"unsafe path rejected");
        require(sf3::pack_index::safe_path("a-01_23.4/replacement.rgba"),"safe ASCII path accepted");
        write(root/sf3::pack_index::filename,valid);text(root/"character"/"replacement.rgba","bad");
        require(indexed.load(root.string())==2 && indexed.loaded_from_index() && !indexed.cached_replacement_bytes(),"payload remains lazy");
        const auto missing=render(indexed,0,1);
        require(std::all_of(missing.begin(),missing.end(),[](uint32_t pixel){return pixel==0x010203;}) && !indexed.cached_replacement_bytes(),"damaged lazy payload falls back to original");
        fs::remove(root/"character"/"replacement.rgba");
        require(indexed.load(root.string())==2 && indexed.loaded_from_index(),"missing payload opens only when matched");
        require(render(indexed,0,1)==missing && !indexed.cached_replacement_bytes(),"missing lazy payload falls back safely");
        fs::remove(root/"manifest.json");
        require(indexed.load(root.string())==1 && !indexed.loaded_from_index(),"legacy marker absence uses directory validation");
        std::puts("PASS: indexed/directory pixel equality, lazy replacement cache, corrupt/truncated/stale index fallback, strict bounds and paths, missing replacement fallback");return 0;
    } catch(const std::exception& error) {std::fprintf(stderr,"FAIL: %s\n",error.what());return 1;}
}
