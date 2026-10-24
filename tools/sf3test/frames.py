"""Tiny frame checks for sweep shots: decode the runtime's 8-bit RGB/RGBA PNGs without Pillow."""
import hashlib
import struct
import zlib


def decode_png(data):
    """(width, height, rows) for a non-interlaced 8-bit RGB or RGBA PNG; rows are bytes of RGB."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG')
    pos, idat, w = 8, b'', None
    while pos < len(data):
        n, kind = struct.unpack_from('>I4s', data, pos)
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b'IHDR':
            w, h, depth, colour, _, _, interlace = struct.unpack('>IIBBBBB', body)
            if depth != 8 or colour not in (2, 6) or interlace:
                raise ValueError('unsupported PNG layout')
            bpp = 3 if colour == 2 else 4
        elif kind == b'IDAT':
            idat += body
        elif kind == b'IEND':
            break
    raw = zlib.decompress(idat)
    stride = w * bpp
    rows, prev = [], bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1: line[i] = (line[i] + a) & 255
            elif f == 2: line[i] = (line[i] + b) & 255
            elif f == 3: line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif f == 4:
                p = a + b - c; pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        rows.append(bytes(line) if bpp == 3 else bytes(line[j] for j in range(stride) if j % 4 != 3))
    return w, h, rows


def stats(data):
    """{'sha1', 'mean', 'black'} of a PNG frame; mean is the average channel value (0-255)."""
    out = dict(sha1=hashlib.sha1(data).hexdigest())
    try:
        w, h, rows = decode_png(data)
    except (ValueError, zlib.error, struct.error):
        return out
    step = max(1, h // 60)
    sample = b''.join(rows[y][::9] for y in range(0, h, step))
    mean = sum(sample) / max(1, len(sample))
    out.update(mean=round(mean, 2), black=mean < 3.0, size=[w, h])
    return out
