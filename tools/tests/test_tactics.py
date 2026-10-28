"""Invented-roster tests for the opt-in battle tactics (tools/sf3test/tactics.py and their use in
autoplay.aimed_turn): --hold-until, --ranged/--casters/--item-attack, --healers and --protect."""
import sys
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from sf3test import autoplay, tactics   # noqa: E402


def turn(force, enemies, mover=2, hurt=lambda rd, b, k, s: False, mp=10, **attrs):
    """One aimed_turn on an invented roster: `force` {slot: (x, y)} (the D-pad moves `mover` until C
    opens the ring), `enemies` [(slot, x, y, flags, hp)]. Returns (pol, buttons after the ring C, the
    returned press list)."""
    ring = []

    def read_units(rd, base, live=None):
        if base == "E":
            return list(enemies)
        return [(k, x, y, 0, 10) for k, (x, y) in force.items()]

    def press(btn, n):
        if btn and btn[0] == "C":
            ring.append("C")
        elif btn and ring:
            ring.append(btn[0])
        elif btn and btn[0] in autoplay.DIRS:
            force[mover] = autoplay.step_of(force[mover], btn[0])

    class Side:
        read = None

        def frame(self):
            return None
    pol = attrs.pop("pol", None) or autoplay.Policy(1)
    pol.pathing = True
    for k, v in attrs.items():
        setattr(pol, k, v)
    with mock.patch.object(autoplay.memory_map, "read_units", read_units), \
            mock.patch.object(autoplay, "panel_share", lambda f: 0.0), \
            mock.patch.object(autoplay, "is_hurt", hurt), \
            mock.patch.object(autoplay, "unit_hp_of", lambda rd, t, k: 5), \
            mock.patch.object(autoplay, "unit_mp_of", lambda rd, t, k: mp):
        out = autoplay.aimed_turn(Side(), {"force": "F", "enemies": "E"}, pol, press)
    return pol, ring, out


