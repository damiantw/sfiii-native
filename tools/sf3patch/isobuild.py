"""The data track the wizard writes: a fresh ISO 9660 image laid out the way its DiscUtils fork
(CDBuilder) lays it out, so files that grow simply move everything after them.

Layout, in 2048-byte sectors:
  0-15   IP.BIN (the system area, rewritten by the wizard)
  16     primary volume descriptor          17  set terminator
  18     type-L path table                  19  type-M path table
  20..   root directory, then every file in the order it was added (no gaps); empty files
         take no space and CD-DA entries (names starting "CD") point past the data track
  +150   zero sectors after the last file (the wizard's post-gap, Mode 1 with EDC/ECC)

The directory-record quirks of that builder are kept: records that would end exactly at a
sector boundary move to the next sector, the CD-DA record carries a 14-byte XA "CD-DA"
system-use field and a data length of 0, all volume dates are blank, and the type-M path
table pointer says sector 19 wherever the table really lands.
"""
from dataclasses import dataclass
import datetime
from typing import Callable

SECTOR = 2048
POSTGAP = 150


class BuildError(ValueError):
    pass


@dataclass
class BuildFile:
    name: str                     # as passed to CDBuilder.AddFile (e.g. "X5FOO.BIN")
    size: int
    time: datetime.datetime       # recorded as-is (the wizard's builder uses a zero time zone)
    read: Callable[[], bytes] = None

    @property
    def is_cd(self):
        return self.name.startswith("CD")


# ---------------------------------------------------------------- names (IsoUtilities)

def _valid_file_name(s):
    return all(("0" <= c <= "9") or ("A" <= c <= "Z") or c in "_.;" for c in s)


def _valid_dchar(c):
    return ("0" <= c <= "9") or ("A" <= c <= "Z") or c in "_."


def _valid_achar(c):
    return (" " <= c <= '"') or ("%" <= c <= "/") or (":" <= c <= "?") or ("0" <= c <= "9") \
        or ("A" <= c <= "Z") or c == "_"


def split_file_name(name):
    parts = [name, "", "1"]
    if "." in name:
        dot = name.index(".")
        parts[0] = name[:dot]
        if ";" in name:
            semi = name.find(";", dot + 1)
            if semi < 0:
                raise BuildError("bad file name %r" % name)
            parts[1] = name[dot + 1:semi]
            parts[2] = name[semi + 1:]
        else:
            parts[1] = name[dot + 1:]
    elif ";" in name:
        semi = name.index(";")
        parts[0] = name[:semi]
        parts[2] = name[semi + 1:]
    try:
        v = int(parts[2]) if parts[2].strip().isdigit() else 0
    except ValueError:
        v = 0
    if not 1 <= v <= 32767:
        v = 1
    parts[2] = str(v)
    return parts


def normalize_file_name(name):
    p = split_file_name(name)
    return p[0] + "." + p[1] + ";" + p[2]


def short_file_name(name):
    if _valid_file_name(name):
        return name
    chars = [c if (_valid_dchar(c) or c in ".;") else "_" for c in name.upper()]
    p = split_file_name("".join(chars))
    if len(p[0]) + len(p[1]) > 30:
        p[1] = p[1][:3]
    if len(p[0]) + len(p[1]) > 30:
        p[0] = p[0][:30 - len(p[1])]
    return p[0] + "." + p[1] + ";" + p[2]


def identifier_text(short):
    """IsoUtilities.WriteString(str): ";1" appended, plus a NUL when that makes it odd."""
    return short + ";1" if len(short) & 1 else short + ";1\0"


def record_size(short):
    """DirectoryRecord.CalcLength(name, ASCII, CDDA: false), used to size directories."""
    if len(short) == 1 and short <= "\x01":
        n = 1
    else:
        n = len(short.encode("ascii", errors="replace")) + 2
        if short.startswith("CD") or short.endswith(".MPG"):
            n += 14
    return 33 + n + (1 if n % 2 == 0 else 0)


def _compare_part(x, y, pad):
    for i in range(max(len(x), len(y))):
        a = x[i] if i < len(x) else pad
        b = y[i] if i < len(y) else pad
        if a != b:
            return ord(a) - ord(b)
    return 0


def _compare_part_backwards(x, y, pad):
    n = max(len(x), len(y))
    ox, oy = n - len(x), n - len(y)
    for i in range(n):
        a = x[i - ox] if i >= ox else pad
        b = y[i - oy] if i >= oy else pad
        if a != b:
            return ord(b) - ord(a)
    return 0


def _split_name(s):
    out, cur = [], ""
    for c in s:
        if c in ".;":
            out.append(cur)
            cur = ""
        else:
            cur += c
    out.append(cur)
    return out


