"""Invented-data tests for the SF3 playability harness (tools/sf3test)."""
import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sf3test import autoplay, diff, frames, memory_map, saves, sweep  # noqa: E402


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


class BattleUnits(unittest.TestCase):
    def test_read_units_and_aim(self):
        mm = memory_map
        raw = bytearray(mm.UNIT_STRIDE * mm.UNIT_COUNT)       # invented records, no game bytes
        for k, (x, y, f, hp) in {0: (10, 5, 0xC0, 12), 3: (2, 5, 0x40, 0), 7: (1, 1, 0x00, 9)}.items():
            e = k * mm.UNIT_STRIDE
            raw[e + mm.UNIT_X], raw[e + mm.UNIT_Y], raw[e + mm.UNIT_FLAGS] = x, y, f
            raw[e + mm.UNIT_HP:e + mm.UNIT_HP + 2] = hp.to_bytes(2, 'big')
        units = mm.read_units(lambda a, n: bytes(raw[:n]), 0)
        self.assertEqual(units, [(0, 10, 5, 0xC0, 12), (3, 2, 5, 0x40, 0)])
        pol = autoplay.Policy(1)
        out = pol.aim([(0, 10, 5, 0xC0, 12)], [(1, 7, 5, 0x40, 5), (2, 9, 9, 0x40, 0)], 0)
        moves = [b for b, n in out if b in (('LEFT',), ('RIGHT',), ('UP',), ('DOWN',))]
        self.assertEqual(moves[:2], [('LEFT',), ('LEFT',)])   # two steps, then next to the live one
        self.assertEqual(moves[2], ('UP',))                    # Attack in the command menu
        self.assertEqual(mm.lookup('scenario1-usa-v25_1')['units']['force'], 0x06032030)


