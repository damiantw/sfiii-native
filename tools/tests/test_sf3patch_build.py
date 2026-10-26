"""sf3patch end to end on a synthetic disc and a synthetic patch package, built at run time.

The source disc is written here by a deliberately simple ISO 9660 writer (not the patcher's
builder): a Saturn-style IP.BIN, a flat root with a CD-DA placeholder, a Mode 1/2352 data
track and a Redump-style audio track with its two-second pregap."""
import contextlib
import datetime
import io
import hashlib
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.sf3patch import cdimage, edcecc, ipbin, output, package, patcher, selection
from tools.sf3patch import cli as sf3cli
from tools.sf3patch.cli import content_sha256, main as cli_main, matching_profiles

try:
    from test_sf3patch_formats import check_mode1_sector
except ImportError:  # run from elsewhere
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_sf3patch_formats import check_mode1_sector

SERIAL, VERSION = "GS-9999", "V1.000"


def _both32(v):
    return v.to_bytes(4, "little") + v.to_bytes(4, "big")


def _rec(name, lba, size, flags=0, xa=None, time=(98, 6, 1, 12, 0, 0, 36)):
    ident = name.encode() if isinstance(name, str) else name
    body = bytearray([0, 0]) + _both32(lba) + _both32(size) + bytes(time) + bytes([flags, 0, 0]) + \
        (1).to_bytes(2, "little") + (1).to_bytes(2, "big") + bytes([len(ident)]) + ident
    if len(ident) % 2 == 0:
        body += b"\0"
    if xa is not None:
        body += b"\0\0\0\0" + xa.to_bytes(2, "big") + b"XA" + bytes(6)
    body[0] = len(body)
    return bytes(body)


def make_ip(product=SERIAL, version=VERSION):
    b = bytearray(32768)
    hdr = (b"SEGA SEGASATURN " + b"SEGA TP T-999   " + product.encode().ljust(10) + version.encode()
           + b"19980101" + b"CD-1/1  " + b"J".ljust(10) + b" " * 6 + b"J".ljust(16)
           + b"SYNTHETIC TEST DISC".ljust(112) + bytes(16) + (0x1800).to_bytes(4, "big") + bytes(4)
           + bytes(8) + (0x06004000).to_bytes(4, "big") + bytes(4) + bytes(8))
    b[:len(hdr)] = hdr
    b[0x100:0x1800] = bytes((i * 7) & 0xFF for i in range(0x1700))
    return bytes(b)


