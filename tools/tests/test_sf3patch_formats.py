"""sf3patch: the small formats (metadata JSON, DFR, IP.BIN, CUE, EDC/ECC), synthetic data only."""
import functools
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.sf3patch import conflicts, dfr, dotnet, edcecc, ipbin, isobuild, netjson, output, package, selection


class NetJson(unittest.TestCase):
    def test_leading_zero_is_octal_like_newtonsoft(self):
        self.assertEqual(netjson.loads('{"priority": 040}')["priority"], 32)
        self.assertEqual(netjson.loads('{"priority": 001}')["priority"], 1)
        self.assertEqual(netjson.loads('{"p": 0x1F}')["p"], 31)

    def test_lenient_syntax(self):
        doc = netjson.loads("{ // comment\n 'a': 1, b: [1,2,], /* c */ \"c\": true, }")
        self.assertEqual(doc, {"a": 1, "b": [1, 2], "c": True})

    def test_last_duplicate_wins_and_trailing_text_fails(self):
        self.assertEqual(netjson.loads('{"a":1,"a":2}')["a"], 2)
        with self.assertRaises(netjson.JsonError):
            netjson.loads('{"a":1} x')

    def test_bom(self):
        self.assertEqual(netjson.read_text(b"\xef\xbb\xbf{}"), "{}")

    def test_conversions(self):
        self.assertIs(netjson.to_net_bool("True"), True)
        self.assertIs(netjson.to_net_bool(0), False)
        with self.assertRaises(netjson.JsonError):
            netjson.to_net_bool(netjson.MISSING)
        self.assertEqual(netjson.to_net_int(2.5), 2)
        self.assertEqual(netjson.to_net_int(3.5), 4)
        self.assertEqual(netjson.to_net_int(" 12 "), 12)
        self.assertEqual(netjson.category_string("BugFixes").lower(), "bugfixes")
        with self.assertRaises(netjson.JsonError):
            netjson.category_string(netjson.MISSING)


class DotNet(unittest.TestCase):
    def test_introsort_sorts(self):
        rnd = random.Random(1)
        for n in (0, 1, 2, 3, 5, 16, 17, 40, 200):
            xs = [rnd.randrange(50) for _ in range(n)]
            ys = list(xs)
            dotnet.introsort(ys, lambda a, b: a - b)
            self.assertEqual(ys, sorted(xs))

    def test_introsort_is_unstable_like_dotnet(self):
        # 20 equal keys: .NET's pivoting reorders equal elements; a stable sort would not.
        items = [(0, i) for i in range(20)]
        dotnet.introsort(items, lambda a, b: a[0] - b[0])
        self.assertEqual(sorted(items), [(0, i) for i in range(20)])
        self.assertNotEqual(items, [(0, i) for i in range(20)])

    def test_culture_order(self):
        words = ["b", "B", "a", "_x", "1", "a b", "ab", "A"]
        got = sorted(words, key=functools.cmp_to_key(dotnet.culture_compare))
        self.assertEqual(got, ["_x", "1", "a", "A", "a b", "ab", "b", "B"])

    def test_text_helpers(self):
        self.assertEqual(dotnet.trim("\u3000 x \t"), "x")
        self.assertEqual(dotnet.utf16_len("a\U0001F600"), 3)
        self.assertEqual(dotnet.pad_right("ab", 4), "ab  ")
        self.assertEqual(dotnet.parse_hex_int(" ff "), 255)
        self.assertEqual(dotnet.parse_hex_int("FFFFFFFF"), -1)