class BattleTurns(unittest.TestCase):
    def test_prelude_and_outcome(self):
        ph = autoplay.prelude_phrase('w5,DOWN*7,A+C')
        self.assertEqual(ph, [((), 5), (('DOWN',), 7), ((), 10), (('A', 'C'), 6), ((), 10)])
        mm = memory_map
        raw = bytearray(mm.UNIT_STRIDE * mm.UNIT_COUNT)        # invented: one force unit, no enemies
        raw[mm.UNIT_FLAGS] = 0xC0
        raw[mm.UNIT_HP + 1] = 5
        units = dict(force=0, enemies=1)
        rd = lambda a, n: bytes(raw[:n]) if a == 0 else bytes(n)
        self.assertEqual(autoplay.battle_outcome(rd, units), 'won')
        raw[mm.UNIT_HP + 1] = 0
        self.assertEqual(autoplay.battle_outcome(rd, units), 'won')


    def test_stuck_unit_attacks_in_place(self):
        # invented: a unit that cannot step, an enemy on the next tile; the second idle turn attacks
        self.assertTrue(autoplay.next_to((5, 5), [(6, 5)]))
        self.assertFalse(autoplay.next_to((5, 5), [(7, 5), (6, 6)]))
        mm = memory_map
        raw = bytearray(mm.UNIT_STRIDE * 2)
        raw[mm.UNIT_FLAGS] = 0xC0                       # force record 0 at (5, 5), 9 HP
        raw[mm.UNIT_X] = raw[mm.UNIT_Y] = 5
        raw[mm.UNIT_HP + 1] = 9
        en = bytearray(raw)
        en[mm.UNIT_FLAGS] = 0x40                         # enemy record 0 at (6, 5)
        en[mm.UNIT_X] = 6

        class Side:
            def read(self, a, n):
                src = raw if a == 0 else en
                return bytes(src[:n]) + bytes(max(0, n - len(src)))

            def frame(self):
                class F:
                    width, height, rgb = 4, 8, bytes(4 * 8 * 3)
                return F()

        pol = autoplay.Policy(1)
        units = dict(force=0, enemies=1)
        first = autoplay.aimed_turn(Side(), units, pol, lambda b, n: None)
        second = autoplay.aimed_turn(Side(), units, pol, lambda b, n: None)
        self.assertNotIn(('UP',), [b for b, _ in first])
        self.assertIn((autoplay.RING['attack'],), [b for b, _ in second])
        self.assertEqual(pol.attacks, 1)


    def test_assist_writes(self):
        mm = memory_map
        raw = bytearray(mm.UNIT_STRIDE * mm.UNIT_COUNT)          # invented: force record 1, enemy record 0
        raw[mm.UNIT_STRIDE + mm.UNIT_FLAGS] = 0xC0
        raw[mm.UNIT_STRIDE:mm.UNIT_STRIDE + 4] = b'Hero'
        en = bytearray(mm.UNIT_STRIDE * mm.UNIT_COUNT)
        en[mm.UNIT_FLAGS] = 0x40
        en[mm.UNIT_HP + 1] = 14
        rd = lambda a, n: bytes(raw[:n]) if a == 0 else bytes(en[:n])
        w = dict(memory_map.assist_writes(rd, dict(force=0, enemies=0x1000)))
        self.assertEqual(w[mm.UNIT_STRIDE + mm.UNIT_HP], (999).to_bytes(2, 'big'))
        self.assertEqual(w[mm.UNIT_STRIDE + mm.UNIT_ATK], bytes([99, 99, 99]))
        self.assertNotIn(0x1000 + mm.UNIT_HP, w)
        raw[mm.UNIT_STRIDE:mm.UNIT_STRIDE + 4] = bytes(4)            # not a force record: no poke
        self.assertEqual(memory_map.assist_writes(rd, dict(force=0, enemies=0x1000)), [])
        raw[mm.UNIT_STRIDE:mm.UNIT_STRIDE + 4] = b'Hero'
        w = dict(memory_map.assist_writes(rd, dict(force=0, enemies=0x1000), enemy_hp=1))
        self.assertEqual(w[0x1000 + mm.UNIT_HP], b'\x00\x01')

    def test_player_tile(self):
        mm = memory_map
        self.assertEqual(mm.player_tile(0x04900000, 0x01B00000), (36, 13))
        self.assertEqual(mm.SC1_PLAYER['obj'] + mm.SC1_PLAYER['x'], 0x06044850)

    def test_scene_records_and_tile_events(self):
        raw = bytes.fromhex('0026020000000000000000000000000000270179000000000000000000000000')
        mm = memory_map
        self.assertEqual(mm.scene_records(raw), [(0, 0x26, 0x200), (1, 0x27, 0x179)])
        tiles = bytearray(4096)
        tiles[32 * 64 + 37], tiles[29 * 64 + 38], tiles[5] = 0x11, 0x51, 0x41
        self.assertEqual(mm.tile_events(bytes(tiles)), {(37, 32): (1, 1), (38, 29): (5, 1)})

    def test_live_byte_tables(self):
        mm = memory_map                                           # invented roster records
        raw = bytearray(mm.UNIT_STRIDE * mm.UNIT_COUNT)
        raw[0:4], raw[mm.UNIT_STRIDE:mm.UNIT_STRIDE + 3] = b'Hero', bytes([0xB8, 0xDE, 0xD7])
        raw[0x98:0x9A] = b'\x03\x01'                              # on the field, flags 0
        raw[mm.UNIT_MAX_HP + 1] = 20
        raw[mm.UNIT_STRIDE + mm.UNIT_FLAGS] = 0xE0                # stale flags, benched
        units = dict(force=0, enemies=0x1000, live=0x98)
        rd = lambda a, n: bytes(raw[:n]) if a == 0 else bytes(n)
        self.assertEqual([u[0] for u in mm.read_units(rd, 0, 0x98)], [0])
        w = dict(mm.assist_writes(rd, units))
        self.assertIn(mm.UNIT_HP, w)
        self.assertNotIn(mm.UNIT_STRIDE + mm.UNIT_HP, w)
        self.assertEqual(mm.lookup('scenario3-v25_1-redump')['units']['live'], 0x98)


