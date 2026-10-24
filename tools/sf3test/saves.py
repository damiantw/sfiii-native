"""Convert Saturn backup RAM images (Mednafen .bkr, SSF/Yabause byte-interleaved .bin, raw)
and single-file .BUP exports into the runtime's native backup record format, and back.

Data-free: this module only knows the public Saturn backup RAM layout. Save files themselves
stay outside the repository (callers must pass external paths).

Saturn backup RAM (de-interleaved): block 0 (and 1 for 64-byte blocks) holds "BackUpRam Format";
an archive starts at a block whose first word is 0x80000000, followed by name[11], language[1],
comment[10], date[4] (minutes since 1980), size[4], a u16 block list ending in 0, then data.
Every block but the first carries 4 tag bytes then payload.

Native record: name[12] comment[11] language[1] date<u32 LE> size<u32 LE> then data."""
import struct

MAGIC = b'BackUpRam Format'


def deinterleave(data):
    """SSF/Yabause store each backup byte in the odd byte of a 16-bit word."""
    if MAGIC not in data[:0x400] and MAGIC in data[1::2][:0x400]:
        return data[1::2]
    return data


def block_size(raw):
    return 64 if len(raw) <= 0x8000 else 512 if len(raw) <= 0x80000 else 512


def parse_bram(data):
    """List of dicts {name, language, comment, date, data} from a backup RAM image."""
    raw = deinterleave(data)
    if MAGIC not in raw[:0x400]:
        raise ValueError('not a Saturn backup RAM image')
    bs = block_size(raw)
    nblocks = len(raw) // bs
    out = []
    for b in range(2, nblocks):
        blk = raw[b * bs:(b + 1) * bs]
        if struct.unpack_from('>I', blk, 0)[0] != 0x80000000:
            continue
        name = blk[4:15].split(b'\0')[0].decode('ascii', 'replace')
        language = blk[15]
        comment = blk[16:26].split(b'\0')[0]
        date, size = struct.unpack_from('>II', blk, 26)
        # stream of payload bytes: rest of the first block, then each listed block minus its tag
        def stream():
            yield blk[34:]
            for nb in blocks:
                yield raw[nb * bs + 4:(nb + 1) * bs]
        # read the block list incrementally (it can spill into listed blocks)
        blocks, buf, pos, i = [], bytearray(blk[34:]), 0, 0
        while True:
            while pos + 2 > len(buf):
                if i >= len(blocks):
                    raise ValueError(f'{name}: truncated block list')
                nb = blocks[i]; i += 1
                buf += raw[nb * bs + 4:(nb + 1) * bs]
            v = struct.unpack_from('>H', buf, pos)[0]; pos += 2
            if v == 0:
                break
            blocks.append(v)
        while len(buf) - pos < size and i < len(blocks):
            nb = blocks[i]; i += 1
            buf += raw[nb * bs + 4:(nb + 1) * bs]
        payload = bytes(buf[pos:pos + size])
        if len(payload) != size:
            raise ValueError(f'{name}: truncated data')
        out.append(dict(name=name, language=language, comment=comment, date=date, data=payload))
    return out


def parse_bup(data):
    """A single-save .BUP export ("Vmem" header, 64 bytes)."""
    if data[:4] != b'Vmem':
        raise ValueError('not a BUP file')
    name = data[0x10:0x1B].split(b'\0')[0].decode('ascii')
    comment = data[0x1C:0x26].split(b'\0')[0]
    language = data[0x27]
    date, size = struct.unpack_from('>II', data, 0x28)
    payload = data[0x40:0x40 + size]
    if len(payload) != size:
        raise ValueError('truncated BUP')
    return [dict(name=name, language=language, comment=comment, date=date, data=payload)]


def check_sf3(rec):
    d = rec['data']
    if rec['name'].startswith('SFORCE3') and len(d) >= 8:
        return int.from_bytes(d[:4], 'big') == len(d) - 8 and int.from_bytes(d[4:8], 'big') == sum(d[8:])
    return None


def native_record(rec):
    head = (rec['name'].encode().ljust(12, b'\0')[:12] + bytes(rec['comment'])[:10].ljust(11, b'\0')
            + bytes([rec['language']]) + struct.pack('<II', rec['date'], len(rec['data'])))
    return head + rec['data']


def native_backup(recs):
    """Bytes of a native backup file holding `recs` (sorted by name, as the importer writes)."""
    by = {r['name']: r for r in recs}
    return b''.join(native_record(by[k]) for k in sorted(by))


def parse_native(data):
    out = []
    while data:
        head, data = data[:32], data[32:]
        name = head[:12].split(b'\0')[0].decode('ascii')
        size = struct.unpack_from('<I', head, 28)[0]
        out.append(dict(name=name, comment=head[12:23].split(b'\0')[0], language=head[23],
                        date=struct.unpack_from('<I', head, 24)[0], data=data[:size]))
        data = data[size:]
    return out


def load_any(data):
    if data[:4] == b'Vmem':
        return parse_bup(data)
    if MAGIC in deinterleave(data)[:0x400]:
        return parse_bram(data)
    return parse_native(data)


def build_bram(recs, size=0x8000, interleave=True):
    """A formatted internal backup RAM image (64-byte blocks) holding `recs`, in the
    byte-interleaved layout Yabause/SSF use when `interleave` (odd bytes, even bytes 0xFF)."""
    bs = 64
    raw = bytearray(size)
    raw[:bs] = MAGIC * (bs // len(MAGIC))
    nxt = 2
    for r in recs:
        data = r['data']
        n = 1
        while 34 + 2 * n + len(data) > bs + (bs - 4) * (n - 1):
            n += 1
        blocks = list(range(nxt, nxt + n))
        if blocks[-1] >= size // bs:
            raise ValueError('backup RAM full')
        nxt += n
        body = (r['name'].encode().ljust(11, b'\0')[:11] + bytes([r['language']])
                + bytes(r['comment'])[:10].ljust(10, b'\0') + struct.pack('>II', r['date'], len(data))
                + b''.join(struct.pack('>H', b) for b in blocks[1:]) + b'\0\0' + data)
        first = blocks[0] * bs
        raw[first:first + 4] = b'\x80\0\0\0'
        chunk, body = body[:bs - 4], body[bs - 4:]
        raw[first + 4:first + 4 + len(chunk)] = chunk
        for b in blocks[1:]:
            chunk, body = body[:bs - 4], body[bs - 4:]
            raw[b * bs + 4:b * bs + 4 + len(chunk)] = chunk
    if not interleave:
        return bytes(raw)
    out = bytearray(b'\xff' * (2 * size))
    out[1::2] = raw
    return bytes(out)