class DFR(unittest.TestCase):
    def test_replace_and_comments(self):
        p = dfr.parse(b"; header\r\n2,4142,5859 ; note\r\n\r\n")
        self.assertEqual(dfr.apply(p, b"xxABzz"), b"xxXYzz")

    def test_mismatch_is_reported_like_the_wizard(self):
        p = dfr.parse(b"0,41,42\n")
        with self.assertRaises(dfr.DFRError) as e:
            dfr.apply(p, b"Z", "X1TEST")
        self.assertIn("Old value 41 is different than 5A on line 1(0)", str(e.exception))
        self.assertEqual(dfr.check(p, b"Z"), [(0, 0x41, 0x5A, 1)])

    def test_append_quirk(self):
        p = dfr.parse(b"1,,AABB\n")
        self.assertEqual(dfr.apply(p, b"0123"), b"0123\xaa\xbb")   # offset inside: still the end
        p = dfr.parse(b"6,,AA\n")
        self.assertEqual(dfr.apply(p, b"01"), b"01\0\0\0\0\xaa")

    def test_bytes_past_end_are_appended(self):
        p = dfr.parse(b"2,41424344,61626364\n")
        self.assertEqual(dfr.apply(p, b"01A"), b"01abcd")

    def test_truncate_stops(self):
        p = dfr.parse(b"2,\n0,30,39\n")
        self.assertEqual(dfr.apply(p, b"01234"), b"01")

    def test_length_mismatch(self):
        with self.assertRaises(dfr.DFRError):
            dfr.parse(b"0,4142,58\n")

    def test_line_numbers_count_blank_lines(self):
        p = dfr.parse(b"\n\r\n0,41,42\r")
        self.assertEqual(p.ops[0].line, 3)


class IPBin(unittest.TestCase):
    def raw(self):
        b = bytearray(32768)
        fields = [b"SEGA SEGASATURN ", b"SEGA TP T-999   ", b"GS-9999   ", b"V1.003", b"19980101",
                  b"CD-1/1  ", b"J         ", b"      ", b"JAMKST          ",
                  b"SHINING FORCE 3 SCENARIO 9".ljust(112), bytes(16),
                  (0x1800).to_bytes(4, "big"), bytes(4), bytes(4), bytes(4),
                  (0x06004000).to_bytes(4, "big"), bytes(4), bytes(8)]
        b[0:256] = b"".join(fields)
        b[0x100:0x200] = bytes(range(256))
        return bytes(b)

    def test_parse(self):
        h = ipbin.parse(self.raw())
        self.assertEqual((h.product, h.version, h.areas), ("GS-9999", "V1.003", "J"))

    def test_wizard_rewrite(self):
        out = ipbin.wizard_rewrite(self.raw(), "25.1")
        self.assertEqual(len(out), 32768)
        self.assertEqual(out[0x20:0x2A], b"SF3TRANS  ")
        self.assertEqual(out[0x2A:0x30], b"V25.1 ")
        self.assertEqual(out[0x30:0x38], b"20240825")
        self.assertEqual(out[0x40:0x4A], b"JTUBKAEL  ")
        self.assertEqual(out[0x50:0x60], b"AJE".ljust(16))
        title = b"SHINING FORCE 3 SCENARIO 9".ljust(32) + b"TRANSLATION".ljust(16) + \
            b"VERSION 25.1".ljust(16) + b"SF3TRANS.SHININGFORCECENTRAL.COM"
        self.assertEqual(out[0x60:0xD0], title.ljust(112))
        self.assertEqual(out[0xE0:0xE4], (0x1800).to_bytes(4, "big"))
        self.assertEqual(out[0xF0:0xF4], (0x06004000).to_bytes(4, "big"))
        self.assertEqual(out[0x100:0x200], bytes(range(256)))   # boot code untouched
        self.assertEqual(out[0xE00:0xE04], (150998688).to_bytes(4, "little"))
        self.assertEqual(out[0xE04:0xE20], b"For JAPAN.".ljust(28))
        self.assertEqual(out[0xE20 + 4:0xE20 + 4 + 11], b"For TAIWAN ")
        end = 0xE00 + 8 * 32
        self.assertEqual(out[end:end + 12], (725615056).to_bytes(4, "little") +
                         (150997248).to_bytes(4, "little") + (4194310).to_bytes(4, "little"))


class Cue(unittest.TestCase):
    def test_text(self):
        t = output.cue_text("GS-9188_V1.003.bin", 130000)
        self.assertEqual(t, 'FILE "GS-9188_V1.003.bin" BINARY\r\n  TRACK 01 MODE1/2352\r\n    INDEX 01 00:00:00\r\n'
                            '  TRACK 02 AUDIO\r\n    INDEX 00 28:51:25\r\n    INDEX 01 28:53:25\r\n')


# --- independent EDC/ECC checks: a bitwise CRC and Reed-Solomon syndromes over GF(2^8)

def _crc_edc(data):
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ (0xD8018001 if c & 1 else 0)
    return c