class FakeSide:
    """An invented game: the battle id at the state block switches on after `battle_at` frames,
    the picture changes only while a button is held."""

    def __init__(self, profile, battle_at=None, reset_at=None):
        self.mm = memory_map.lookup(profile)
        self.frames, self.held, self.battle_at, self.pads = 0, (), battle_at, []
        self.reset_at, self.tick = reset_at, 5000

    def step(self):
        self.frames += 1
        self.tick = 0 if self.frames == self.reset_at else self.tick + 1

    def pad(self, buttons):
        self.held = tuple(buttons)
        self.pads.append((self.frames, self.held))

    def read(self, addr, n):
        if addr == self.mm['battle_id']:
            return bytes([0x81 if self.battle_at is not None and self.frames >= self.battle_at else 0])
        if addr == self.mm['map_id']:
            return bytes([0x36])
        if addr == self.mm['state_base']:
            lost = self.reset_at is not None and self.frames >= self.reset_at and self.tick < 9000
            return (0 if lost else memory_map.PAYLOAD_SIZE[3] - 8).to_bytes(4, 'big')
        if addr == self.mm['tick']:
            return self.tick.to_bytes(4, 'big')
        return bytes(n)

    def frame(self):
        class F:
            rgb = bytes([self.frames % 251 if self.held else 0]) * 64
        return F()


class Autoplay(unittest.TestCase):
    P = 'scenario2-v25_1-v1_003'   # a profile without a unit table: the probing policy

    def test_same_seed_same_script(self):
        a = autoplay.play(FakeSide(self.P), self.P, 3000, 5)
        b = autoplay.play(FakeSide(self.P), self.P, 3000, 5)
        c = autoplay.play(FakeSide(self.P), self.P, 3000, 6)
        self.assertEqual(a['sha1'], b['sha1'])
        self.assertNotEqual(a['sha1'], c['sha1'])
        self.assertTrue(a['script'].startswith('0:'))

    def test_battle_state_changes_policy_and_is_logged(self):
        side = FakeSide(self.P, battle_at=600)
        r = autoplay.play(side, self.P, 3000, 1)
        self.assertEqual([e[2] for e in r['events']][:2], [0, 0x81])
        after = [b for f, b in r['presses'] if f > r['events'][1][0]]
        self.assertIn('C', after)
        self.assertTrue(set(after) & set(autoplay.DIRS))

    def test_town_walker_spirals_and_talks(self):
        r = autoplay.play(FakeSide(self.P), self.P, 3000, 2, walker=True)
        pressed = {b for f, b in r['presses']}
        self.assertTrue(set(autoplay.DIRS) <= pressed and {'A', 'C'} <= pressed)
        self.assertGreater(r['legs'], 4)

    def test_battle_with_no_unit_moving_ends_idle(self):
        P = 'scenario3-v25_1-redump'
        units = memory_map.lookup(P)['units']

        class Frozen(FakeSide):
            """One force and one enemy record, both live, that never move (Sc2 free-walk after a win)."""
            def read(self, addr, n):
                for base, x in ((units['force'], 3), (units['enemies'], 9)):
                    if base <= addr < base + 0xB0 * 60:
                        rec = bytearray(0xB0 * 60)
                        for k in range(1):
                            o = k * 0xB0
                            rec[o] = 0x41
                            rec[o + memory_map.UNIT_X], rec[o + memory_map.UNIT_Y] = x, 5
                            rec[o + memory_map.UNIT_HP:o + memory_map.UNIT_HP + 2] = (7).to_bytes(2, 'big')
                            rec[o + memory_map.UNIT_MAX_HP:o + memory_map.UNIT_MAX_HP + 2] = (9).to_bytes(2, 'big')
                            rec[o + memory_map.UNIT_FLAGS], rec[o + 0x98], rec[o + 0x99] = 0xC0, 1, 1
                        off = addr - base
                        return bytes(rec[off:off + n])
                return super().read(addr, n)

            def frame(self):
                top = bytes([self.frames % 250, 0, 0]) * (320 * 100)
                class F:
                    width, height, rgb = 320, 224, top + bytes(320 * 124 * 3)
                return F()
        r = autoplay.play(Frozen(P, battle_at=0), P, 60000, 1, walker=True)
        self.assertIn('idle', [o for f, o in r['outcomes']])
        self.assertEqual([o for f, o in r['outcomes']].count('idle'), 1)

    def test_back_at_title_reloads(self):
        def reload(side):
            for _ in range(200):
                side.step()
            side.tick = 9000
        r = autoplay.play(FakeSide(self.P, reset_at=1000), self.P, 3000, 1, reload=reload)
        self.assertEqual(len(r['resets']), 1)
        self.assertTrue(1000 <= r['resets'][0] < 1400)
        self.assertIn((r['resets'][0], -1, -1), r['events'])

    def test_stuck_picture_escapes(self):
        pol = autoplay.Policy(3)
        h = pol.heading
        phrase = pol.next_phrase(dict(map=1, battle=0, stuck=True))
        self.assertIn(('B',), [b for b, n in phrase])
        self.assertNotEqual(pol.heading, h)

    def test_script_and_replay(self):
        presses = [(0, 'UP'), (10, ''), (20, 'A+C')]
        self.assertEqual(autoplay.script_text(presses, 100), '100:UP,110:,120:A+C')
        side = FakeSide(self.P)
        autoplay.replay(side, presses, 30)
        self.assertEqual(side.pads, [(0, ('UP',)), (10, ()), (20, ('A', 'C'))])


