#pragma once

namespace sf3 {
// Prime with generated PCM before starting/resuming the device. Never splice
// synthetic silence between game chunks to refill an empty playback queue.
struct AudioBuffer {
    static constexpr int lead = 4410; // 100 ms at 44.1 kHz
    static constexpr int maximum = 11025;
    bool playing = false;
    int speed = 1; // Host playback ratio; machine PCM stays at 44.1 kHz.

    void reset(int ratio) { playing = false; speed = ratio; }

    bool drained(int queued) {
        if (!playing || queued != 0) return false;
        playing = false;
        return true;
    }
    bool ready(int queued) {
        if (playing || queued < lead * speed) return false;
        playing = true;
        return true;
    }
    bool fits(int queued, int incoming) const {
        return queued >= 0 && incoming > 0 && incoming <= maximum && queued <= maximum * speed - incoming;
    }
};
}
