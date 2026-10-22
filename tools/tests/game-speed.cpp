#include "pace.h"
#include <cstdio>
#include <cstdlib>

static void check(bool ok) { if(!ok) std::abort(); }
int main() {
    using namespace std::chrono;
    const auto t=PaceClock::time_point(seconds(100));
    for(int speed=1;speed<=3;++speed) {
        // One virtual second consumes exactly 1/speed real seconds.
        auto base=t;auto step=nanoseconds(1000000000/speed);
        auto near=t+step-milliseconds(10);
        check(pace_wait(base,1000000000,near,speed)==milliseconds(10));
        check(pace_wait(base,1000000000,t+step,speed)==PaceClock::duration{});
        // Slow host/stall rebases instead of bursting through delayed input.
        check(pace_wait(base,1000000000,t+step+seconds(10),speed)==PaceClock::duration{});
        check(base==t+seconds(10));
        check(pace_wait(base,1000000000,t+step+seconds(10),speed)==PaceClock::duration{});
        // Native-state restoration / long-running sessions use 64-bit time.
        const uint64_t now=987654321098765ULL;
        base=t-nanoseconds(now/speed);
        check(pace_wait(base,now,t,speed)==PaceClock::duration{});
        check(pace_wait(base,now+6000000,t,speed)==nanoseconds(6000000/speed));
    }
    // Every change and pause rebases at current machine time (no jump).
    for(int before=1;before<=3;++before)for(int after=1;after<=3;++after) {
        uint64_t now=123456789012ULL;
        auto base=t-nanoseconds(now/before);
        check(pace_wait(base,now,t,before)==PaceClock::duration{});
        base=t+seconds(3)-nanoseconds(now/after);
        check(pace_wait(base,now,t+seconds(3),after)==PaceClock::duration{});
    }
    std::puts("PASS: 1x/2x/3x deadlines, stalls, restored clocks, every speed/pause transition");
}