class RealCoverage(unittest.TestCase):
    """An invented module at 06001000: f0 (bsr f1), f1 (mov.l literal -> f2), f2, an unreachable f3,
    and f4 named only from a data word (a pointer table); module B holds a copy of f2."""

    def module(self):
        from sf3test import realcov
        img = bytearray(0x40)
        img[0x00:0x02] = (0xB000 | ((0x10 - 0x04) // 2)).to_bytes(2, 'big')   # 06001000 bsr 06001010
        img[0x10:0x12] = (0xD000 | 1).to_bytes(2, 'big')                     # 06001010 mov.l @(4,pc) -> 06001018
        img[0x18:0x1C] = (0x06001020).to_bytes(4, 'big')
        img[0x20:0x22] = b'\x00\x09'                                         # f2: nop
        img[0x28:0x2A] = b'\x00\x0b'                                         # f3: rts
        img[0x3C:0x40] = (0x06001030).to_bytes(4, 'big')                     # data word -> f4
        img[0x30:0x32] = b'\x00\x0b'
        text = '# A: A.BIN at 06001000, 64 bytes, sha1 0\n# address\tfunction\tkind\tfile\tline\n'
        for f, n in ((0x1000, 2), (0x1010, 2), (0x1020, 1), (0x1028, 1), (0x1030, 1)):
            for i in range(n):
                text += f'{0x06000000 + f + 2 * i:08X}\t{0x06000000 + f:08X}\tinsn\tx.cpp\t1\n'
        a = realcov.parse_map(text)
        b = realcov.parse_map('# B: B.BIN at 06001020, 2 bytes, sha1 1\n06001020\t06001020\tinsn\tx.cpp\t1\n')
        return realcov, [a, b], {'A': bytes(img), 'B': b'\x00\x09'}

    def test_reachability_duplicates_and_bytes(self):
        realcov, mods, images = self.module()
        rows, tot = realcov.analyze(mods, images, {}, {('A', 0x06001010)})
        a = rows[0]
        self.assertEqual(a['functions'], 5)
        self.assertEqual(a['unreachable'], 1)              # f3 only
        self.assertEqual(rows[1]['duplicate'], 1)          # B's copy of f2
        self.assertEqual(a['real'], 4)
        self.assertEqual(a['ran_bytes'], 4)
        self.assertAlmostEqual(a['pct'], 100 * 4 / a['real_bytes'])
        self.assertEqual(realcov.ran_set(['A 06001010 2 1\nA 06001012 0 0']), {('A', 0x06001010)})
