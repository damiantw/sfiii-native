"""Invented-data tests for the SF3 playability harness (tools/sf3test)."""
import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sf3test import diff, frames, memory_map, saves, sweep  # noqa: E402


def sf3_payload(n, fill=7):
    body = bytes((i * fill) & 0xFF for i in range(n - 8))
    return memory_map.fix_checksum(b'\0' * 8 + body)


def rec(name='SFORCE31_01', n=300):
    return dict(name=name, language=1, comment=b'TEST', date=12345, data=sf3_payload(n))


def png(w, h, rgb):
    raw = b''.join(b'\0' + bytes(rgb) * w for _ in range(h))
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


class Saves(unittest.TestCase):
    def test_bram_round_trip_interleaved_and_raw(self):
        recs = [rec('SFORCE31_01', 300), rec('SFORCE31_02', 1000)]
        for inter in (True, False):
            img = saves.build_bram(recs, interleave=inter)
            self.assertEqual(len(img), 0x10000 if inter else 0x8000)
            back = saves.parse_bram(img)
            self.assertEqual([r['name'] for r in back], ['SFORCE31_01', 'SFORCE31_02'])
            self.assertEqual([r['data'] for r in back], [r['data'] for r in recs])
            self.assertTrue(all(saves.check_sf3(r) for r in back))

    def test_native_round_trip_sorted(self):
        recs = [rec('SFORCE31_02'), rec('SFORCE31_01')]
        back = saves.parse_native(saves.native_backup(recs))
        self.assertEqual([r['name'] for r in back], ['SFORCE31_01', 'SFORCE31_02'])
        self.assertEqual(back[0]['date'], 12345)
        self.assertEqual(saves.load_any(saves.native_backup(recs))[1]['data'], recs[0]['data'])

    def test_bup(self):
        r = rec()
        head = bytearray(64)
        head[:4] = b'Vmem'
        head[0x10:0x10 + 11] = r['name'].encode()
        head[0x1C:0x20] = b'TEST'
        head[0x27] = 1
        struct.pack_into('>II', head, 0x28, 99, len(r['data']))
        out = saves.load_any(bytes(head) + r['data'])
        self.assertEqual(out[0]['name'], 'SFORCE31_01')
        self.assertEqual(out[0]['data'], r['data'])

    def test_full(self):
        with self.assertRaises(ValueError):
            saves.build_bram([rec(n=40000)])

    def test_checksum_and_map_edit(self):
        p = memory_map.with_map(sf3_payload(200), 0x2C, 3)
        self.assertEqual(p[memory_map.MAP_ID], 0x2C)
        self.assertEqual(p[memory_map.BATTLE_ID], 3)
        self.assertTrue(saves.check_sf3(dict(name='SFORCE31_01', data=p)))
        self.assertFalse(saves.check_sf3(dict(name='SFORCE31_01', data=p[:-1] + b'\x01')))


class MemoryMap(unittest.TestCase):
    def test_lookup(self):
        mm = memory_map.lookup('scenario1-usa-v25_1.json')
        self.assertEqual(mm['map_id'], mm['state_base'] + 0x1D)
        with self.assertRaises(KeyError):
            memory_map.lookup('nope')


class Frames(unittest.TestCase):
    def test_black_and_mean(self):
        self.assertTrue(frames.stats(png(4, 3, (0, 1, 0)))['black'])
        s = frames.stats(png(4, 3, (90, 90, 90)))
        self.assertFalse(s['black'])
        self.assertAlmostEqual(s['mean'], 90, delta=0.5)


