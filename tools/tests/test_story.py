"""Invented-data tests for the story driver (tools/sf3test/story.py, sf3-story.py) and a check
that every committed acceptance segment (tools/story-replays) is pad presses only."""
import importlib.util
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from sf3test import story                     # noqa: E402
from sf3test.autoplay import flat_blue_rows, plan_step   # noqa: E402

GOOD = '\n'.join(['# sf3 story segment v1', 'profile p', 'record save:x:01', 'seed 1', 'assist none',
                  'clock 2026-01-01T00:00:00', 'end_vblank 2000', 'end_ram_sha1 0123456789abcdef', 'input',
                  '1100 pad START', '1108 pad ', '1500 pad C+UP']) + '\n'

class StoryTest(unittest.TestCase):
    def test_compare(self):
        self.assertEqual(story.compare(b'\x01\x00', b'\x03\x80'), (2, 0))
        self.assertEqual(story.compare(b'\x07', b'\x01'), (0, 2))
        self.assertTrue(story.reached(b'\x03', b'\x01'))
        self.assertFalse(story.reached(b'\x01', b'\x03'))

    def test_hms_and_playtime(self):
        self.assertEqual(story.hms(60 * 3661), '1:01:01')
        rec = bytes(16) + (60 * 90).to_bytes(4, 'big') + bytes(0x400)
        self.assertEqual(story.playtime(rec), 5400)
        order = story.story_order([{'id': 'b', 'record': {'data': rec}},
                                   {'id': 'a', 'record': {'data': bytes(0x420)}}])
        self.assertEqual([t['id'] for t in order], ['a', 'b'])

    def test_segment_round_trip(self):
        header = {'profile': 'p', 'end_vblank': '42'}
        actions = [(1100, 'pad', 'START'), (1108, 'pad', ''), (2000, 'poke', '0602F6F0', '0001')]
        h, a = story.parse_segment(story.segment_text(header, actions))
        self.assertEqual(h, header)
        self.assertEqual(a, actions)
        self.assertEqual(story.actions_sha1(a), story.actions_sha1(actions))

    def test_check_committed(self):
        self.assertEqual(story.check_committed(GOOD), [])
        poke = GOOD + '2000 poke 0602F6F0 03e7\n'
        self.assertTrue(any('pads only' in p for p in story.check_committed(poke)))
        self.assertTrue(story.check_committed(GOOD.replace('assist none', 'assist party')))
        self.assertTrue(story.check_committed(GOOD.replace('clock 2026-01-01T00:00:00\n', '')))
        self.assertTrue(story.check_committed(GOOD.replace('profile p', 'profile p\nfont 00ff')))
        self.assertTrue(story.check_committed(GOOD + '1600 pad TURBO\n'))
        self.assertTrue(story.check_committed(GOOD + '1000 pad B\n'))

    def test_committed_segments_are_pads_only(self):
        segs = sorted((TOOLS / 'story-replays').glob('*/*.seg'))
        for seg in segs:
            with self.subTest(seg=seg.name):
                self.assertEqual(story.check_committed(seg.read_text()), [])
                self.assertIn(seg.parent.name, ('sc1', 'sc2v2', 'sc2v1', 'sc3'))

    def test_plan_step(self):
        self.assertEqual(plan_step((0, 0), [(3, 0)], set(), {}), 'RIGHT')
        # a wall east of the start (two failed steps) sends the unit round it
        self.assertEqual(plan_step((0, 0), [(3, 0)], set(), {((0, 0), (1, 0)): 2}), 'UP')
        # a corridor one tile wide, an ally in it: walk through the ally (passable), never stop on it
        wall = {(x, y) for x in range(0, 8) for y in (1, -1)}
        self.assertIsNone(plan_step((0, 0), [(5, 0)], wall | {(2, 0)}, {}))
        self.assertEqual(plan_step((0, 0), [(5, 0)], wall | {(2, 0)}, {}, passable={(2, 0)}), 'RIGHT')
        self.assertIsNone(plan_step((0, 0), [(3, 0)], wall | {(2, 0), (3, 0)}, {}, passable={(2, 0)}))
        # boxed in by other units: no step
        self.assertIsNone(plan_step((1, 1), [(5, 5)], {(0, 1), (2, 1), (1, 0), (1, 2)}, {}))

    def test_flat_blue_rows(self):
        w, h = 64, 16
        flat = bytes([20, 30, 120]) * (w * h)
        self.assertGreater(flat_blue_rows(w, h, flat), 0)
        rough = bytearray(flat)
        for i in range(0, len(rough), 6):
            rough[i + 2] = 200           # every other pixel a different blue: textured water
        self.assertEqual(flat_blue_rows(w, h, bytes(rough)), 0)

    def test_aimed_turn_unit_leaves_table(self):
        # invented roster: unit 22 drops out of the force table during the probe (it fell on the
        # previous enemy turn); it must not be taken as the unit under control (KeyError before)
        from unittest import mock
        from sf3test import autoplay
        presses = []
        force = {1: (5, 5), 22: (6, 5)}

        def read_units(rd, base, live=None):
            if base == 'E':
                return [(0, 9, 5, 0, 10)]
            return [(k, x, y, 0, 10) for k, (x, y) in force.items()]

        def press(btn, n):
            presses.append(btn)
            force.pop(22, None)

        class Side:
            read = None
            def frame(self):
                return None
        pol = autoplay.Policy(1)
        pol.pathing = True
        with mock.patch.object(autoplay.memory_map, 'read_units', read_units), \
                mock.patch.object(autoplay, 'panel_share', lambda f: 0.0):
            autoplay.aimed_turn(Side(), {'force': 'F', 'enemies': 'E'}, pol, press)
        self.assertTrue(presses)

    def test_aimed_turn_returns_off_a_teammate(self):
        # invented roster: every step the mover takes lands on a teammate (a packed bridge); the
        # turn must not end there, so B returns it to its start tile before the ring opens
        from unittest import mock
        from sf3test import autoplay
        start, tiles = (5, 7), [(5, 6), (4, 6)]
        force = {1: (5, 6), 2: start, 3: (4, 6)}
        log = []

        def read_units(rd, base, live=None):
            if base == 'E':
                return [(0, 5, 0, 0, 10)]
            return [(k, x, y, 0, 10) for k, (x, y) in force.items()]

        def press(btn, n):
            if btn == ('B',):
                force[2] = start
            elif btn and btn[0] in autoplay.DIRS:
                force[2] = tiles[len(log) % 2]
            if btn:
                log.append((btn, force[2]))

        class Side:
            read = None
            def frame(self):
                return None
        pol = autoplay.Policy(1)
        pol.pathing = True
        with mock.patch.object(autoplay.memory_map, 'read_units', read_units), \
                mock.patch.object(autoplay, 'panel_share', lambda f: 0.0), \
                mock.patch.object(autoplay, 'is_hurt', lambda *a: False):
            autoplay.aimed_turn(Side(), {'force': 'F', 'enemies': 'E'}, pol, press)
        first_c = next(i for i, (b, _) in enumerate(log) if b == ('C',))
        self.assertEqual(log[first_c - 1], (('B',), start))
        self.assertEqual(pol.returns, 1)

    def test_aimed_turn_phantom_enemy(self):
        # invented roster: the mover's step lands on a live enemy record's tile (a record that is
        # not on the field); B returns it and the record stops being a target for this battle
        from unittest import mock
        from sf3test import autoplay
        start = (5, 7)
        force = {1: (1, 1), 2: start}
        log = []

        def read_units(rd, base, live=None):
            if base == 'E':
                return [(8, 5, 6, 0, 10), (9, 5, 0, 0, 10)]
            return [(k, x, y, 0, 10) for k, (x, y) in force.items()]

        def press(btn, n):
            if btn == ('B',):
                force[2] = start
            elif btn and btn[0] in autoplay.DIRS and force[2] == start:
                force[2] = (5, 6)
            if btn:
                log.append(btn)

        class Side:
            read = None
            def frame(self):
                return None
        pol = autoplay.Policy(1)
        pol.pathing = True
        with mock.patch.object(autoplay.memory_map, 'read_units', read_units), \
                mock.patch.object(autoplay, 'panel_share', lambda f: 0.0), \
                mock.patch.object(autoplay, 'is_hurt', lambda *a: False):
            autoplay.aimed_turn(Side(), {'force': 'F', 'enemies': 'E'}, pol, press)
        self.assertEqual(pol.phantoms, {8})
        self.assertIn(('B',), log)
        self.assertEqual(force[2], start)

    def test_panel_names_boxed_in_unit_and_heals(self):
        # invented roster and pictures: slot 31 never moves (boxed in), slot 7 does and its panel
        # is learned; a force panel matching no learned name is the one slot left (31), which is
        # hurt with MP, so its turn casts (ring Magic) instead of idling; an enemy panel names nobody
        from unittest import mock
        from types import SimpleNamespace as N
        from sf3test import autoplay

        def frame(text_x, red=False):
            w, h = 320, 240
            px = bytearray(w * h * 3)
            for y in range(10, 40):
                for x in list(range(60, 90)) + list(range(100, 260)):    # land-effect box, panel
                    px[(y * w + x) * 3:(y * w + x) * 3 + 3] = bytes((20, 30, 120))
            for y in range(14, 24):
                for x in text_x:
                    px[(y * w + x) * 3:(y * w + x) * 3 + 3] = bytes((250, 60, 60) if red else (250, 250, 250))
            return N(width=w, height=h, rgb=bytes(px))
        julian, gracia, monk = frame(range(110, 130)), frame(range(140, 170)), frame(range(110, 150), red=True)
        sj, sg, sm = (autoplay.panel_sig(f) for f in (julian, gracia, monk))
        scene = bytearray(julian.rgb)                    # an attack scene: no land-effect box
        for y in range(10, 40):
            for x in range(60, 90):
                scene[(y * 320 + x) * 3:(y * 320 + x) * 3 + 3] = bytes(3)
        self.assertIsNone(autoplay.panel_sig(N(width=320, height=240, rgb=bytes(scene))))
        self.assertFalse(sj[1]); self.assertTrue(sm[1])
        self.assertEqual(sj, autoplay.panel_sig(julian))
        pol = autoplay.Policy(1)
        pol.sigs = {7: sj[0]}
        self.assertIsNone(autoplay.panel_unit(pol, sm, [7, 31]))
        self.assertEqual(autoplay.panel_unit(pol, sj, [7, 31]), 7)
        self.assertEqual(autoplay.panel_unit(pol, sg, [7, 31]), 31)
        self.assertEqual(autoplay.panel_unit(pol, sg, [7, 31, 40]), 31)   # learned now
        force = {7: (1, 1), 31: (5, 5)}

        def read_units(rd, base, live=None):
            if base == 'E':
                return [(0, 9, 9, 0, 10)]
            return [(k, x, y, 0, 10) for k, (x, y) in force.items()]

        class Side:
            read = None
            def frame(self):
                return gracia
        pol.heal, pol.heal_at = (31,), 0.7
        with mock.patch.object(autoplay.memory_map, 'read_units', read_units), \
                mock.patch.object(autoplay, 'panel_share', lambda f: 0.0), \
                mock.patch.object(autoplay, 'SIGS', {'F': dict(pol.sigs)}), \
                mock.patch.object(autoplay, 'is_hurt', lambda *a: True), \
                mock.patch.object(autoplay, 'unit_mp_of', lambda *a: 20), \
                mock.patch.object(autoplay, 'unit_hp_of', lambda *a: 11):
            out = autoplay.aimed_turn(Side(), {'force': 'F', 'enemies': 'E'}, pol, lambda b, n: None)
        self.assertIn((autoplay.RING['magic'],), [b for b, _ in out])
        self.assertEqual(pol.heal_check, (31, 11, 31))
        self.assertEqual(pol.casts, 1)

    def test_escort_draws_units_to_it(self):
        # invented roster: slot 9 is escorted (the game moves it); with an enemy near it the mover
        # walks to that enemy, not the nearer far-off one; with none near it walks next to slot 9
        from unittest import mock
        from sf3test import autoplay
        for enemies, want in (([(0, 3, 5, 0, 10), (1, 12, 12, 0, 10)], (12, 12)), ([(0, 10, 6, 0, 10)], (10, 13)), ([(0, 1, 1, 0, 10)], (1, 1))):
            force = {2: (5, 5), 9: (10, 13)}

            def read_units(rd, base, live=None):
                if base == 'E':
                    return enemies
                return [(k, x, y, 0, 10) for k, (x, y) in force.items()]

            def press(btn, n):
                if btn and btn[0] in autoplay.DIRS:
                    force[2] = autoplay.step_of(force[2], btn[0])

            class Side:
                read = None
                def frame(self):
                    return None
            pol = autoplay.Policy(1)
            pol.pathing, pol.escort, pol.leader = True, 9, 9
            with mock.patch.object(autoplay.memory_map, 'read_units', read_units), \
                    mock.patch.object(autoplay, 'panel_share', lambda f: 0.0), \
                    mock.patch.object(autoplay, 'is_hurt', lambda *a: False):
                autoplay.aimed_turn(Side(), {'force': 'F', 'enemies': 'E'}, pol, press)
            x, y = force[2]
            self.assertLessEqual(abs(x - want[0]) + abs(y - want[1]), 2, (enemies, force))
            self.assertEqual(getattr(pol, "escorting", 0), 0 if want == (1, 1) else 1)   # an enemy far off: attack

    def test_heal_item_on_hurt_escort_beside(self):
        # invented roster: slot 2 carries a heal item, escorted slot 9 beside it is hurt: slot 2 uses
        # its first item (ring Items) and the check watches 9's HP, charging a miss to 2; with 9
        # two tiles off it does not
        from unittest import mock
        from sf3test import autoplay
        for spot, want in (((5, 6), True), ((5, 8), False)):
            force = {2: (5, 5), 9: spot}

            def read_units(rd, base, live=None):
                if base == 'E':
                    return [(0, 5, 12, 0, 10)]
                return [(k, x, y, 0, 10) for k, (x, y) in force.items()]

            def press(btn, n):
                if btn and btn[0] in autoplay.DIRS:
                    force[2] = autoplay.step_of(force[2], btn[0])

            class Side:
                read = None
                def frame(self):
                    return None
            pol = autoplay.Policy(1)
            pol.pathing, pol.escort, pol.leader, pol.heal_item = True, 9, 9, (2,)
            with mock.patch.object(autoplay.memory_map, 'read_units', read_units), \
                    mock.patch.object(autoplay, 'panel_share', lambda f: 0.0), \
                    mock.patch.object(autoplay, 'is_hurt', lambda rd, b, k, s: k == 9), \
                    mock.patch.object(autoplay, 'unit_hp_of', lambda *a: 8):
                out = autoplay.aimed_turn(Side(), {'force': 'F', 'enemies': 'E'}, pol, press)
            used = (autoplay.RING['item'],) in [b for b, _ in out]
            self.assertEqual(used, want, spot)
            if want:
                self.assertEqual(pol.heal_check, (9, 8, 2))

    def test_escort_several_guards_the_exposed_one(self):
        # invented roster: slots 9 and 7 escorted; no enemy near either; 7 is nearer the enemy, so
        # the mover walks next to 7, not 9
        from unittest import mock
        from sf3test import autoplay
        force = {2: (10, 10), 9: (14, 14), 7: (6, 6)}

        def read_units(rd, base, live=None):
            if base == 'E':
                return [(0, 2, 2, 0, 10)]
            return [(k, x, y, 0, 10) for k, (x, y) in force.items()]

        def press(btn, n):
            if btn and btn[0] in autoplay.DIRS:
                force[2] = autoplay.step_of(force[2], btn[0])

        class Side:
            read = None
            def frame(self):
                return None
        pol = autoplay.Policy(1)
        pol.pathing, pol.escort, pol.leader = True, [9, 7], 9
        with mock.patch.object(autoplay.memory_map, 'read_units', read_units), \
                mock.patch.object(autoplay, 'panel_share', lambda f: 0.0), \
                mock.patch.object(autoplay, 'is_hurt', lambda *a: False):
            autoplay.aimed_turn(Side(), {'force': 'F', 'enemies': 'E'}, pol, press)
        x, y = force[2]
        self.assertLessEqual(abs(x - 6) + abs(y - 6), 2, force)

    def test_hurt_leader_retreats(self):
        # invented roster: the leader (lowest slot) is hurt with an enemy two tiles away; its turn
        # walks it away from the enemy instead of holding still
        from unittest import mock
        from sf3test import autoplay
        force = {1: (5, 5), 4: (9, 9)}

        def read_units(rd, base, live=None):
            if base == 'E':
                return [(0, 5, 7, 0, 10)]
            return [(k, x, y, 0, 10) for k, (x, y) in force.items()]

        def press(btn, n):
            if btn and btn[0] in autoplay.DIRS:
                force[1] = autoplay.step_of(force[1], btn[0])

        class Side:
            read = None
            def frame(self):
                return None
        pol = autoplay.Policy(1)
        pol.pathing = True
        with mock.patch.object(autoplay.memory_map, 'read_units', read_units), \
                mock.patch.object(autoplay, 'panel_share', lambda f: 0.0), \
                mock.patch.object(autoplay, 'is_hurt', lambda *a: True):
            autoplay.aimed_turn(Side(), {'force': 'F', 'enemies': 'E'}, pol, press)
        x, y = force[1]
        self.assertGreater(abs(x - 5) + abs(y - 7), 5)
        self.assertGreater(pol.retreats, 2)

    def test_retreat_path_goes_through_allies(self):
        from sf3test import autoplay
        # a column of teammates north of the leader, the enemy south: the path crosses them and
        # ends on a free tile
        allies = {(5, 6), (5, 7), (4, 6), (6, 6)}
        path = autoplay.retreat_path((5, 5), [(5, 2)], allies, {})
        p = (5, 5)
        for d in path:
            p = autoplay.step_of(p, d)
        self.assertNotIn(p, allies)
        self.assertGreaterEqual(p[1], 8)
        self.assertEqual(autoplay.retreat_path((5, 5), [(5, 2)], allies, {}, reach=0), [])

    def test_prune_keeps_backtrack_frontier(self):
        import tempfile
        from pathlib import Path
        from sf3test import search
        with tempfile.TemporaryDirectory() as td:
            c = Path(td) / 'c'
            for n in ('0000-0', '0000-1', '0000-2', '0001-0', '0001-1', '0002-0'):
                (c / n).mkdir(parents=True)
                (c / n / 'commit.state').write_text('x')
            st = lambda n: str(c / n / 'commit.state')
            levels = [dict(state='/root.state', ranked=[dict(state=st('0000-1'), score=5), dict(state=st('0000-0'), score=4),
                                                        dict(state=st('0000-2'), score=-1e6)], pick=0),
                      dict(state=st('0000-1'), ranked=[dict(state=st('0001-0'), score=3), dict(state=st('0001-1'), score=2)], pick=1),
                      dict(state=st('0002-0'), ranked=[], pick=0)]
            self.assertEqual(search.prune_dead(c, levels), 4)
            self.assertEqual(sorted(p.name for p in c.iterdir()), ['0000-0', '0002-0'])

    def test_keep_alts_caps_frontier(self):
        from sf3test import search
        levels = [dict(state='r', ranked=[dict(state='a/x', score=5), dict(state='b/x', score=4), dict(state='c/x', score=3),
                                          dict(state='d/x', score=2)], pick=0), dict(state='a/x', ranked=[], pick=0)]
        search.cap_alternatives(levels, 1)
        self.assertEqual([c['state'] for c in levels[0]['ranked']], ['a/x', 'b/x'])
        self.assertEqual({str(p) for p in search.live_dirs(levels)}, {'a', 'b'})

    def test_threat_costs_score(self):
        from sf3test import search
        m = dict(goal=False, leader_down=False, won=False, enemy_left=0.5, kills=1, force_left=1.0, deaths=0, leader=1.0)
        self.assertAlmostEqual(search.score(m) - search.score(dict(m, threat=1)), 1.5)

    def test_zone_costs_score(self):
        from sf3test import search
        m = dict(goal=False, leader_down=False, won=False, enemy_left=0.5, kills=1, force_left=1.0, deaths=0, leader=1.0)
        self.assertAlmostEqual(search.score(m) - search.score(dict(m, in_zone=1)), 3)

    def test_too_many_deaths_loses(self):
        from sf3test import search
        m = dict(goal=False, leader_down=False, won=False, enemy_left=0.5, kills=1, force_left=1.0, deaths=3, leader=1.0)
        self.assertEqual(search.score(dict(m, too_many_deaths=True)), -1e6)

    def test_search_metrics_and_score(self):
        from sf3test import search
        root = {'force': {0: (60, 60), 1: (40, 40)}, 'enemies': {5: (100, 100), 6: (50, 50)}}
        same = search.metrics(root, root, 0)
        hit = search.metrics({'force': {0: (60, 60), 1: (40, 40)}, 'enemies': {5: (40, 100)}}, root, 0)
        hurt = search.metrics({'force': {0: (10, 60), 1: (40, 40)}, 'enemies': {5: (100, 100), 6: (50, 50)}}, root, 0)
        down = search.metrics({'force': {1: (40, 40)}, 'enemies': {5: (1, 100)}}, root, 0)
        won = search.metrics({'force': {0: (5, 60)}, 'enemies': {}}, root, 0)
        self.assertEqual(hit['kills'], 1)
        self.assertGreater(search.score(hit), search.score(same))
        self.assertGreater(search.score(same), search.score(hurt))
        self.assertTrue(down['leader_down'])
        self.assertEqual(search.score(down), -1e6)
        self.assertTrue(won['won'])
        self.assertGreater(search.score(won), search.score(hit))
        self.assertEqual(search.score(dict(same, goal=True)), 1e6)
        junk = search.metrics({'force': {0: (60, 60), 1: (13000, 40)}, 'enemies': {5: (100, 100), 6: (50, 50)}}, root, 0)
        self.assertEqual(junk['force_left'], 1.0)

    def test_battle_over_from_active_byte(self):
        from sf3test import search, memory_map as M
        prof = 'scenario3-v25_1-redump'
        addr, val = M.lookup(prof)['battle_active']
        job = dict(profile=prof, root_active=True, root_flag_bits=17)
        m = dict(won=False, leader_down=False, reset=False)
        field = lambda a, n: bytes([2]) if a == addr else bytes(n)
        fight = lambda a, n: bytes([val]) if a == addr else bytes(n)
        self.assertFalse(search.battle_over(fight, job, m, 18))     # still in battle
        self.assertTrue(search.battle_over(field, job, m, 18))      # over by event: a new story bit
        self.assertFalse(search.battle_over(field, job, m, 17))     # Egress: no new bit, enemies up
        self.assertTrue(search.battle_over(field, job, dict(m, won=True), 17))
        self.assertFalse(search.battle_over(field, job, dict(m, leader_down=True), 18))
        self.assertFalse(search.battle_over(field, dict(job, root_active=None), m, 18))
        self.assertIsNone(M.in_battle(field, M.lookup('scenario1-usa-v25_1')))

    def test_turned_camera_pad(self):
        # round 27: on Sc2 V1.003 map 0x49 pad RIGHT steps y-1 and UP x+1
        from sf3test import autoplay as A
        t = A.learn_turn('RIGHT', (0, -1))
        self.assertEqual(t, A.learn_turn('UP', (1, 0)))
        self.assertEqual(A.pad_for('RIGHT', t), 'UP')
        self.assertEqual(A.pad_for('UP', t), 'LEFT')
        self.assertEqual(A.pad_for('DOWN', 0), 'DOWN')
        self.assertIsNone(A.learn_turn('UP', (1, 1)))

    def test_guard_hp_floor_loses(self):
        from sf3test import search
        root = dict(force={31: (35, 35), 7: (40, 40)}, enemies={0: (10, 10)})
        now = dict(force={31: (30, 35), 7: (13, 40)}, enemies={0: (10, 10)})
        self.assertTrue(search.low_hp(now, root, [31, 7], 0.4))
        self.assertFalse(search.low_hp(now, root, [31], 0.4))
        m = dict(search.metrics(now, root, 31, [7]), low_hp=True)
        self.assertEqual(search.score(m), -1e6)

    def test_protected_fall_loses(self):
        from sf3test import search
        root = dict(force={31: (40, 40), 7: (13, 42)}, enemies={0: (40, 40)})
        up = dict(force={31: (35, 40), 7: (13, 42)}, enemies={0: (40, 40)})
        julian_gone = dict(force={31: (35, 40)}, enemies={0: (40, 40)})
        self.assertFalse(search.metrics(up, root, 31, [7])['leader_down'])
        self.assertFalse(search.metrics(julian_gone, root, 31)['leader_down'])
        m = search.metrics(julian_gone, root, 31, [7])
        self.assertTrue(m['leader_down'])
        self.assertEqual(search.score(m), -1e6)
        self.assertFalse(search.metrics(julian_gone, root, 31, [9])['leader_down'])   # not in the root roster

    def test_is_hurt(self):
        from sf3test import autoplay, memory_map as M
        rec = bytearray(M.UNIT_STRIDE * 2)
        o = M.UNIT_STRIDE
        rec[o + M.UNIT_HP:o + M.UNIT_HP + 2] = (18).to_bytes(2, 'big')
        rec[o + M.UNIT_MAX_HP:o + M.UNIT_MAX_HP + 2] = (63).to_bytes(2, 'big')
        read = lambda a, n: bytes(rec[a - 0x1000:a - 0x1000 + n])
        self.assertTrue(autoplay.is_hurt(read, 0x1000, 1, 0.6))
        self.assertFalse(autoplay.is_hurt(read, 0x1000, 1, 0.2))
        self.assertFalse(autoplay.is_hurt(read, 0x1000, 0, 0.6))     # empty record

if __name__ == '__main__':
    unittest.main()
