"""Replay honours a segment's recorded agent step edge (the 'agent_line' header).

Invented-data tests: a fake agent whose end RAM hash depends on SF3_AGENT_LINE stands in for the game,
so a replay only matches its segment when it steps at the edge the segment was recorded with.
The optional real replay (SF3_REPLAY_SEGMENT, SF3_REPLAY_BUILD, SF3_REPLAY_CUE, SF3_REPLAY_SAVES)
runs a locally recorded segment against a local build and disc; it is skipped when they are not set."""
import glob
import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from sf3test import story  # noqa: E402


def load_cli():
    spec = importlib.util.spec_from_file_location('sf3_story_cli', TOOLS / 'sf3-story.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fake_ram(line):
    return hashlib.sha1(f'edge {line}'.encode()).hexdigest()[:16]


class FakeRun:
    def __init__(self):
        self.line = os.environ.get('SF3_AGENT_LINE')   # what the agent process would inherit

    def close(self):
        pass


class FakeRecorder:
    def __init__(self, r, *a):
        self.r, self.events = r, []

    def shot(self, name):
        pass


class ReplayAgentLineTest(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.get('SF3_AGENT_LINE')
        self.cli = load_cli()
        c = self.cli
        c.memory_map = types.SimpleNamespace(lookup=lambda p: {'scenario': 1})
        c.scenario_targets = lambda profile, saves: []
        c.find = lambda ts, rid: {'id': rid}
        c.goal_list = lambda ts, start: []
        c.sha_bin = lambda p: 'b'
        c.start_run = lambda saturn, cue, target, scenario, work, **k: (Path(work).mkdir(parents=True, exist_ok=True), FakeRun())[1]
        c.Recorder = FakeRecorder
        c.apply_actions = lambda s, actions, until=None: None
        c.end_hashes = lambda s, profile: dict(vblank=2000, ram_sha1=fake_ram(s.r.line), flags_sha1='f')
        c.fatal_lines = lambda out: []
        self.td = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.td.cleanup()
        if self.saved is None:
            os.environ.pop('SF3_AGENT_LINE', None)
        else:
            os.environ['SF3_AGENT_LINE'] = self.saved

    def replay(self, header_line, recorded_line, env_line=None):
        h = dict(profile='p', record='save:x:01', clock='2026-01-01T00:00:00', binary='b', end_vblank=2000,
                 end_ram_sha1=fake_ram(recorded_line), end_flags_sha1='f', reached='-')
        if header_line is not None:
            h['agent_line'] = header_line
        seg = Path(self.td.name) / 'a.seg'
        seg.write_text(story.segment_text(h, [(1100, 'pad', 'START'), (1108, 'pad', '')]))
        if env_line is None:
            os.environ.pop('SF3_AGENT_LINE', None)
        else:
            os.environ['SF3_AGENT_LINE'] = env_line
        a = types.SimpleNamespace(segment=str(seg), saves=[], out=str(Path(self.td.name) / 'out'), saturn='s',
                                  cue='c', coverage=False, rebase=None)
        return self.cli.replay(a)

    def test_header_parse(self):
        self.assertIsNone(story.agent_line({}))
        self.assertIsNone(story.agent_line({'agent_line': '-'}))
        self.assertEqual(story.agent_line({'agent_line': '262'}), '262')
        text = story.segment_text({'profile': 'p', 'agent_line': '262'}, [(5, 'pad', 'C')])
        self.assertEqual(story.agent_line(story.parse_segment(text)[0]), '262')
        with self.assertRaises(ValueError):
            story.agent_line({'agent_line': 'vblank'})

    def test_env_restored(self):
        os.environ['SF3_AGENT_LINE'] = '100'
        with story.agent_line_env({'agent_line': '262'}) as line:
            self.assertEqual((line, os.environ['SF3_AGENT_LINE']), ('262', '262'))
        self.assertEqual(os.environ['SF3_AGENT_LINE'], '100')
        with story.agent_line_env({}):
            self.assertNotIn('SF3_AGENT_LINE', os.environ)
        self.assertEqual(os.environ['SF3_AGENT_LINE'], '100')

    def test_recorded_line_replays_to_same_hash(self):
        self.assertEqual(self.replay('262', '262'), 0)

    def test_recorded_line_beats_inherited_env(self):
        self.assertEqual(self.replay('262', '262', env_line='100'), 0)

    def test_no_header_keeps_vblank_in_default(self):
        self.assertEqual(self.replay(None, None, env_line='262'), 0)   # inherited SF3_AGENT_LINE is ignored
        self.assertEqual(self.replay('-', None), 0)

    def test_wrong_edge_mismatches(self):
        self.assertEqual(self.replay(None, '262'), 1)   # an old play.py segment without the header


@unittest.skipUnless(all(os.environ.get(f'SF3_REPLAY_{n}') for n in ('SEGMENT', 'BUILD', 'CUE', 'SAVES')),
                     'local real replay: set SF3_REPLAY_SEGMENT SF3_REPLAY_BUILD SF3_REPLAY_CUE SF3_REPLAY_SAVES')
class RealReplayTest(unittest.TestCase):
    def test_segment_ram_hash_matches(self):
        e = os.environ
        with tempfile.TemporaryDirectory() as td:
            cmd = [sys.executable, str(TOOLS / 'sf3-story.py'), 'replay', '--saturn', e['SF3_REPLAY_BUILD'],
                   '--cue', e['SF3_REPLAY_CUE'], '--saves', *sorted(glob.glob(os.path.join(e['SF3_REPLAY_SAVES'], '*.bin'))),
                   '--out', td, e['SF3_REPLAY_SEGMENT']]
            p = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout[-2000:] + p.stderr[-2000:])
            self.assertIn('MATCH end', p.stdout)


if __name__ == '__main__':
    unittest.main()
