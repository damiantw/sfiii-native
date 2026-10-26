"""Reading the source disc: CUE/BIN (one file per track or one file for all), CHD via chdman,
and the ISO 9660 file system on the data track.

Only what the wizard reads from a mounted disc is needed: the first 16 sectors (IP.BIN), the
volume label, the root directory's files with their sizes and times, and each audio track from
its INDEX 01 to the end of the track.
"""
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

RAW = 2352
USER = 2048


class DiscError(ValueError):
    pass


@dataclass
class Track:
    number: int
    mode: str                 # 'MODE1/2352', 'MODE1/2048', 'MODE2/2352', 'AUDIO', ...
    path: Path
    indexes: dict = field(default_factory=dict)   # index number -> frame offset in file
    pregap: int = 0           # PREGAP frames (not stored in the file)
    start: int = 0            # byte offset in the file of the first stored frame
    end: int = 0              # byte offset in the file after the last frame

    @property
    def sector_size(self):
        return USER if self.mode.endswith("/2048") else RAW

    @property
    def is_audio(self):
        return self.mode == "AUDIO"

    @property
    def index1(self):
        return self.indexes[1] * self.sector_size

    def stored_bytes(self, f):
        f.seek(self.start)
        return f.read(self.end - self.start)

    def hashes(self):
        """(SHA-1, SHA-256, bytes) of the track as Redump stores it, in one pass: an unstored PREGAP
        counts as silence."""
        h1, h256 = hashlib.sha1(), hashlib.sha256()
        silence = bytes(self.pregap * self.sector_size)
        h1.update(silence)
        h256.update(silence)
        with open(self.path, "rb") as f:
            f.seek(self.start)
            left = self.end - self.start
            while left:
                chunk = f.read(min(left, 1 << 22))
                if not chunk:
                    break
                h1.update(chunk)
                h256.update(chunk)
                left -= len(chunk)
        return h1.hexdigest(), h256.hexdigest(), self.pregap * self.sector_size + self.end - self.start

    def hash_sha1(self):
        """(SHA-1, bytes) of the track as Redump stores it."""
        sha1, _, size = self.hashes()
        return sha1, size

    def audio_from_index1(self):
        """What the wizard rips: raw CD-DA from INDEX 01 to the end of the track."""
        with open(self.path, "rb") as f:
            f.seek(self.index1)
            return f.read(self.end - self.index1)


def _msf(text):
    m = re.fullmatch(r"(\d+):(\d+):(\d+)", text)
    if not m:
        raise DiscError("bad MSF time %r in CUE sheet" % text)
    mm, ss, ff = map(int, m.groups())
    return (mm * 60 + ss) * 75 + ff


def parse_cue(cue_path):
    cue_path = Path(cue_path)
    text = cue_path.read_bytes().decode("utf-8-sig", errors="replace")
    tracks, current_file = [], None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.upper().startswith("REM"):
            continue
        try:
            words = shlex.split(line, posix=True)
        except ValueError:
            words = line.split()
        key = words[0].upper()
        if key == "FILE":
            if len(words) < 3:
                raise DiscError("bad FILE line in %s" % cue_path)
            if words[-1].upper() not in ("BINARY",):
                raise DiscError("unsupported CUE file type %s (only BINARY)" % words[-1])
            name = " ".join(words[1:-1])
            current_file = (cue_path.parent / name)
            if not current_file.exists():
                # CUE sheets written on Windows may differ in case from the file on disk
                matches = [p for p in cue_path.parent.iterdir() if p.name.lower() == name.lower()]
                if len(matches) == 1:
                    current_file = matches[0]
                else:
                    raise DiscError("the CUE sheet's file %s does not exist" % current_file)
        elif key == "TRACK":
            if current_file is None:
                raise DiscError("TRACK before FILE in %s" % cue_path)
            tracks.append(Track(int(words[1]), words[2].upper(), current_file))
        elif key == "INDEX":
            tracks[-1].indexes[int(words[1])] = _msf(words[2])
        elif key == "PREGAP":
            tracks[-1].pregap = _msf(words[1])
    if not tracks:
        raise DiscError("no tracks in %s" % cue_path)
    for i, t in enumerate(tracks):
        if 1 not in t.indexes:
            raise DiscError("track %d has no INDEX 01" % t.number)
        first = min(t.indexes.values())
        t.start = first * t.sector_size
        nxt = tracks[i + 1] if i + 1 < len(tracks) else None
        if nxt is not None and nxt.path == t.path:
            t.end = min(nxt.indexes.values()) * nxt.sector_size
        else:
            t.end = t.path.stat().st_size
        if t.end < t.index1:
            raise DiscError("track %d ends before its INDEX 01" % t.number)
    return tracks


def chd_to_cue(chd, work):
    """Extract a CHD with chdman into `work`; returns the CUE path (one BIN, all tracks)."""
    chdman = shutil.which("chdman")
    if not chdman:
        raise DiscError("CHD input needs chdman (MAME tools: apt install mame-tools)")
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([chdman, "verify", "-i", str(chd)], check=True, stdout=subprocess.DEVNULL)
    cue, bin_ = work / "disc.cue", work / "disc.bin"
    for p in (cue, bin_):
        if p.exists():
            p.unlink()
    subprocess.run([chdman, "extractcd", "-i", str(chd), "-o", str(cue), "-ob", str(bin_)],
                   check=True, stdout=subprocess.DEVNULL)
    return cue


