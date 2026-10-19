#include "replay-checkpoint.h"
#include <cstdio>
#include <exception>
#include <string>
int main(int argc, char** argv) {
    try {
        if (argc == 4 && std::string(argv[1]) == "verify") {
            std::printf("%llu\n", (unsigned long long)sf3_replay::verify(argv[2], argv[3])); return 0;
        }
        if (argc == 6 && std::string(argv[1]) == "save") {
            auto path = sf3_replay::save(argv[2], argv[3], argv[4], std::stoull(argv[5]));
            std::printf("%s\n", path.string().c_str()); return 0;
        }
        std::fprintf(stderr, "usage: replay_checkpoint verify CHECKPOINT SEED | save ROOT SEED INPUT FRAME\n");
        return 2;
    } catch (const std::exception& e) { std::fprintf(stderr, "Replay checkpoint: %s\n", e.what()); return 1; }
}
