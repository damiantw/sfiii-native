"""CD-ROM Mode 1 sectors (ECMA-130): sync, BCD MSF header, EDC and Reed-Solomon P/Q parity.

Written from the standard, not from the wizard; the wizard's DiscUtils fork produces the same
standard sectors.  A pure-Python path keeps the tests dependency-free; numpy, when present,
encodes whole runs of sectors at once for real discs.
"""
SYNC = b"\x00" + b"\xff" * 10 + b"\x00"

_F = [0] * 256
_B = [0] * 256
_EDC = [0] * 256
for _i in range(256):
    _j = (_i << 1) ^ (0x11D if _i & 0x80 else 0)
    _F[_i] = _j & 0xFF
    _B[_i ^ (_j & 0xFF)] = _i
    _e = _i
    for _ in range(8):
        _e = (_e >> 1) ^ (0xD8018001 if _e & 1 else 0)
    _EDC[_i] = _e


def bcd(n):
    return ((n // 10) << 4) | (n % 10)


def msf(lba):
    """Header address of a sector: LBA 0 is 00:02:00."""
    a = lba + 150
    return bytes((bcd(a // 4500), bcd(a // 75 % 60), bcd(a % 75)))


def edc(data):
    e = 0
    for b in data:
        e = (e >> 8) ^ _EDC[(e ^ b) & 0xFF]
    return e


def _parity(sector, major_count, minor_count, major_mult, minor_inc, dest):
    size = major_count * minor_count
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        a = b = 0
        for _ in range(minor_count):
            t = sector[12 + index]
            index += minor_inc
            if index >= size:
                index -= size
            a ^= t
            b ^= t
            a = _F[a]
        a = _B[_F[a] ^ b]
        sector[dest + major] = a
        sector[dest + major + major_count] = a ^ b


def mode1(user, lba):
    """One 2352-byte Mode 1 sector for 2048 bytes of user data at `lba`."""
    if len(user) != 2048:
        raise ValueError("Mode 1 user data is 2048 bytes")
    s = bytearray(2352)
    s[0:12] = SYNC
    s[12:15] = msf(lba)
    s[15] = 1
    s[16:2064] = user
    e = edc(s[0:2064])
    s[2064:2068] = e.to_bytes(4, "little")
    _parity(s, 86, 24, 2, 86, 2076)
    _parity(s, 52, 43, 86, 88, 2248)
    return bytes(s)


# ---------------------------------------------------------------- vectorised encoder

try:  # pragma: no cover - exercised on machines with numpy
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None


_TABLES = None


def _edc_tables_fast():
    """Building T column by column is slow in a loop; build it from the shift recurrence."""
    np = _np
    edc_lut = np.array(_EDC, dtype=np.uint32)
    T = np.zeros((2064, 256), dtype=np.uint32)
    e = edc_lut[np.arange(256)]
    T[2063] = e
    for pos in range(2062, -1, -1):
        e = (e >> 8) ^ edc_lut[e & 0xFF]
        T[pos] = e
    return T


def _tables():
    global _TABLES
    if _TABLES is None:
        np = _np
        T = _edc_tables_fast()

        def plan(major_count, minor_count, major_mult, minor_inc):
            size = major_count * minor_count
            idx = np.zeros((minor_count, major_count), dtype=np.int64)
            for major in range(major_count):
                index = (major >> 1) * major_mult + (major & 1)
                for m in range(minor_count):
                    idx[m, major] = 12 + index
                    index += minor_inc
                    if index >= size:
                        index -= size
            return idx
        _TABLES = (T, plan(86, 24, 2, 86), plan(52, 43, 86, 88),
                   np.array(_F, np.uint8), np.array(_B, np.uint8))
    return _TABLES


def mode1_many(user, first_lba):
    """Encode len(user)/2048 consecutive sectors; returns bytes.  Uses numpy if available."""
    n = len(user) // 2048
    if len(user) != n * 2048:
        raise ValueError("user data must be whole 2048-byte sectors")
    if _np is None or n < 64:
        return b"".join(mode1(user[k * 2048:(k + 1) * 2048], first_lba + k) for k in range(n))
    np = _np
    T, pidx, qidx, F, B = _tables()
    s = np.zeros((n, 2352), dtype=np.uint8)
    s[:, 0:12] = np.frombuffer(SYNC, np.uint8)
    a = np.arange(n, dtype=np.int64) + first_lba + 150
    def tobcd(v):
        return ((v // 10) << 4) | (v % 10)
    s[:, 12] = tobcd(a // 4500)
    s[:, 13] = tobcd(a // 75 % 60)
    s[:, 14] = tobcd(a % 75)
    s[:, 15] = 1
    s[:, 16:2064] = np.frombuffer(bytes(user), np.uint8).reshape(n, 2048)
    pos = np.arange(2064)
    e = np.bitwise_xor.reduce(T[pos[None, :], s[:, 0:2064]], axis=1)
    s[:, 2064:2068] = e.astype("<u4").view(np.uint8).reshape(n, 4)
    for idx, major_count, dest in ((pidx, 86, 2076), (qidx, 52, 2248)):
        acc_a = np.zeros((n, major_count), np.uint8)
        acc_b = np.zeros((n, major_count), np.uint8)
        for row in idx:
            t = s[:, row]
            acc_a ^= t
            acc_b ^= t
            acc_a = F[acc_a]
        acc_a = B[F[acc_a] ^ acc_b]
        s[:, dest:dest + major_count] = acc_a
        s[:, dest + major_count:dest + 2 * major_count] = acc_a ^ acc_b
    return s.tobytes()