def _gmul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a <<= 1
        if a & 0x100:
            a ^= 0x11D
        b >>= 1
    return r


def _syndromes_ok(word):
    s0 = s1 = 0
    for c in word:
        s0 ^= c
        s1 = _gmul(s1, 2) ^ c
    return s0 == 0 and s1 == 0


def check_mode1_sector(tc, raw, lba):
    tc.assertEqual(raw[0:12], edcecc.SYNC)
    tc.assertEqual(raw[12:15], edcecc.msf(lba))
    tc.assertEqual(raw[15], 1)
    tc.assertEqual(int.from_bytes(raw[2064:2068], "little"), _crc_edc(raw[0:2064]))
    tc.assertEqual(raw[2068:2076], bytes(8))
    body = raw[12:]
    for m in range(86):   # P: 86 columns of 26 bytes
        tc.assertTrue(_syndromes_ok([body[m + 86 * k] for k in range(26)]), "P %d" % m)
    for m in range(52):   # Q: 52 diagonals of 43 bytes plus 2 parity bytes
        idx = (m >> 1) * 86 + (m & 1)
        word = []
        for _ in range(43):
            word.append(body[idx])
            idx += 88
            if idx >= 2236:
                idx -= 2236
        word += [body[2236 + m], body[2236 + 52 + m]]
        tc.assertTrue(_syndromes_ok(word), "Q %d" % m)


class EdcEcc(unittest.TestCase):
    def test_sectors_against_independent_checks(self):
        rnd = random.Random(7)
        users = [bytes(2048), bytes(rnd.randrange(256) for _ in range(2048))]
        for lba, u in ((0, users[0]), (16, users[1]), (300000, users[1])):
            check_mode1_sector(self, edcecc.mode1(u, lba), lba)

    def test_batch_matches_single(self):
        rnd = random.Random(3)
        user = bytes(rnd.randrange(256) for _ in range(2048 * 70))
        many = edcecc.mode1_many(user, 1000)
        for k in (0, 33, 69):
            self.assertEqual(many[k * 2352:(k + 1) * 2352], edcecc.mode1(user[k * 2048:(k + 1) * 2048], 1000 + k))


class IsoNames(unittest.TestCase):
    def test_normalize_and_identifier(self):
        self.assertEqual(isobuild.normalize_file_name("CDDA2"), "CDDA2.;1")
        self.assertEqual(isobuild.normalize_file_name("X1.BIN"), "X1.BIN;1")
        self.assertEqual(isobuild.identifier_text("X1.BIN"), "X1.BIN;1\0")
        self.assertEqual(isobuild.identifier_text("X12.BIN"), "X12.BIN;1")
        self.assertEqual(isobuild.record_size("X1.BIN"), 42)
        self.assertEqual(isobuild.record_size("CDDA2"), 54)

    def test_member_order(self):
        names = ["X1.BIN;1", "X.BIN;1", "X10.BIN;1", "A.TXT;1", "CDDA2.;1", "X_1.BIN;1", "0.BIN;1"]
        dotnet.introsort(names, isobuild.member_compare)
        self.assertEqual(names, ["0.BIN;1", "A.TXT;1", "CDDA2.;1", "X.BIN;1", "X1.BIN;1", "X10.BIN;1", "X_1.BIN;1"])


def _meta(d, **kw):
    d.mkdir(parents=True, exist_ok=True)
    body = ", ".join('"%s": %s' % (k, v) for k, v in kw.items())
    (d / "metadata.json").write_text("{%s}" % body)


