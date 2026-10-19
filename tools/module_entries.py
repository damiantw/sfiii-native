"""Conservative recognition of entry points in fully matched SH-2 code idioms."""


def unrolled_copy_entries(data: bytes, base: int) -> set[int]:
    """Entry per longword in a complete descending 64-byte copy and return.

    Some routines compute a jump into this sequence according to copy length.
    Require all sixteen load/store pairs and a known harmless RTS delay slot;
    neither a lone instruction pair nor an arbitrary pointer is evidence.
    """
    pattern = b''.join(
        (0x5050 | n).to_bytes(2, 'big') + (0x1400 | n).to_bytes(2, 'big')
        for n in range(15, -1, -1)
    )
    entries = set()
    for offset in range(0, len(data) - 67, 2):
        if (base + offset) & 1:
            continue
        if data[offset:offset + 64] != pattern:
            continue
        if data[offset + 64:offset + 68] not in (b'\x00\x0b\x00\x09', b'\x00\x0b\x20\x0b'):
            continue
        # Include the RTS entry for a zero-length copy as well.
        entries.update(base + offset + n * 4 for n in range(17))
    return entries


def arithmetic_shift_entries(data: bytes, base: int) -> set[int]:
    """Entries in a complete byte/word/longword arithmetic-right-shift cascade.

    Count dispatch jumps into SHAR chains; register only verified instructions,
    including RTS entries whose delay slot performs the final operation.
    Require all three chains and the zero-shift return, not isolated shifts.
    """
    entries = set()
    for register in range(16):
        shar = 0x4021 | register << 8
        words = ([shar] * 6 + [0x4029 | register << 8, 0x4019 | register << 8,
                              0x000B, 0x600E | register << 8 | register << 4]
                 + [shar] * 7 + [0x4029 | register << 8, 0x000B, 0x600F | register << 8 | register << 4]
                 + [shar] * 14 + [0x000B, shar, 0x000B, 0x0009])
        pattern = b''.join(w.to_bytes(2, 'big') for w in words)
        at = data.find(pattern)
        while at >= 0:
            if not ((base + at) & 1):
                entries.update(base + at + off for off in range(0, len(pattern), 2)
                               if off not in (18, 38, 70, 74))
            at = data.find(pattern, at + 1)
    return entries