@dataclass
class Record:
    name: str           # identifier without ';1'
    lba: int
    size: int
    flags: int
    time: bytes         # 7-byte ISO 9660 recording time
    xa_attr: int = None
    is_dir: bool = False

    @property
    def is_cdda(self):
        return self.xa_attr is not None and bool(self.xa_attr & 0x4000)


class Disc:
    """A source disc image: tracks plus the ISO 9660 view of track 1."""

    def __init__(self, path, work=None):
        path = Path(path)
        if path.suffix.lower() == ".chd":
            if work is None:
                raise DiscError("CHD input needs a work directory for the extracted image")
            path = chd_to_cue(path, work)
        if path.suffix.lower() != ".cue":
            raise DiscError("give the disc as a .cue sheet or a .chd")
        self.cue = path
        self.tracks = parse_cue(path)
        self.data = self.tracks[0]
        if self.data.is_audio:
            raise DiscError("track 1 is not a data track")
        if self.data.mode not in ("MODE1/2352", "MODE1/2048"):
            raise DiscError("track 1 is %s; Saturn discs are MODE1" % self.data.mode)
        self._f = open(self.data.path, "rb")
        self.ip_raw = self.read_sectors(0, 16)
        pvd = self.read_sectors(16, 1)
        if pvd[0] != 1 or pvd[1:6] != b"CD001":
            raise DiscError("no ISO 9660 primary volume descriptor at sector 16")
        self.pvd = pvd
        self.volume_id = pvd[40:72].decode("ascii", errors="replace")
        self.root = self._record(pvd, 156)
        self.files = self._list_root()

    def close(self):
        self._f.close()

    def read_sectors(self, lba, count):
        t = self.data
        ss = t.sector_size
        out = bytearray()
        self._f.seek(t.index1 + lba * ss)
        raw = self._f.read(count * ss)
        if len(raw) < count * ss:
            raise DiscError("read past the end of the data track (sector %d)" % (lba + count))
        if ss == USER:
            return bytes(raw)
        for k in range(count):
            out += raw[k * RAW + 16:k * RAW + 16 + USER]
        return bytes(out)

    def read_file(self, rec):
        if rec.size == 0:
            return b""
        n = (rec.size + USER - 1) // USER
        return self.read_sectors(rec.lba, n)[:rec.size]

    @staticmethod
    def _record(buf, off):
        n = buf[off]
        lba = int.from_bytes(buf[off + 2:off + 6], "little")
        size = int.from_bytes(buf[off + 10:off + 14], "little")
        time = bytes(buf[off + 18:off + 25])
        flags = buf[off + 25]
        nl = buf[off + 32]
        ident = bytes(buf[off + 33:off + 33 + nl])
        su = off + 33 + nl + (0 if nl & 1 else 1)
        xa = None
        if off + n - su >= 14 and buf[su + 6:su + 8] == b"XA":
            xa = int.from_bytes(buf[su + 4:su + 6], "big")
        if ident in (b"\x00", b"\x01"):
            name = ident.decode("latin-1")
        else:
            name = ident.decode("ascii", errors="replace")
            if ";" in name:
                name = name[:name.index(";")]
            if name.endswith(".") and not flags & 2:
                name = name[:-1]  # CDFS shows "CDDA2." as "CDDA2"
        return Record(name, lba, size, flags, time, xa, bool(flags & 2))

    def _list_root(self):
        data = self.read_sectors(self.root.lba, (self.root.size + USER - 1) // USER)
        out, off = [], 0
        while off < len(data):
            n = data[off]
            if n == 0:
                off = (off // USER + 1) * USER
                continue
            rec = self._record(data, off)
            off += n
            if rec.name in ("\x00", "\x01"):
                continue
            if rec.is_dir:
                raise DiscError("the disc has a subdirectory (%s); Shining Force III discs have none, "
                                "and this tool only rebuilds a flat root" % rec.name)
            if rec.flags & 0x04:
                raise DiscError("associated file %s is not supported" % rec.name)
            out.append(rec)
        return out

    def audio_tracks(self):
        return [t for t in self.tracks[1:] if t.is_audio]


def iso_time_to_utc(t, mode="iso"):
    """The time Windows' CDFS reports for a directory record, as (y, mo, d, h, mi, s) UTC.

    mode 'iso' applies the record's GMT offset as ISO 9660 defines it; 'local' ignores the
    offset (treats the stored wall-clock time as UTC)."""
    import datetime
    if t == bytes(7):
        return None
    y, mo, d, h, mi, s, off = t[0] + 1900, t[1], t[2], t[3], t[4], t[5], t[6]
    if off > 127:
        off -= 256
    try:
        dt = datetime.datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None
    if mode == "iso" and -48 <= off <= 52:
        dt -= datetime.timedelta(minutes=15 * off)
    return dt


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()