def member_compare(x, y):
    """BuildDirectoryMember.DirectorySortedComparison on normalized names."""
    a, b = _split_name(x), _split_name(y)
    for i in range(2):
        r = _compare_part(a[i] if len(a) > i else "", b[i] if len(b) > i else "", " ")
        if r:
            return r
    return _compare_part_backwards(a[2] if len(a) > 2 else "", b[2] if len(b) > 2 else "", "0")


# ---------------------------------------------------------------- byte helpers

def both32(v):
    return v.to_bytes(4, "little") + v.to_bytes(4, "big")


def both16(v):
    return v.to_bytes(2, "little") + v.to_bytes(2, "big")


def dir_time(dt):
    if dt is None:
        return bytes(7)
    if dt.year < 1900:
        raise BuildError("Year is out of range")
    return bytes((dt.year - 1900, dt.month, dt.day, dt.hour, dt.minute, dt.second, 0))


def _ascii_bytes(s):
    return bytes(ord(c) & 0xFF for c in s)


def _record_standard(ident, lba, size, time, flags):
    n = record_size(ident)
    r = bytearray(n)
    r[0] = n
    r[2:10] = both32(lba)
    r[10:18] = both32(size)
    r[18:25] = dir_time(time)
    r[25] = flags
    r[28:32] = both16(1)
    if len(ident) == 1 and ident <= "\x01":
        r[32] = 1
        r[33] = ord(ident)
    else:
        b = ident.encode("ascii", errors="replace")
        r[32] = len(b)
        r[33:33 + len(b)] = b
    return bytes(r)


def _record_member(short, lba, size, time, xa):
    """The position-aware writers of the wizard's DiscUtils fork (plain and XA)."""
    text = identifier_text(short)
    r = bytearray([0, 0]) + both32(lba) + both32(size) + dir_time(time) + bytes((0, 0, 0)) + both16(1) + b"\0"
    r += _ascii_bytes(text)
    r[32] = len(text.rstrip("\0"))
    if xa:
        r += b"\0\0\0\0" + (b"\x41" if short.startswith("CD") else b"\x31" if short.endswith(".MPG") else b"") \
            + b"\x11\x58\x41" + bytes(6)
    r[0] = len(r) & 0xFF
    return bytes(r)


# ---------------------------------------------------------------- the builder

@dataclass
class Identifiers:
    system: str = "SEGA SEGASATURN"
    volume: str = ""
    volume_set: str = ""
    publisher: str = "SEGA ENTERPRISES,LTD."
    preparer: str = "CAMELOT,LTD."
    application: str = ""
    copyright: str = "COPYRIGH.TXT"
    abstract: str = "ABSTRACT.TXT"
    bibliographic: str = "BIBLIOGR.TXT"


def _write_string(buf, off, width, s, pad=True, truncate=False, check=None):
    if check is not None and not all(check(c) for c in s):
        raise BuildError("Attempt to write string with invalid characters: %r" % s)
    text = s + " " * width if pad else s
    data = _ascii_bytes(text)[:width]
    if not truncate and len(s) > width:
        raise BuildError("Failed to write entire string %r" % s)
    buf[off:off + len(data)] = data