def make_disc(folder, files, volume="SF3_TEST", audio_sectors=40, seed=5):
    """files: list of (name, bytes) in directory (sorted) order; 'CDDA2' becomes the CD-DA entry."""
    folder.mkdir(parents=True, exist_ok=True)
    ip = make_ip()
    lba = 21
    recs, blobs = [], []
    for name, data in files:
        if name == "CDDA2":
            continue
        recs.append((name, lba, len(data)))
        blobs.append(data)
        lba += max(1, -(-len(data) // 2048))
    data_sectors = lba + 150
    root = bytearray()
    root += _rec(b"\0", 20, 2048, 2) + _rec(b"\1", 20, 2048, 2)
    for name, data in files:
        if name == "CDDA2":
            root += _rec("CDDA2.;1", data_sectors + 150, audio_sectors * 2352, 0, xa=0x4111)
        else:
            r = next(r for r in recs if r[0] == name)
            root += _rec(name + ";1", r[1], r[2])
    root = bytes(root).ljust(2048, b"\0")
    pvd = bytearray(2048)
    pvd[0:7] = b"\x01CD001\x01"
    pvd[8:40] = b"SEGA SEGASATURN".ljust(32)
    pvd[40:72] = volume.encode().ljust(32)
    pvd[80:88] = _both32(data_sectors + 150 + audio_sectors)
    pvd[120:132] = (1).to_bytes(2, "little") + (1).to_bytes(2, "big") + (1).to_bytes(2, "little") + \
        (1).to_bytes(2, "big") + (2048).to_bytes(2, "little") + (2048).to_bytes(2, "big")
    pvd[156:190] = _rec(b"\0", 20, 2048, 2)
    pvd[881] = 1
    term = b"\xffCD001\x01".ljust(2048, b"\0")
    user = bytearray(ip + bytes(pvd) + term + bytes(4096) + root)
    for data in blobs:
        user += data + bytes(-len(data) % 2048 if data else 2048)
    user += bytes(150 * 2048)
    assert len(user) == data_sectors * 2048
    t1 = folder / "disc (Track 1).bin"
    t1.write_bytes(edcecc.mode1_many(bytes(user), 0))
    rnd = random.Random(seed)
    audio = bytes(rnd.randrange(256) for _ in range(audio_sectors * 2352))
    t2 = folder / "disc (Track 2).bin"
    t2.write_bytes(bytes(150 * 2352) + audio)
    cue = folder / "disc.cue"
    cue.write_text('FILE "disc (Track 1).bin" BINARY\n  TRACK 01 MODE1/2352\n    INDEX 01 00:00:00\n'
                   'FILE "disc (Track 2).bin" BINARY\n  TRACK 02 AUDIO\n    INDEX 00 00:00:00\n'
                   '    INDEX 01 00:02:00\n')
    return cue, audio


def make_package(root, entries, drive_order):
    """entries: {folder: (metadata json text, {relative path: bytes})}."""
    for sub in ("Patches", "Custom Mods", "DriveOrder", "Data"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "Data" / "data.json").write_text('{\n  "version": "25.1"\n}')
    (root / "DriveOrder" / (SERIAL + ".txt")).write_bytes(
        "".join("%s , %d\r\n" % (n, i + 1) for i, n in enumerate(drive_order)).encode())
    for folder, (meta, files) in entries.items():
        d = root / "Patches" / folder
        d.mkdir(parents=True)
        (d / "metadata.json").write_text(meta)
        for rel, data in files.items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            os.utime(p, (946684800, 946684800))   # 2000-01-01 00:00:00 UTC
    return root


def _meta(text, category, enabled, priority=None):
    s = '{"title": "%s", "text": "%s", "category": "%s", "enabled": %s' % (text, text, category, enabled)
    if priority is not None:
        s += ', "priority": %s' % priority
    return s + "}"


class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        rnd = random.Random(9)
        cls.x1 = bytes(rnd.randrange(256) for _ in range(5000))
        cls.x2 = bytes(rnd.randrange(256) for _ in range(4096))
        files = [("0.BIN", b"boot" * 300), ("ABSTRACT.TXT", b"abstract\r\n"), ("BIBLIOGR.TXT", b"biblio\r\n"),
                 ("CDDA2", b""), ("COPYRIGH.TXT", b"(c) nobody\r\n"), ("EMPTY.BIN", b""),
                 ("X1TEST.BIN", cls.x1), ("X2KEEP.BIN", cls.x2)]
        cls.files = dict(files)
        cls.cue, cls.audio = make_disc(base / "src", files)
        cls.grow = bytes(range(256)) * 20      # 5120 bytes appended: X1TEST grows by 3 sectors
        dfr1 = ("; synthetic translation\r\n10,%s,%s\r\n%X,,%s\r\n"
                % (cls.x1[0x10:0x14].hex().upper(), "DEADBEEF", 5000, cls.grow.hex().upper())).encode()
        entries = {
            "Translation": (_meta("Translation", "General", "true", "001"),
                            {SERIAL + "/X1TEST.BIN.DFR": dfr1, SERIAL + "/NEWFILE.BIN": b"brand new file",
                             SERIAL + "/" + VERSION + "/LATE.DAT": b"version specific"}),
            "Replace Text": (_meta("Replace Text", "BugFixes", "true", "100"),
                             {SERIAL.lower() + "/v1.000/ABSTRACT.TXT": b"patched abstract\r\n"}),
            "Stacked Fix": (_meta("Stacked Fix", "QoL", "true"),
                            {SERIAL + "/X1TEST.BIN.DFR": b"10,DEADBEEF,CAFEF00D\n"}),
            "Optional": (_meta("Optional", "Mods", "false", "300"),
                         {SERIAL + "/X2KEEP.BIN.DFR": ("0,%02X,00\n" % cls.x2[0]).encode()}),
            "Other Disc": (_meta("Other Disc", "General", "true", "2"),
                           {"MK-00000/X2KEEP.BIN": b"never"}),
        }
        order = ["COPYRIGH.TXT", "ABSTRACT.TXT", "BIBLIOGR.TXT", "0.BIN", "X2KEEP.BIN", "X1TEST.BIN",
                 "EMPTY.BIN", "CDDA2"]
        cls.pkg_root = make_package(base / "wiz", entries, order)
        cls.order = order
        cls.base = base

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def build(self, enable=(), out_name="GS-9999_V1.000.bin", **kw):
        disc = cdimage.Disc(self.cue)
        pkg = package.load(self.pkg_root, self.base / "work")
        ordered, errors = selection.listed(pkg.patches, SERIAL, VERSION)
        self.assertEqual(errors, [])
        chosen = selection.choose(ordered, enable=enable)
        opts = patcher.Options(now=datetime.datetime(2026, 1, 2, 3, 4, 5),
                               host_utc_offset=datetime.timedelta(hours=-5), **kw)
        b = patcher.Build(disc, pkg, chosen, self.base / ("work-" + out_name), opts)
        layout = b.layout()
        out = self.base / "out" / out_name
        out.parent.mkdir(exist_ok=True)
        cue, sectors, t1, whole = output.write_image(out, layout, b.audio_data())
        disc.close()
        return b, layout, out, cue, sectors

    def test_default_selection_round_trip(self):
        b, layout, out, cue, sectors = self.build()
        self.assertEqual([p.name for p in b.patches], ["Translation", "Replace Text", "Stacked Fix"])
        d = cdimage.Disc(cue)
        names = [r.name for r in d.files]
        self.assertEqual(names, ["0.BIN", "ABSTRACT.TXT", "BIBLIOGR.TXT", "CDDA2", "COPYRIGH.TXT", "EMPTY.BIN",
                                 "LATE.DAT", "NEWFILE.BIN", "X1TEST.BIN", "X2KEEP.BIN"])
        got = {r.name: d.read_file(r) for r in d.files if r.name != "CDDA2"}
        x1 = bytearray(self.x1)
        x1[0x10:0x14] = bytes.fromhex("CAFEF00D")
        self.assertEqual(got["X1TEST.BIN"], bytes(x1) + self.grow)
        self.assertEqual(got["X2KEEP.BIN"], self.x2)
        self.assertEqual(got["ABSTRACT.TXT"], b"patched abstract\r\n")
        self.assertEqual(got["NEWFILE.BIN"], b"brand new file")
        self.assertEqual(got["LATE.DAT"], b"version specific")
        self.assertEqual(got["EMPTY.BIN"], b"")
        # files laid out in DriveOrder order, then the new ones (version folder first)
        by = {r.name: r for r in d.files}
        lbas = [by[n].lba for n in ["COPYRIGH.TXT", "ABSTRACT.TXT", "BIBLIOGR.TXT", "0.BIN", "X2KEEP.BIN",
                                     "X1TEST.BIN", "LATE.DAT", "NEWFILE.BIN"]]
        self.assertEqual(lbas[0], 21)
        self.assertEqual(lbas, sorted(lbas))
        self.assertEqual(by["X1TEST.BIN"].lba + 5, by["LATE.DAT"].lba)       # 10120 bytes -> 5 sectors
        self.assertEqual(by["EMPTY.BIN"].lba, by["LATE.DAT"].lba)            # empty files take no space
        files_end = by["NEWFILE.BIN"].lba + 1
        self.assertEqual(sectors, files_end + 150)
        cd = by["CDDA2"]
        self.assertEqual((cd.lba, cd.size), (files_end + 300, 0))
        self.assertTrue(cd.is_cdda)
        # IP.BIN rewritten, PVD as the wizard writes it
        h = ipbin.parse(d.ip_raw)
        self.assertEqual((h.product, h.version, h.areas, h.peripherals), ("SF3TRANS", "V25.1", "JTUBKAEL", "AJE"))
        self.assertEqual(d.ip_raw[0x100:0xE00], make_ip()[0x100:0xE00])      # boot code kept,
        self.assertEqual(d.ip_raw[0xF0C:0x1800], make_ip()[0xF0C:0x1800])    # area code rewritten
        pvd = d.pvd
        self.assertEqual(pvd[8:40], b"SEGA SEGASATURN".ljust(32))
        self.assertEqual(pvd[40:72], b"SF3_TEST".ljust(32))
        # the builder counts the 150-sector CD-DA gap twice: 150 more than the image holds
        self.assertEqual(int.from_bytes(pvd[80:84], "little"), sectors + 150 + 150 + 40)
        self.assertEqual(pvd[190:318], b"SF3_TEST".ljust(128))
        self.assertEqual(pvd[318:446], b"SEGA ENTERPRISES,LTD.".ljust(128))
        self.assertEqual(pvd[446:574], b"CAMELOT,LTD.".ljust(128))
        self.assertEqual(pvd[702:739], b"COPYRIGH.TXT".ljust(37))
        self.assertEqual(pvd[813:830], b"0" * 16 + b"\0")
        self.assertEqual(int.from_bytes(pvd[140:144], "little"), 18)
        self.assertEqual(int.from_bytes(pvd[148:152], "big"), 19)
        # times: DFR files get "now", copied files their own mtime, untouched files keep theirs
        self.assertEqual(by["X1TEST.BIN"].time, bytes((126, 1, 2, 3, 4, 5, 0)))
        self.assertEqual(by["ABSTRACT.TXT"].time, bytes((100, 1, 1, 0, 0, 0, 0)))
        self.assertEqual(by["X2KEEP.BIN"].time, bytes((98, 6, 1, 3, 0, 0, 0)))   # 12:00 at GMT+9 -> 03:00 UTC
        # audio: 150 silent sectors then the source audio from INDEX 01
        raw = out.read_bytes()
        self.assertEqual(len(raw), (sectors + 150 + 40) * 2352)
        self.assertEqual(raw[sectors * 2352:(sectors + 150) * 2352], bytes(150 * 2352))
        self.assertEqual(raw[(sectors + 150) * 2352:], self.audio)
        self.assertEqual(cue.read_bytes().decode(), output.cue_text(out.name, sectors))
        # the wizard's CUE puts INDEX 00 on the data track's post-gap and INDEX 01 on the
        # silence, so "from INDEX 01" now includes those 150 silent sectors
        tracks = cdimage.parse_cue(cue)
        self.assertEqual(tracks[1].audio_from_index1(), bytes(150 * 2352) + self.audio)
        for lba in (0, 16, 17, 20, sectors - 151, sectors - 1):
            check_mode1_sector(self, raw[lba * 2352:(lba + 1) * 2352], lba)
        d.close()

    def test_reproducible(self):
        a = self.build(out_name="a.bin")[2].read_bytes()
        b = self.build(out_name="b.bin")[2].read_bytes()
        self.assertEqual(hashlib.sha1(a).digest(), hashlib.sha1(b).digest())

    def test_mismatch_fails(self):
        dfr_path = self.pkg_root / "Patches" / "Optional" / SERIAL / "X2KEEP.BIN.DFR"
        good = dfr_path.read_bytes()
        self.build(enable=["Optional"], out_name="ok.bin")
        dfr_path.write_bytes(("0,%02X,00\n" % (self.x2[0] ^ 1)).encode())
        try:
            with self.assertRaises(patcher.PatchError) as e:
                self.build(enable=["Optional"], out_name="bad.bin")
            self.assertIn("Old value %X is different than %X on line 1(0)" % (self.x2[0] ^ 1, self.x2[0]),
                          str(e.exception))
        finally:
            dfr_path.write_bytes(good)

    def test_case_only_name_clash_fails_like_the_wizard(self):
        extra = self.pkg_root / "Patches" / "Translation" / SERIAL / "x2keep.bin"
        extra.write_bytes(b"lower case copy")
        try:
            with self.assertRaises(patcher.PatchError) as e:
                self.build(out_name="clash.bin")
            self.assertIn("File already exists", str(e.exception))
        finally:
            extra.unlink()

    def test_content_identity(self):
        cue = self.build(out_name="cid.bin")[3]
        c = content_sha256(cue)
        if c is None:
            self.skipTest("saturn-recomp not importable")
        self.assertRegex(c, "^[0-9a-f]{64}$")
        self.assertEqual(matching_profiles(c), [])          # synthetic disc: no real profile
        self.assertEqual(matching_profiles("5a50848fa5fe94bbde5a9132a04655dd81cdbcd3af6eb23a0666c3e9e6973252"),
                         ["scenario3-translation-v25_1"])
        src = Path(__file__).resolve().parents[2] / ".local" / "saturn-recomp" / "src"
        sys.path.insert(0, str(src))
        from saturnrecomp import disc as srd
        m = srd.manifest(srd.Disc(str(cue)))
        self.assertEqual((m["product"], m["version"]), ("SF3TRANS", "V25.1"))
        self.assertIn("/NEWFILE.BIN", m["files"])
        self.assertNotIn("/CDDA2", m["files"])
        self.assertEqual(m["audio"]["02"]["sha1"], hashlib.sha1(bytes(150 * 2352) + self.audio).hexdigest())
        self.assertEqual(m["audio"]["02"]["frames"], 150 + 40)

    def test_cli(self):
        out = self.base / "cli" / "x.bin"
        log = io.StringIO()
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            rc = cli_main(["patch", str(self.cue), "--package", str(self.pkg_root), "-o", str(out),
                           "--any-disc", "--reproducible", "--no-content-id", "--work", str(self.base / "cliwork")])
            self.assertEqual(rc, 0, log.getvalue())
            self.assertTrue(out.with_suffix(".cue").exists())
            self.assertEqual(cli_main(["compare", str(out.with_suffix(".cue")), str(out.with_suffix(".cue"))]), 0)
            self.assertEqual(cli_main(["list", str(self.cue), "--package", str(self.pkg_root)]), 0)
        self.assertIn("[x] general       1  Translation", log.getvalue())

    def _refuse(self, target):
        log = io.StringIO()
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            rc = cli_main(["patch", str(self.cue), "--package", str(self.pkg_root), "-o", str(target),
                           "--any-disc"])
        self.assertEqual(rc, 2, log.getvalue())
        self.assertIn("refusing to write a disc image inside the sfiii-native checkout", log.getvalue())
        self.assertFalse(target.exists())
        self.assertFalse(target.with_suffix(".cue").exists())

    def test_cli_refuses_checkout_output(self):
        # The guard keeps game data out of a git checkout. Exercise it against an
        # invented checkout so it is tested wherever the suite runs, including the
        # packaged application payload, which has no .git and must not be written to.
        fake = self.base / "fake-checkout"
        (fake / ".git").mkdir(parents=True)
        with mock.patch.object(sf3cli, "REPO", fake.resolve()):
            self._refuse(fake / "tools" / "tests" / "nope.bin")
            self.assertFalse((fake / "tools").exists())
            (fake / ".git").rmdir()
            (fake / ".git").write_text("gitdir: elsewhere\n")   # a worktree's .git is a file
            self.assertTrue(sf3cli._inside_repo(fake / "x.bin"))
            (fake / ".git").unlink()
            self.assertFalse(sf3cli._inside_repo(fake / "x.bin"))   # not a checkout: no refusal
            self.assertFalse(sf3cli._inside_repo(self.base / "elsewhere.bin"))

    def test_cli_refuses_real_checkout(self):
        if not (sf3cli.REPO / ".git").exists():
            self.skipTest("not running from a git checkout (e.g. the packaged application payload)")
        self._refuse(Path(__file__).resolve().parent / "nope.bin")


if __name__ == "__main__":
    unittest.main()
