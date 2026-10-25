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

if __name__ == '__main__':
    unittest.main()
