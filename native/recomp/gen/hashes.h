// SF3 recomp, on-console generator: CRC-32 (zlib's) and SHA-1 for module tables and maps (MIT,
// written from the public specifications: ISO 3309 / RFC 1952 CRC, FIPS 180-4 SHA-1).
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string>

namespace sf3::gen {

inline uint32_t crc32(const uint8_t* p, size_t n) {
    static uint32_t table[256];
    if (!table[1])
        for (uint32_t i = 0; i < 256; ++i) {
            uint32_t c = i;
            for (int k = 0; k < 8; ++k) c = c & 1 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            table[i] = c;
        }
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; ++i) c = table[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

inline std::string sha1_hex(const uint8_t* p, size_t n) {
    uint32_t h[5] = {0x67452301u, 0xEFCDAB89u, 0x98BADCFEu, 0x10325476u, 0xC3D2E1F0u};
    auto rol = [](uint32_t x, int s) { return x << s | x >> (32 - s); };
    uint64_t bits = uint64_t(n) * 8;
    size_t total = (n + 9 + 63) / 64 * 64;
    uint8_t blk[64];
    for (size_t off = 0; off < total; off += 64) {
        for (size_t i = 0; i < 64; ++i) {
            size_t j = off + i;
            if (j < n) blk[i] = p[j];
            else if (j == n) blk[i] = 0x80;
            else if (j >= total - 8) blk[i] = uint8_t(bits >> (8 * (total - 1 - j)));
            else blk[i] = 0;
        }
        uint32_t w[80];
        for (int i = 0; i < 16; ++i) w[i] = uint32_t(blk[4 * i]) << 24 | blk[4 * i + 1] << 16 | blk[4 * i + 2] << 8 | blk[4 * i + 3];
        for (int i = 16; i < 80; ++i) w[i] = rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
        uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4];
        for (int i = 0; i < 80; ++i) {
            uint32_t f, k;
            if (i < 20) f = (b & c) | (~b & d), k = 0x5A827999u;
            else if (i < 40) f = b ^ c ^ d, k = 0x6ED9EBA1u;
            else if (i < 60) f = (b & c) | (b & d) | (c & d), k = 0x8F1BBCDCu;
            else f = b ^ c ^ d, k = 0xCA62C1D6u;
            uint32_t t = rol(a, 5) + f + e + k + w[i];
            e = d, d = c, c = rol(b, 30), b = a, a = t;
        }
        h[0] += a, h[1] += b, h[2] += c, h[3] += d, h[4] += e;
    }
    char s[41];
    for (int i = 0; i < 5; ++i) snprintf(s + 8 * i, 9, "%08x", h[i]);
    return s;
}

}  // namespace sf3::gen
