#include "saturn.h"
#include "test.h"
#include <filesystem>
#include <chrono>
#include <fstream>
#include <cstring>

namespace {
struct BackupFixture {
    std::filesystem::path folder;
    std::string previous_save=g_cfg.save,previous_out=g_cfg.out;
    static constexpr uint32_t dir=0x06018000,data=0x06020000,out=0x06040000;
    BackupFixture() {
        folder=std::filesystem::temp_directory_path()/("sf3-backup-boundary-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        std::filesystem::create_directory(folder);g_cfg.save=(folder/"backup.bin").string();g_cfg.out=".";
        reload();
    }
    ~BackupFixture() {
        std::filesystem::remove(folder/"backup.bin");std::filesystem::remove(folder/"backup.bin.cartridge");
        std::filesystem::remove(folder);g_cfg.save=previous_save;g_cfg.out=previous_out;
    }
    void reload() {uint8_t ip[256]{};bios_select_save(ip);}
    uint32_t call(unsigned fn,unsigned device,uint32_t r5=dir,uint32_t r6=out,uint32_t r7=0) {
        auto& c=g_master;c.r[4]=device;c.r[5]=r5;c.r[6]=r6;c.r[7]=r7;
        CHECK_EQ(bios_call(c,0x3000+fn*4),true);return c.r[0];
    }
    void prepare(const char* name,uint32_t size,uint8_t seed) {
        for(unsigned i=0;i<36;++i) st8(dir+i,0);
        for(unsigned i=0;i<std::strlen(name);++i) st8(dir+i,name[i]);
        st32(dir+28,size);
        for(unsigned i=0;i<size;++i) st8(data+i,uint8_t(seed+i));
    }
};
}

TEST(full_internal_memory_rejects_new_and_growing_saves_without_losing_old_data) {
    BackupFixture f;
    f.prepare("A",12904,3);CHECK_EQ(f.call(4,0,f.dir,f.data),0);
    f.prepare("B",12904,5);CHECK_EQ(f.call(4,0,f.dir,f.data),0);
    CHECK_EQ(f.call(3,0,12904,f.out),0);CHECK_EQ(ld32(f.out+20),0);
    f.prepare("C",12904,7);CHECK_EQ(f.call(4,0,f.dir,f.data),4);
    f.prepare("A",20000,9);CHECK_EQ(f.call(4,0,f.dir,f.data),4);
    f.reload();f.prepare("A",0,0);CHECK_EQ(f.call(5,0),0);
    for(unsigned i=0;i<12904;++i) CHECK_EQ(ld8(f.out+i),uint8_t(3+i));
}

TEST(backup_directory_limits_prefixes_and_invalid_devices_do_not_overwrite_buffers) {
    BackupFixture f;
    for(const char* name : {"A","AB","AC"}) {f.prepare(name,1,8);CHECK_EQ(f.call(4,0,f.dir,f.data),0);}
    for(unsigned i=0;i<128;++i) st8(f.out+i,0xCD);
    st8(f.dir,0);CHECK_EQ(f.call(7,0,f.dir,1,f.out),uint32_t(-3));
    for(unsigned i=36;i<128;++i) CHECK_EQ(ld8(f.out+i),0xCD);
    CHECK_EQ(f.call(7,0,f.dir,0,f.out+64),uint32_t(-3));
    for(unsigned i=64;i<128;++i) CHECK_EQ(ld8(f.out+i),0xCD);
    f.prepare("AB",0,0);CHECK_EQ(f.call(7,0,f.dir,1,f.out),1);
    CHECK_EQ(ld8(f.out),'A');CHECK_EQ(ld8(f.out+1),'B');CHECK_EQ(ld8(f.out+2),0);
    CHECK_EQ(f.call(7,2,f.dir,1,f.out+64),0);
    for(unsigned i=64;i<128;++i) CHECK_EQ(ld8(f.out+i),0xCD);
    CHECK_EQ(f.call(4,2,f.dir,f.data),1);
    auto& c=g_master;c.r[4]=f.data;c.r[5]=f.data+16384;c.r[6]=f.out;
    // BIOS pointer-table slot 0x06000358 resolves to the runtime entry 0x1358.
    CHECK_EQ(bios_call(c,0x1358),true);
    CHECK_EQ(ld16(f.out),1);CHECK_EQ(ld16(f.out+2),1);
    CHECK_EQ(ld16(f.out+4),2);CHECK_EQ(ld16(f.out+6),1);
}

TEST(malformed_backup_record_length_is_rejected_before_allocating_and_keeps_prior_save) {
    BackupFixture f;f.prepare("A",1,42);CHECK_EQ(f.call(4,0,f.dir,f.data),0);
    {
        std::ofstream append(f.folder/"backup.bin",std::ios::binary|std::ios::app);
        char header[32]{};header[0]='B';for(int i=28;i<32;++i) header[i]=char(0xFF);
        append.write(header,sizeof header);
    }
    f.reload();f.prepare("A",0,0);CHECK_EQ(f.call(5,0),0);CHECK_EQ(ld8(f.out),42);
    f.prepare("B",0,0);CHECK_EQ(f.call(5,0),5);
}

TEST(replay_history_does_not_mark_a_save_as_live) {
    namespace fs = std::filesystem;
    const auto folder = fs::temp_directory_path() / ("sf3-live-save-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    fs::create_directory(folder);
    const auto old_out = g_cfg.out;
    const auto old_resume = g_cfg.resume;
    g_cfg.out = folder.string();
    g_cfg.save = (folder / "backup.bin").string();
    uint8_t ip[256]{};
    bios_select_save(ip);
    const uint32_t dir = 0x06018000;
    for (int i = 0; i < 36; ++i) st8(dir+i, 0);
    st8(dir, 'A'); st32(dir+28, 1); st8(dir+64, 7);
    auto write = [&] {
        auto& c = g_master;
        c.r[4] = 0; c.r[5] = dir; c.r[6] = dir+64; c.r[7] = 0;
        CHECK_EQ(bios_call(c, 0x3010), true);
        CHECK_EQ(c.r[0], 0);
    };
    g_cfg.resume = UINT64_MAX;
    write();
    CHECK_EQ(fs::exists(folder / "backup.bin"), true);
    CHECK_EQ(fs::exists(folder / "live-save-written.txt"), false);
    g_cfg.resume = 0;
    write();
    CHECK_EQ(fs::exists(folder / "live-save-written.txt"), true);
    g_cfg.out = old_out; g_cfg.resume = old_resume;
    fs::remove(folder / "backup.bin");
    fs::remove(folder / "live-save-written.txt");
    fs::remove(folder);
}

TEST(empty_backup_reports_writable_entries_for_zero_length_queries) {
    uint8_t ip[256]{};
    g_cfg.save = "-";
    bios_select_save(ip);
    auto stat = [](uint32_t size) {
        auto& c = g_master;
        c.r[4] = 0; c.r[5] = size; c.r[6] = 0x06018000;
        CHECK_EQ(bios_call(c, 0x300C), true);
        CHECK_EQ(c.r[0], 0);
        CHECK_EQ(ld32(0x06018010), 510);
        return ld32(0x06018014);
    };
    CHECK_EQ(stat(0), 255);
    CHECK_EQ(stat(12904), 2);
}

TEST(internal_and_cartridge_have_independent_saves_and_capacity) {
    namespace fs = std::filesystem;
    const auto folder = fs::temp_directory_path() / ("sf3-dual-save-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    fs::create_directory(folder);
    g_cfg.save = (folder / "backup.bin").string();
    uint8_t ip[256]{}; bios_select_save(ip);
    auto call = [](uint32_t fn, uint32_t device, uint32_t r5, uint32_t r6, uint32_t r7=0) {
        auto& c=g_master; c.r[4]=device; c.r[5]=r5; c.r[6]=r6; c.r[7]=r7;
        CHECK_EQ(bios_call(c,0x3000+fn*4), true); return c.r[0];
    };
    const uint32_t dir=0x06018000, data=dir+64, out=data+64;
    for (int i=0;i<36;++i) st8(dir+i,0);
    st8(dir,'A'); st32(dir+28,1);
    for (uint32_t device=0;device<2;++device) {
        st8(data,7+device);
        CHECK_EQ(call(4,device,dir,data),0);
        CHECK_EQ(call(3,device,12904,out),0);
        CHECK_EQ(ld32(out),device ? 524288 : 32768);
        CHECK_EQ(ld32(out+8),device ? 512 : 64);
    }
    bios_select_save(ip);
    for (uint32_t device=0;device<2;++device) {
        CHECK_EQ(call(5,device,dir,out),0);
        CHECK_EQ(ld8(out),7+device);
        st8(data,7+device);
        CHECK_EQ(call(8,device,dir,data),0);
    }
    CHECK_EQ(call(6,1,dir,0),0);
    CHECK_EQ(call(5,1,dir,out),5);
    CHECK_EQ(call(5,0,dir,out),0);
    st32(dir+28,524289);
    CHECK_EQ(call(4,1,dir,data),4);
    fs::remove(folder/"backup.bin"); fs::remove(folder/"backup.bin.cartridge"); fs::remove(folder);
}