class Selection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "wiz"
        for sub in ("Patches", "Custom Mods", "DriveOrder", "Data"):
            (root / sub).mkdir(parents=True)
        (root / "Data" / "data.json").write_text('{"version": "25.1"}')
        (root / "DriveOrder" / "GS-9999.txt").write_text("A.BIN , 1\r\n")
        P = root / "Patches"
        _meta(P / "Zed", text='"Zed"', category='"General"', enabled="true", priority="010")
        _meta(P / "Alpha", text='"Alpha"', category='"General"', enabled="true", priority="8")
        _meta(P / "Fix", text='"Fix"', category='"BugFixes"', enabled="false")
        _meta(P / "Other", text='"Other"', category='"QoL"', enabled="true")
        _meta(P / "Weird", text='"Weird"', category='"Misc"', enabled="true")
        for name in ("Zed", "Alpha", "Fix", "Weird"):
            (P / name / "gs-9999").mkdir()
            (P / name / "gs-9999" / "A.BIN.DFR").write_text("0,00,01\n")
        (P / "Other" / "MK-00000").mkdir()
        (P / "Other" / "MK-00000" / "A.BIN.DFR").write_text("0,00,01\n")
        _meta(root / "Custom Mods" / "Late", text='"Late"', category='"general"', enabled="1")
        (root / "Custom Mods" / "Late" / "GS-9999" / "V1.000").mkdir(parents=True)
        (root / "Custom Mods" / "Late" / "GS-9999" / "V1.000" / "B.BIN").write_text("new")
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def test_wizard_listing_and_order(self):
        pkg = package.load(self.root, Path(self.tmp.name) / "work")
        self.assertEqual(pkg.version, "25.1")
        ordered, errors = selection.listed(pkg.patches, "GS-9999", "V1.000")
        self.assertEqual(errors, [])
        # octal 010 == 8 ties with Alpha's 8 and falls back to the text order
        self.assertEqual([p.name for p in ordered], ["Alpha", "Zed", "Late", "Fix"])
        self.assertEqual([p.priority for p in ordered], [8, 8, 9999, 9999])
        self.assertEqual([p.name for p in selection.choose(ordered)], ["Alpha", "Zed", "Late"])
        chosen = selection.choose(ordered, enable=["fix"], disable=["Custom Mods/Late"])
        self.assertEqual([p.name for p in chosen], ["Alpha", "Zed", "Fix"])
        self.assertEqual([p.name for p in selection.choose(ordered, only=["Late"])], ["Late"])
        with self.assertRaises(package.PackageError):
            selection.choose(ordered, enable=["nope"])

    def test_broken_metadata_is_an_error(self):
        (self.root / "Patches" / "Zed" / "metadata.json").write_text('{"text": "Zed", "enabled": true}')
        pkg = package.load(self.root, Path(self.tmp.name) / "work")
        ordered, errors = selection.listed(pkg.patches, "GS-9999", "V1.000")
        self.assertEqual(len(errors), 1)
        self.assertIn("Error with patch file:Zed", errors[0])

    def test_conflicts(self):
        pkg = package.load(self.root, Path(self.tmp.name) / "work")
        ordered, _ = selection.listed(pkg.patches, "GS-9999", "V1.000")
        issues = conflicts.check(selection.choose(ordered), ["A.BIN"], "GS-9999", "V1.000")
        self.assertEqual([s for s, _ in issues], ["error"])          # Alpha and Zed both write A.BIN[0]
        (self.root / "Patches" / "Zed" / "gs-9999" / "A.BIN.DFR").write_text("0,01,02\n")
        pkg = package.load(self.root, Path(self.tmp.name) / "work")
        ordered, _ = selection.listed(pkg.patches, "GS-9999", "V1.000")
        issues = conflicts.check(selection.choose(ordered), ["A.BIN"], "GS-9999", "V1.000")
        self.assertEqual([s for s, _ in issues], ["warning"])        # stacked on purpose

    def test_supersede(self):
        base = [package.PatchDir(Path("/x/Rogan Sprite Fix"), "Patches"), package.PatchDir(Path("/x/Keep v1"), "Patches")]
        mods = [package.PatchDir(Path("/m/Rogan Sprite Fix v5"), "mod:a"), package.PatchDir(Path("/m/Keep v2"), "mod:b")]
        out, notes = selection.layer(base, mods)
        self.assertEqual([p.name for p in out], ["Keep v1", "Rogan Sprite Fix v5", "Keep v2"])
        self.assertTrue(any("superseded" in n for n in notes))
        self.assertTrue(any(n.startswith("warning") for n in notes))
        out, _ = selection.layer(base, mods, supersede=False)
        self.assertEqual(len(out), 4)
        mri = package.PatchDir(Path("/m/Magic Resistance Icons v2"), "mod:c")
        mri.enabled = True
        _, notes = selection.layer([], [mri])
        self.assertFalse(mri.enabled)
        self.assertTrue(any(n.startswith("unticked") for n in notes))


if __name__ == "__main__":
    unittest.main()