class Sweep(unittest.TestCase):
    def test_inputs_deterministic(self):
        a = sweep.input_script(sweep.menu_inputs() + sweep.explore_inputs(6000, 7000, 3))
        self.assertEqual(a, sweep.input_script(sweep.menu_inputs() + sweep.explore_inputs(6000, 7000, 3)))
        self.assertTrue(a.startswith('1100:START,1108:,'))

    def test_analyze(self):
        ok_log = 'stopped (VBlank limit) after 8000 VBlanks\n'
        prog = [(10, 0x55, 0), (5300, 0x2C, 0), (6000, 0x30, 1)]
        shots = [(6000, dict(sha1='a', black=False)), (7000, dict(sha1='b', black=False))]
        r = sweep.analyze(ok_log, prog, shots, 8000, expect=(0x2C, 0))
        self.assertEqual((r['status'], r['maps'], r['battles'], r['loaded_at']), ('ok', [0x2C, 0x30], [1], 5300))
        crash = '[x] FATAL: call to 06041234, not an entry of an active module (from pr 06040000)\n'
        r = sweep.analyze(crash, prog, shots, 8000)
        self.assertEqual(r['status'], 'crash')
        self.assertEqual(r['unresolved_calls'], [['06041234', '06040000']])
        stall = 'STALL: no VBlank for 5 s after VBlank 6100\n'
        self.assertEqual(sweep.analyze(stall, prog, shots, 8000)['status'], 'hang')
        same = [(v, dict(sha1='z', black=False)) for v in (6000, 6600, 7200)]
        self.assertEqual(sweep.analyze(ok_log, prog, same, 8000)['status'], 'frozen')
        # the record's map id already in the block before the load: nothing logged at the load
        held = [(10, 0x46, 0x70), (5500, 0x09, 0)]
        r = sweep.analyze(ok_log, held, shots, 8000, expect=(0x46, 0), loaded_after=5000)
        self.assertEqual((r['status'], r['maps'], r['loaded_at'], r['load_inferred']), ('ok', [0x09, 0x46], 5000, True))
        r = sweep.analyze(ok_log, [(10, 0x47, 0)], shots, 8000, expect=(0x46, 0), loaded_after=5000)
        self.assertEqual(r['status'], 'no-load')

    def test_coverage_union(self):
        a = 'M1 06000000 10 1\nM1 06000010 5 0\nM2 06001000 7 0\n'
        b = 'M1 06000010 5 1\nM2 06001000 7 0\n'
        self.assertEqual(sweep.coverage_union([a, b]), {'M1': [2, 2, 15, 15], 'M2': [1, 0, 7, 0]})

    def test_matrix(self):
        row = sweep.analyze('stopped (VBlank limit) after 10 VBlanks\n', [(1, 1, 0)], [], 10)
        row.update(id='save:x:01', kind='save', map=1, battle=0, last_shot=None)
        rep = dict(profile='p', vblanks=10, results=[row])
        self.assertIn('save:x:01', sweep.matrix(rep))


class Diff(unittest.TestCase):
    def test_compare(self):
        a = bytearray(64)
        b = bytearray(64)
        a[memory_map.MAP_ID] = b[memory_map.MAP_ID] = 5
        b[40] = b[41] = b[50] = 1
        p = diff.compare_point(100, dict(block=bytes(a)), dict(block=bytes(b), frame_no=120))
        self.assertEqual((p['block_bytes_differing'], p['block_ranges']), (3, [[40, 42], [50, 51]]))
        self.assertFalse(p['state_match'])
        q = diff.compare_point(200, dict(block=bytes(a)), dict(block=bytes(a)))
        s = diff.summarize([p, q], loaded_from=100)
        self.assertEqual((s['points'], s['state_matches'], s['same_map'], s['first_divergence']), (2, 1, 2, 100))

    def test_dots_over(self):
        class F:
            def __init__(self, w, h, rgb):
                self.width, self.height, self.rgb = w, h, rgb
        ours = F(2, 1, bytes([10, 10, 10, 200, 0, 0]))
        theirs = F(4, 1, bytes([0] * 3 + [14, 10, 10, 100, 0, 0] + [0] * 3))
        self.assertEqual(diff.dots_over(ours, theirs, 8), 1)
        self.assertEqual(diff.dots_over(ours, theirs, 100), 0)


if __name__ == '__main__':
    unittest.main()


class BeetleReference(unittest.TestCase):
    def test_prepare_links_bios_and_writes_a_plain_bkr(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / 'bios').mkdir()
            (t / 'bios' / 'invented.bin').write_bytes(b'not a bios')
            (t / 'bios' / 'notes.txt').write_text('skip me')
            for d in ('core-save', 'core-system'):
                (t / 'w' / d).mkdir(parents=True)
            r = rec()
            diff.prepare_beetle(t / 'w', '/discs/game.cue', r, t / 'bios')
            self.assertEqual(sorted(p.name for p in (t / 'w' / 'core-system').iterdir()), ['invented.bin'])
            bkr = (t / 'w' / 'core-save' / 'game.bkr').read_bytes()
            self.assertEqual(len(bkr), 0x8000)
            self.assertTrue(bkr.startswith(saves.MAGIC))   # not byte-interleaved
            self.assertEqual(saves.parse_bram(bkr)[0]['data'], r['data'])


class FatalLines(unittest.TestCase):
    def test_both_fatal_forms(self):
        log = 'FATAL: unresolved jump\n[  55.780 FATAL] returned to 06000010, expected 06000020\n'
        self.assertEqual([m.group(1).strip() for m in sweep.FATAL.finditer(log)],
                         ['unresolved jump', 'returned to 06000010, expected 06000020'])


class InvalidMaps(unittest.TestCase):
    def test_entries_are_map_ids_with_a_reason(self):
        for sc, maps in memory_map.INVALID_MAPS.items():
            self.assertIn(sc, memory_map.PAYLOAD_SIZE)
            for m, why in maps.items():
                self.assertTrue(0 <= m <= 0xFF and why)
