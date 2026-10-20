// Synthetic SH-2 peripheral tests; no disc or game-generated inputs.
#include "saturn.h"
#include "test.h"
#include <array>
#include <climits>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <chrono>

TEST(cd_track_types_follow_track_boundaries_in_shared_and_split_files) {
    namespace fs=std::filesystem;
    const auto parent=fs::temp_directory_path();
    const auto dir=parent/("sf3-cd-track-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    fs::create_directory(dir);
    auto track=[&](const char* name,int first,int count) {
        std::ofstream out(dir/name,std::ios::binary);
        for(int n=first;n<first+count;++n) {std::array<char,2352> sector{};sector.fill(char(n));out.write(sector.data(),sector.size());}
    };
    track("shared.bin",1,6);track("data.bin",1,2);track("audio.bin",3,2);track("last.bin",5,2);
    for(bool split : {false,true}) for(bool last_data : {false,true}) {
        std::ofstream cue(dir/"synthetic.cue");
        if(split)cue<<"FILE \"data.bin\" BINARY\n TRACK 01 MODE1/2352\n INDEX 01 00:00:00\nFILE \"audio.bin\" BINARY\n TRACK 02 AUDIO\n INDEX 01 00:00:00\n";
        else cue<<"FILE \"shared.bin\" BINARY\n TRACK 01 MODE1/2352\n INDEX 01 00:00:00\n TRACK 02 AUDIO\n INDEX 01 00:00:02\n";
        if(last_data) {
            if(split)cue<<"FILE \"last.bin\" BINARY\n TRACK 03 MODE1/2352\n INDEX 01 00:00:00\n";
            else cue<<" TRACK 03 MODE1/2352\n INDEX 01 00:00:04\n";
        }
        cue.close();CHECK_EQ(cdrom_open((dir/"synthetic.cue").string()),true);
        CHECK_EQ(cdrom_is_audio(149),false);
        for(uint32_t fad=150;fad<(split&&!last_data ? 154u : 156u);++fad) {
            const bool audio=fad>=152 && (!last_data || fad<154);
            CHECK_EQ(cdrom_is_audio(fad),audio);
            std::array<uint8_t,2352> sector{};CHECK_EQ(cdrom_read(fad,sector.data()),true);CHECK_EQ(sector.front(),fad-149);
        }
        CHECK_EQ(cdrom_is_audio(split&&!last_data ? 154 : 156),false);
    }
    // Closing a synthetic image releases Windows handles before fixture cleanup.
    CHECK_EQ(cdrom_open((dir/"missing.cue").string()),false);
    if(dir.parent_path()!=parent)throw std::runtime_error("Unexpected CD fixture cleanup path");fs::remove_all(dir);
}

TEST(division_handles_signs_boundaries_zero_and_wide_overflow_on_both_cpus) {
    const int32_t divisors[]={INT32_MIN,-32769,-17,-1,0,1,7,32767,INT32_MAX};
    const int64_t narrow[]={INT32_MIN,-65537,-1,0,1,65537,INT32_MAX};
    const int64_t wide[]={INT64_MIN,INT64_MIN+1,int64_t(INT32_MIN)*7-3,-1,0,1,int64_t(INT32_MAX)*7+3,INT64_MAX};
    unsigned cases=0;
    for(int cpu=0;cpu<2;++cpu) for(bool is_wide : {false,true}) {
        const auto* values=is_wide ? wide : narrow;
        const size_t count=is_wide ? std::size(wide) : std::size(narrow);
        for(size_t i=0;i<count;++i) for(int32_t divisor : divisors) {
            SH2Context c{};c.cpu=cpu;onchip_reset(cpu);
            const uint32_t base=cpu ? 0xFFFFFF20 : 0xFFFFFF00; // Exercise the DIVU register mirror too.
            onchip_write(c,base,uint32_t(divisor),4);
            if(is_wide) {
                onchip_write(c,base+16,uint32_t(uint64_t(values[i])>>32),4);
                onchip_write(c,base+20,uint32_t(values[i]),4);
            } else onchip_write(c,base+4,uint32_t(values[i]),4);
            const __int128 quotient=divisor ? __int128(values[i])/divisor : 0;
            const bool overflow=!divisor || quotient<INT32_MIN || quotient>INT32_MAX;
            CHECK_EQ(onchip_read(c,base+8,4)&1,unsigned(overflow));
            // Overflow result contents are not used as an arithmetic oracle.
            if(!overflow) {
                const uint32_t q=uint32_t(quotient),r=uint32_t(__int128(values[i])%divisor);
                CHECK_EQ(onchip_read(c,base+28,4),q);
                CHECK_EQ(onchip_read(c,base+24,4),r);
                CHECK_EQ(onchip_read(c,0xFFFFFF1C,4),q);
                CHECK_EQ(onchip_read(c,0xFFFFFF18,4),r);
            }
            ++cases;
        }
    }
    std::printf("  %u signed division boundary cases\n",cases);
}

TEST(dmac_address_modes_widths_channels_and_enable_gates_preserve_memory) {
    unsigned cases=0;
    for(int cpu=0;cpu<2;++cpu) for(int channel=0;channel<2;++channel)
    for(int size=0;size<3;++size) for(int source_mode=0;source_mode<3;++source_mode)
    for(int dest_mode=0;dest_mode<3;++dest_mode) {
        SH2Context c{};c.cpu=cpu;onchip_reset(cpu);
        const int width=1<<size, count=7;
        const int ss=source_mode==1 ? width : source_mode==2 ? -width : 0;
        const int ds=dest_mode==1 ? width : dest_mode==2 ? -width : 0;
        constexpr uint32_t source=0x06090000,dest=0x06091000;
        std::array<uint8_t,256> expected;
        expected.fill(0xCC);
        for(unsigned i=0;i<256;++i) {st8(source+i,(i*17+3)&255);st8(dest+i,0xCC);}
        const int start_s=source_mode==2 ? 128 : 64,start_d=dest_mode==2 ? 128 : 64;
        for(int i=0;i<count;++i) for(int b=0;b<width;++b)
            expected[start_d+i*ds+b]=uint8_t(((start_s+i*ss+b)*17+3)&255);
        const uint32_t regs=0xFFFFFF80+channel*16;
        onchip_write(c,regs,source+start_s,4);onchip_write(c,regs+4,dest+start_d,4);
        onchip_write(c,regs+8,count,4);
        const uint32_t control=0x201|(size<<10)|(source_mode<<12)|(dest_mode<<14);
        onchip_write(c,regs+12,control,4);
        for(unsigned i=0;i<256;++i) CHECK_EQ(ld8(dest+i),0xCC); // Global enable still off.
        onchip_write(c,0xFFFFFFB0,1,4);
        for(unsigned i=0;i<256;++i) CHECK_EQ(ld8(dest+i),expected[i]);
        CHECK_EQ(onchip_read(c,regs,4),uint32_t(source+start_s+count*ss));
        CHECK_EQ(onchip_read(c,regs+4,4),uint32_t(dest+start_d+count*ds));
        CHECK_EQ(onchip_read(c,regs+8,4),0);
        CHECK_EQ(onchip_read(c,regs+12,4)&2,2);
        st8(source+start_s,0xFF);
        onchip_write(c,0xFFFFFFB0,1,4); // TE must prevent an accidental second transfer.
        for(unsigned i=0;i<256;++i) CHECK_EQ(ld8(dest+i),expected[i]);
        ++cases;
    }
    std::printf("  %u DMA mode/width/channel cases\n",cases);
}