class Layout:
    def __init__(self, ip, files, root_time, audio_bytes, ids):
        if len(ip) != 16 * SECTOR:
            raise BuildError("IP.BIN area must be 16 sectors")
        self.ip = ip
        self.files = list(files)
        self.root_time = root_time
        self.ids = ids
        names = {}
        for f in self.files:
            if "\\" in f.name or "/" in f.name:
                raise BuildError("subdirectories are not supported (%s)" % f.name)
            if f.name.endswith(".MPG"):
                raise BuildError("%s: MPEG (Mode 2) files are not supported" % f.name)
            key = normalize_file_name(f.name)
            if key in names:
                raise BuildError("File already exists: %s (the wizard fails here too)" % f.name)
            names[key] = f
        self.members = list(names.items())
        from .dotnet import introsort
        introsort(self.members, lambda a, b: member_compare(a[0], b[0]))
        # root directory size (GetDataSize)
        n = 68
        for key, f in self.members:
            rs = record_size(short_file_name(f.name))
            if n % SECTOR + rs > SECTOR:
                n += SECTOR - n % SECTOR
            n += rs
        self.root_size = (n + SECTOR - 1) // SECTOR * SECTOR
        self.root_lba = 20
        pos = 40960 + self.root_size
        self.lba = {}
        self.order = []
        for f in self.files:
            if f.is_cd:
                continue
            self.lba[f.name] = pos // SECTOR
            if f.size:
                self.order.append(f)
                pos += (f.size + SECTOR - 1) // SECTOR * SECTOR
        self.files_end = pos
        self.data_sectors = pos // SECTOR + POSTGAP
        cd = [f for f in self.files if f.is_cd]
        audio = sum(b // 2352 * 2048 for b in audio_bytes)
        num7 = pos
        if cd:
            num7 += 307200
        sub = 0
        if not cd:
            sub = -614400 if audio > 0 else -307200
        for f in cd:
            num7 += 307200
            self.lba[f.name] = -(-num7 // SECTOR)
            size = f.size // 2352 * 2048
            num7 += (size + SECTOR - 1) // SECTOR * SECTOR
            sub += (size + SECTOR - 1) // SECTOR * SECTOR
        num7 += audio - sub
        self.volume_space = num7 // SECTOR
        self.root = self._root_directory()

    def _root_directory(self):
        buf = bytearray(self.root_size)
        here = _record_standard("\0", self.root_lba, self.root_size, self.root_time, 2)
        up = _record_standard("\x01", self.root_lba, self.root_size, self.root_time, 2)
        buf[0:34] = here
        buf[34:68] = up
        n = 68
        for key, f in self.members:
            short = short_file_name(f.name)
            size = f.size // 2352 * 2048 if f.is_cd else f.size
            rec = _record_member(short, self.lba[f.name], size, f.time, f.is_cd)
            room = SECTOR - n % SECTOR
            if len(rec) - room >= 0:
                rec = bytes(room) + rec
            if n + len(rec) > len(buf):
                raise BuildError("the root directory overflows the space the wizard's builder reserves "
                                 "for it; the wizard would silently drop %s" % f.name)
            buf[n:n + len(rec)] = rec
            n += len(rec)
        return bytes(buf)

    def system_area(self):
        """Sectors 0-19 plus the root directory."""
        out = bytearray(40960)
        out[0:32768] = self.ip
        pvd = bytearray(SECTOR)
        pvd[0] = 1
        pvd[1:6] = b"CD001"
        pvd[6] = 1
        ids = self.ids
        _write_string(pvd, 8, 32, ids.system, check=_valid_achar)
        _write_string(pvd, 40, 32, ids.volume, truncate=True)
        pvd[80:88] = both32(self.volume_space)
        pvd[120:124] = both16(1)
        pvd[124:128] = both16(1)
        pvd[128:132] = both16(2048)
        pvd[132:140] = both32(10)
        pvd[140:144] = (18).to_bytes(4, "little")
        pvd[148:152] = (19).to_bytes(4, "big")
        pvd[156:190] = _record_standard("\0", self.root_lba, self.root_size, self.root_time, 2)
        _write_string(pvd, 190, 129, ids.volume_set, check=_valid_dchar)
        _write_string(pvd, 318, 129, ids.publisher, check=_valid_achar)
        _write_string(pvd, 446, 129, ids.preparer, check=_valid_achar)
        _write_string(pvd, 574, 129, ids.application, check=_valid_achar)
        _write_string(pvd, 702, 37, ids.copyright.upper(), check=_valid_dchar)
        _write_string(pvd, 739, 37, ids.abstract.upper(), check=_valid_dchar)
        _write_string(pvd, 776, 37, ids.bibliographic.upper(), check=_valid_dchar)
        for off in (813, 830, 847, 864):
            pvd[off:off + 16] = b"0" * 16
            pvd[off + 16] = 0
        pvd[881] = 1
        out[32768:34816] = pvd
        term = bytearray(SECTOR)
        term[0] = 255
        term[1:6] = b"CD001"
        term[6] = 1
        out[34816:36864] = term
        lpt = bytes((1, 0)) + self.root_lba.to_bytes(4, "little") + (1).to_bytes(2, "little") + b"\0\0"
        mpt = bytes((1, 0)) + self.root_lba.to_bytes(4, "big") + (1).to_bytes(2, "big") + b"\0\0"
        out[36864:36864 + 10] = lpt
        out[38912:38912 + 10] = mpt
        return bytes(out) + self.root

    def user_data(self, chunk_sectors=4096):
        """Yield the data track's 2048-byte user data in large chunks, post-gap included."""
        pending = bytearray(self.system_area())
        limit = chunk_sectors * SECTOR
        for f in self.order:
            data = f.read()
            if len(data) != f.size:
                raise BuildError("%s changed size while building" % f.name)
            pending += data
            pad = -len(data) % SECTOR
            pending += bytes(pad)
            while len(pending) >= limit:
                yield bytes(pending[:limit])
                del pending[:limit]
        pending += bytes(POSTGAP * SECTOR)
        while pending:
            yield bytes(pending[:limit])
            del pending[:limit]
