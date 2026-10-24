"""Comparing two images the way that matters for validating against the official wizard:
IP.BIN, volume descriptor, each file's place and contents, and the audio.  Timestamps that
cannot match between runs (patch time, the host's time zone) are masked unless asked for."""
import hashlib

from .cdimage import Disc


def _pvd_masked(pvd):
    b = bytearray(pvd)
    b[156 + 18:156 + 25] = bytes(7)   # root record time
    return bytes(b)


def summary(path):
    d = Disc(path)
    files = {}
    for r in d.files:
        data = d.read_file(r) if not r.is_cdda else b""
        files[r.name] = (r.lba, r.size, hashlib.sha1(data).hexdigest(), r.time, r.xa_attr)
    audio = [hashlib.sha1(t.audio_from_index1()).hexdigest() for t in d.audio_tracks()]
    order = [r.name for r in d.files]
    root = d.read_sectors(d.root.lba, (d.root.size + 2047) // 2048)
    sectors = (d.data.end - d.data.start) // d.data.sector_size
    d.close()
    return dict(ip=d.ip_raw, pvd=d.pvd, files=files, order=order, audio=audio, root=root, sectors=sectors)


def diff(a, b, times=False):
    out = []
    if a["ip"] != b["ip"]:
        n = sum(x != y for x, y in zip(a["ip"], b["ip"]))
        first = next(i for i, (x, y) in enumerate(zip(a["ip"], b["ip"])) if x != y)
        out.append("IP.BIN differs (%d bytes, first at 0x%X)" % (n, first))
    pa, pb = (a["pvd"], b["pvd"]) if times else (_pvd_masked(a["pvd"]), _pvd_masked(b["pvd"]))
    if pa != pb:
        first = next(i for i, (x, y) in enumerate(zip(pa, pb)) if x != y)
        out.append("primary volume descriptor differs (first at byte %d)" % first)
    if a["sectors"] != b["sectors"]:
        out.append("data track is %d sectors vs %d" % (a["sectors"], b["sectors"]))
    if a["order"] != b["order"]:
        out.append("directory order differs")
    for name in sorted(set(a["files"]) | set(b["files"])):
        fa, fb = a["files"].get(name), b["files"].get(name)
        if fa is None or fb is None:
            out.append("%s only in %s" % (name, "the second" if fa is None else "the first"))
            continue
        if fa[2] != fb[2] or fa[1] != fb[1]:
            out.append("%s: contents differ (%d vs %d bytes)" % (name, fa[1], fb[1]))
        if fa[0] != fb[0]:
            out.append("%s: at sector %d vs %d" % (name, fa[0], fb[0]))
        if fa[4] != fb[4]:
            out.append("%s: XA attributes differ" % name)
        if times and fa[3] != fb[3]:
            out.append("%s: time %s vs %s" % (name, fa[3].hex(), fb[3].hex()))
    if a["audio"] != b["audio"]:
        out.append("audio differs")
    return out


def main(a, b, times=False):
    sa, sb = summary(a), summary(b)
    d = diff(sa, sb, times)
    for line in d:
        print(line)
    if not d:
        print("identical%s" % ("" if times else " (timestamps not compared)"))
    return 1 if d else 0