class TacticsTest(unittest.TestCase):
    def test_track_still(self):
        still = {}
        e = [(0, 5, 5, 0, 10), (1, 9, 9, 0, 10)]
        self.assertEqual(tactics.track_still(still, e, {0: (5, 5), 1: (8, 9)}), {0})  # 0 never left its root tile
        tactics.track_still(still, e)
        self.assertEqual(tactics.track_still(still, e), {0, 1})                     # 1: three turns on 9,9
        self.assertEqual(tactics.track_still(still, [(0, 5, 6, 0, 10), (1, 9, 9, 0, 1)]), set())  # moved; a 1-HP barrel

    def test_hold_until_waits_out_of_range_then_commits(self):
        # the Sc1 pocket, invented: a boss that never moves at 16,29 (its Bolt reaches 3 tiles); the
        # mover at 16,24 alone could reach it, its partner at 30,5 cannot: it waits out of range
        boss = [(0, 16, 29, 0, 90)]
        force = {2: (16, 24), 3: (30, 5), 9: (40, 40)}
        pol, _, _ = turn(force, boss, leader=9, tactics={"hold_until": 2}, root_epos={0: (16, 29)})
        self.assertEqual(pol.hold_waits, 1)
        self.assertGreater(tactics.md(force[2], (16, 29)), tactics.HOLD_RANGE, force)
        # the partner now within a move of the boss: they commit, the mover ends next to it
        force = {2: (16, 24), 3: (18, 25), 9: (40, 40)}
        pol, _, _ = turn(force, boss, leader=9, tactics={"hold_until": 2}, root_epos={0: (16, 29)})
        self.assertEqual(getattr(pol, "hold_waits", 0), 0)
        self.assertEqual(tactics.md(force[2], (16, 29)), 1, force)
        # off by default: it walks straight in
        force = {2: (16, 24), 3: (30, 5), 9: (40, 40)}
        pol, _, _ = turn(force, boss, leader=9, root_epos={0: (16, 29)})
        self.assertEqual(tactics.md(force[2], (16, 29)), 1, force)

    def test_hold_goals_helper(self):
        # a target with a hit tile out of every threat's range is fair game; fewer units left than N:
        # they go with what there is
        self.assertIsNone(tactics.hold_goals((5, 0), (5, 5), [(5, 9)], set(), 3, {2: (5, 0)}))
        self.assertIsNone(tactics.hold_goals((5, 0), (5, 5), [(5, 5)], set(), 3, {2: (5, 0)}))
        g = tactics.hold_goals((5, 0), (5, 5), [(5, 5)], set(), 3, {2: (5, 0), 3: (30, 30)})
        self.assertTrue(g and all(not tactics.in_danger(q, [(5, 5)]) for q in g), g)

    def test_caster_casts_from_two_tiles(self):
        force = {2: (10, 10), 9: (40, 40)}
        foe = [(0, 10, 16, 0, 30)]
        pol, ring, _ = turn(force, foe, leader=9, tactics={"casters": [2]})
        self.assertEqual(tactics.md(force[2], (10, 16)), tactics.SPELL_RANGE, force)
        self.assertEqual(ring[1], autoplay.RING["magic"], ring)
        self.assertEqual(pol.tac_uses, 1)
        # no MP: an ordinary unit, it walks next to the target and attacks
        force = {2: (10, 10), 9: (40, 40)}
        pol, ring, _ = turn(force, foe, leader=9, tactics={"casters": [2]}, mp=0)
        self.assertEqual(getattr(pol, "tac_uses", 0), 0)

    def test_ranged_shoots_and_failed_uses_turn_it_off(self):
        force = {2: (10, 10), 9: (40, 40)}
        foe = [(0, 10, 16, 0, 30)]
        pol, ring, _ = turn(force, foe, leader=9, tactics={"ranged": [2]})
        self.assertEqual(tactics.md(force[2], (10, 16)), 2, force)
        self.assertEqual(ring[1], autoplay.RING["attack"], ring)
        self.assertEqual(pol.tac_check[2], 2)
        for _ in range(tactics.FAIL_MAX):         # the target HP never drops: two misses
            pol, ring, _ = turn(force, foe, pol=pol, leader=9, tactics={"ranged": [2]})
        self.assertEqual(pol.tac_fail[2], tactics.FAIL_MAX)
        turn(force, foe, pol=pol, leader=9, tactics={"ranged": [2]})
        self.assertEqual(tactics.md(force[2], (10, 16)), 1, force)  # back to walking up and striking

    def test_item_attack_uses_item_ring(self):
        force = {2: (10, 14), 9: (40, 40)}
        pol, ring, _ = turn(force, [(0, 10, 16, 0, 30)], leader=9, tactics={"item_attack": [2]})
        self.assertEqual(ring[1], autoplay.RING["item"], ring)

    def test_healer_heals_hurt_ally_before_attacking(self):
        hurt = lambda rd, b, k, s: b == "F" and k == 3
        force = {2: (10, 10), 3: (11, 10), 9: (40, 40)}
        foe = [(0, 10, 12, 0, 30)]
        pol, ring, out = turn(force, foe, hurt=hurt, leader=9, tactics={"healers": [2]})
        self.assertEqual(pol.ally_heals, 1)
        btn = [b[0][0] for b, n in [(x, 0) for x in out] if b[0]]
        self.assertEqual(btn[:4], ["C", autoplay.RING["magic"], "C", "C"])
        self.assertEqual(btn[4], "RIGHT")             # the target cursor onto the ally at 11,10
        self.assertEqual(pol.heal_check[2], 2)
        # an ally farther off: the healer walks over to it
        force = {2: (10, 10), 3: (14, 10), 9: (40, 40)}
        pol, ring, out = turn(force, [(0, 30, 30, 0, 30)], hurt=hurt, leader=9, tactics={"healers": [2]})
        self.assertEqual(pol.heal_walks, 1)
        self.assertEqual(tactics.md(force[2], (14, 10)), 1, force)

    def test_protect_attacks_a_safe_target(self):
        force = {2: (10, 10), 9: (40, 40)}
        pol, _, _ = turn(force, [(0, 10, 15, 0, 30)], leader=9, protect=[2])
        self.assertEqual(pol.protect_attacks, 1)
        self.assertEqual(tactics.md(force[2], (10, 15)), 1, force)

    def test_protect_never_ends_next_to_a_stationary_enemy(self):
        force = {2: (10, 10), 9: (40, 40)}
        pol, _, _ = turn(force, [(0, 10, 15, 0, 30)], leader=9, protect=[2], root_epos={0: (10, 15)})
        self.assertEqual(getattr(pol, "protect_attacks", 0), 0)
        self.assertGreater(tactics.md(force[2], (10, 15)), 1, force)
        # a moving target next to the stationary one: only the tiles away from it are used
        force = {2: (10, 10), 9: (40, 40)}
        foes = [(0, 10, 15, 0, 30), (1, 11, 16, 0, 30)]
        pol, _, _ = turn(force, foes, leader=9, protect=[2], focus=[0], root_epos={1: (11, 16)})
        self.assertEqual(pol.protect_attacks, 1)
        self.assertEqual(tactics.md(force[2], (10, 15)), 1, force)
        self.assertGreater(tactics.md(force[2], (11, 16)), 1, force)

    def test_passive_protected_unit_never_attacks(self):
        force = {2: (10, 10), 9: (40, 40)}
        pol, _, _ = turn(force, [(0, 10, 15, 0, 30)], leader=9, protect=[2], tactics={"passive": [2]})
        self.assertEqual(getattr(pol, "protect_attacks", 0), 0)
        self.assertGreater(tactics.md(force[2], (10, 15)), 1, force)

    def test_protect_still_retreats_when_hurt(self):
        force = {2: (10, 10), 9: (40, 40)}
        pol, _, _ = turn(force, [(0, 10, 12, 0, 30)], hurt=lambda rd, b, k, s: b == "F" and k == 2,
                         leader=9, protect=[2])
        self.assertEqual(getattr(pol, "protect_attacks", 0), 0)
        self.assertGreater(tactics.md(force[2], (10, 12)), 2, force)


    def test_avoid_all_walks_any_unit_out_of_the_zone(self):
        # the Sc2 blast zone, invented: an ordinary unit starting its turn inside walks out
        foe = [(0, 10, 13, 0, 30)]
        force = {2: (10, 10), 9: (40, 40)}
        turn(force, foe, leader=9, avoid=(10, 10, 3), tactics={"avoid_all": True})
        self.assertGreater(tactics.md(force[2], (10, 10)), 3, force)
        # off by default: only the leader and protected units leave; it walks up to the enemy
        force = {2: (10, 10), 9: (40, 40)}
        turn(force, foe, leader=9, avoid=(10, 10, 3))
        self.assertEqual(tactics.md(force[2], (10, 13)), 1, force)

    def test_retreat_never_ends_in_the_avoid_zone(self):
        from sf3test import autoplay
        free = autoplay.retreat_path((10, 10), [(10, 9)], set(), {}, reach=3)
        end = (10, 10)
        for d in free:
            end = autoplay.step_of(end, d)
        zone = (end[0], end[1], 1)
        path = autoplay.retreat_path((10, 10), [(10, 9)], set(), {}, reach=3, avoid=zone)
        q = (10, 10)
        for d in path:
            q = autoplay.step_of(q, d)
        self.assertTrue(path)
        self.assertGreater(abs(q[0] - zone[0]) + abs(q[1] - zone[1]), 1)

    def test_zone_fatal_scores_a_loss(self):
        from sf3test import search
        m = dict(leader_down=False, won=False, enemy_left=0.5, kills=1, force_left=0.5, deaths=0, leader=1.0, in_zone=1)
        self.assertGreater(search.score(m), -10)
        self.assertEqual(search.score(dict(m, zone_fatal=True)), -1e6)

    def test_tactics_of_search_args(self):
        import argparse
        from sf3test import search
        a = argparse.Namespace(hold_until=3, ranged=None, casters=[2], healers=None, item_attack=None)
        self.assertEqual(search.tactics_of(a), {"hold_until": 3, "casters": [2]})
        self.assertEqual(search.tactics_of(argparse.Namespace()), {})


if __name__ == "__main__":
    unittest.main()
