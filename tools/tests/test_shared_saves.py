"""Shared backup memory for all scenarios: synthetic backup images only, never real game data."""
import contextlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'desktop'))
import shared_saves as shared_saves
import run_posix as sessions

PROFILES = {1: 'scenario1-translation-v25_1', 2: 'scenario2-v25_1-v2_000', 3: 'scenario3-v25_1-redump'}


def record(name, size, fill, comment=b'SYNTHETIC'):
    data = bytes([fill]) * size
    return name.encode().ljust(12, b'\0') + comment.ljust(11, b'\0') + b'\0' + struct.pack('<II', 1234, size) + data


def game(root, name, scenario, internal=b'', cartridge=None):
    work = Path(root)/name
    work.mkdir(parents=True)
    (work/'game.json').write_text(json.dumps({'profile_id': PROFILES[scenario]}))
    (work/'experimental-backup.bin').write_bytes(internal)
    if cartridge is not None:
        (work/'experimental-backup.bin.cartridge').write_bytes(cartridge)
    return work


def names(path):
    return sorted(shared_saves.read_device(Path(path)))


S1, S2, S3 = shared_saves.SAVE_SIZES[1], shared_saves.SAVE_SIZES[2], shared_saves.SAVE_SIZES[3]


class SharedSavesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.shared = self.root/'shared'

    def tearDown(self):
        self.temp.cleanup()

    def test_container_round_trip_and_damage_keeps_whole_records(self):
        raw = record('SFORCE32_02', 10, 2) + record('SFORCE31_01', 5, 1)
        records, problem = shared_saves.parse(raw)
        self.assertIsNone(problem)
        self.assertEqual(shared_saves.serialize(records), record('SFORCE31_01', 5, 1) + record('SFORCE32_02', 10, 2))
        records, problem = shared_saves.parse(raw + b'SFORCE33_01\0' + b'\0' * 10)
        self.assertEqual(list(records), ['SFORCE32_02', 'SFORCE31_01'])
        self.assertIn('truncated', problem)

    def test_block_counts_match_the_runtime(self):
        # The runtime's HLE BUP: (size + 34 + block - 1) / block + 1, two blocks reserved per device.
        self.assertEqual(shared_saves.blocks(S2, 64), 256)
        self.assertEqual(shared_saves.blocks(S3, 64), 382)
        self.assertEqual(shared_saves.usable(shared_saves.DEVICES[0]), 510)
        self.assertEqual(shared_saves.usable(shared_saves.DEVICES[1]), 1022)

    def test_scenario_of_profiles(self):
        self.assertEqual(shared_saves.scenario_of('scenario1-usa'), 1)
        self.assertEqual(shared_saves.scenario_of('scenario2-v25_1-v1_003'), 2)
        self.assertEqual(shared_saves.scenario_of('scenario3-v25_1-redump'), 3)
        with self.assertRaises(ValueError):
            shared_saves.scenario_of('premium-disc')

    def test_migration_merges_every_save_and_keeps_originals(self):
        sc1 = game(self.root, 'sc1', 1, record('SFORCE31_01', S1, 1) + record('SFORCE31_02', S1, 11))
        sc2 = game(self.root, 'sc2', 2, record('SFORCE32_01', S2, 2), record('SFORCE32_02', S2, 22))
        before = {p: p.read_bytes() for p in [sc1/'experimental-backup.bin', sc2/'experimental-backup.bin', sc2/'experimental-backup.bin.cartridge']}
        report = shared_saves.merge(self.shared, [sc2, sc1])
        self.assertEqual(len(report['added']), 4)
        self.assertEqual(report['not_migrated'], [])
        # Sc1 x2 (2*204) does not leave room for Sc2's 256 blocks on the internal memory: moved, not dropped.
        self.assertEqual(names(self.shared/'backup.bin'), ['SFORCE31_01', 'SFORCE31_02'])
        self.assertEqual(names(self.shared/'backup.bin.cartridge'), ['SFORCE32_01', 'SFORCE32_02'])
        self.assertEqual([m['shared_name'] for m in report['moved']], ['SFORCE32_01'])
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)
            self.assertTrue(path.exists())
        backups = Path(report['backups'])
        copies = sorted(p.read_bytes() for p in backups.rglob('experimental-backup.bin*'))
        self.assertEqual(copies, sorted(before.values()))
        self.assertIn('Originals kept', shared_saves.describe(report))

    def test_duplicates_are_merged_once_and_name_collisions_are_renamed(self):
        sc2 = game(self.root, 'sc2', 2, record('SFORCE32_01', 100, 2))
        # The Sc3 folder has an imported copy of the same Sc2 save, and a different save with the same name.
        sc3 = game(self.root, 'sc3', 3, record('SFORCE32_01', 100, 2) + record('SFORCE33_01', 200, 3),
                   record('SFORCE32_01', 100, 9))
        report = shared_saves.merge(self.shared, [sc3, sc2])
        self.assertEqual(len(report['duplicates']), 1)
        self.assertEqual([(r['name'], r['shared_name']) for r in report['renamed']], [('SFORCE32_01', 'SFORCE32_02')])
        internal = shared_saves.read_device(self.shared/'backup.bin')
        self.assertEqual(internal['SFORCE32_01']['data'], bytes([2])*100)   # the owner keeps its name
        cartridge = shared_saves.read_device(self.shared/'backup.bin.cartridge')
        self.assertEqual(cartridge['SFORCE32_02']['data'], bytes([9])*100)

    def test_merge_is_one_time_and_rerun_only_after_a_change(self):
        sc1 = game(self.root, 'sc1', 1, record('SFORCE31_01', 50, 1))
        self.assertEqual(len(shared_saves.merge(self.shared, [sc1])['added']), 1)
        again = shared_saves.merge(self.shared, [sc1])
        self.assertEqual(again['merged'], [])
        self.assertEqual(shared_saves.describe(again), '')
        # Played with separate saves: the newer save is added beside the old one, never over it.
        (sc1/'experimental-backup.bin').write_bytes(record('SFORCE31_01', 50, 7))
        changed = shared_saves.merge(self.shared, [sc1])
        self.assertEqual([r['shared_name'] for r in changed['added']], ['SFORCE31_02'])
        self.assertEqual(names(self.shared/'backup.bin'), ['SFORCE31_01', 'SFORCE31_02'])
        manifest = json.loads((self.shared/'shared-saves.json').read_text())
        self.assertEqual(len(manifest['history']), 2)
        before = Path(changed['backups'])/'shared-before-merge'/'backup.bin'
        self.assertEqual(shared_saves.parse(before.read_bytes())[0].keys(), {'SFORCE31_01'})

    def test_save_without_room_is_reported_kept_and_retried(self):
        # Fill both shared devices with Sc3-sized saves.
        internal = record('SFORCE33_01', S3, 3)
        # 20 * 49 + 27 = 1007 of 1022 cartridge blocks used: 15 free, a Sc2 save needs 33.
        cartridge = b''.join(record(f'SFORCE33_{n:02d}', S3, n) for n in range(2, 22)) + record('SFORCE31_01', S1, 1)
        self.shared.mkdir()
        (self.shared/'backup.bin').write_bytes(internal)
        (self.shared/'backup.bin.cartridge').write_bytes(cartridge)
        sc2 = game(self.root, 'sc2', 2, record('SFORCE32_01', S2, 2))
        report = shared_saves.merge(self.shared, [sc2])
        self.assertEqual(len(report['not_migrated']), 1)
        self.assertIn('WARNING', shared_saves.describe(report))
        self.assertEqual((self.shared/'backup.bin').read_bytes(), internal)
        self.assertEqual((self.shared/'backup.bin.cartridge').read_bytes(), cartridge)
        self.assertEqual(len(shared_saves.merge(self.shared, [sc2])['not_migrated']), 1)
        room = shared_saves.capacity(self.shared, 2)
        self.assertIn('full', room['warnings'][0])

    def test_capacity_warnings(self):
        self.shared.mkdir()
        self.assertEqual(shared_saves.capacity(self.shared, 3)['warnings'], [])
        (self.shared/'backup.bin').write_bytes(record('SFORCE32_01', S2, 2))
        room = shared_saves.capacity(self.shared, 3)
        self.assertEqual(room['devices']['internal']['new_saves_that_fit'], 0)
        self.assertIn('Save to the cartridge', room['warnings'][0])
        (self.shared/'backup.bin.cartridge').write_bytes(b''.join(record(f'SFORCE31_{n:02d}', S3, n) for n in range(1, 20)))
        self.assertIn('almost full', shared_saves.capacity(self.shared, 3)['warnings'][0])

    def test_damaged_shared_file_is_never_rewritten(self):
        self.shared.mkdir()
        (self.shared/'backup.bin').write_bytes(b'not a backup')
        sc1 = game(self.root, 'sc1', 1, record('SFORCE31_01', 50, 1))
        with self.assertRaisesRegex(ValueError, 'damaged'):
            shared_saves.merge(self.shared, [sc1])
        self.assertEqual((self.shared/'backup.bin').read_bytes(), b'not a backup')

    def test_lock_allows_one_user_at_a_time(self):
        with shared_saves.lock(self.shared):
            with self.assertRaises(shared_saves.Busy):
                with shared_saves.lock(self.shared):
                    pass
            # Another process (another scenario's launcher) is refused too.
            code = ('import sys; sys.path.insert(0, %r); import shared_saves\n'
                    'try:\n    shared_saves.lock(%r).__enter__()\nexcept shared_saves.Busy:\n    sys.exit(3)\n'
                    % (str(Path(shared_saves.__file__).parent), str(self.shared)))
            self.assertEqual(subprocess.run([sys.executable, '-B', '-c', code]).returncode, 3)
        with shared_saves.lock(self.shared):
            pass

    def test_native_state_load_cannot_roll_back_other_scenarios(self):
        self.shared.mkdir()
        old = record('SFORCE31_01', 50, 1) + record('SFORCE32_01', 60, 2)
        (self.shared/'backup.bin').write_bytes(old)
        before = shared_saves.snapshot(self.shared)
        # The session restored an old memory (Sc1 save missing, an older Sc3 save) and saved Sc2.
        (self.shared/'backup.bin').write_bytes(record('SFORCE32_01', 60, 5) + record('SFORCE33_01', 10, 3))
        (self.shared/'backup.bin.cartridge').write_bytes(record('SFORCE31_09', 10, 9))
        report = shared_saves.guard_foreign(self.shared, 2, before)
        internal = shared_saves.read_device(self.shared/'backup.bin')
        self.assertEqual(sorted(internal), ['SFORCE31_01', 'SFORCE32_01'])
        self.assertEqual(internal['SFORCE32_01']['data'], bytes([5])*60)
        self.assertEqual(names(self.shared/'backup.bin.cartridge'), [])
        self.assertEqual(len(report['restored']), 1)
        self.assertEqual(len(report['removed']), 2)
        self.assertTrue(list(Path(report['backup']).glob('backup.bin*')))
        self.assertEqual(shared_saves.guard_foreign(self.shared, 2, shared_saves.snapshot(self.shared))['restored'], [])

    def test_replay_publish_takes_only_its_own_scenario(self):
        self.shared.mkdir()
        (self.shared/'backup.bin').write_bytes(record('SFORCE31_01', 50, 1) + record('SFORCE33_01', 10, 3))
        session = self.root/'replay-backup.bin'
        session.write_bytes(record('SFORCE31_01', 50, 8) + record('SFORCE33_01', 10, 4) + record('SFORCE33_02', 10, 6))
        shared_saves.publish_own(self.shared, 3, session)
        internal = shared_saves.read_device(self.shared/'backup.bin')
        self.assertEqual(internal['SFORCE31_01']['data'], bytes([1])*50)
        self.assertEqual(internal['SFORCE33_01']['data'], bytes([4])*10)
        self.assertIn('SFORCE33_02', internal)

    def test_known_folders_come_from_launcher_settings(self):
        sc1 = game(self.root, 'sc1', 1)
        sc3 = game(self.root, 'sc3', 3)
        (self.root/'missing').mkdir()
        settings = self.root/'launcher.json'
        settings.write_text(json.dumps({'games': {'0': {'work': str(sc1)}, '1': {'work': str(self.root/'missing')}}}))
        self.assertEqual(shared_saves.known_folders(sc3, [settings, self.root/'absent.json']), [sc3, sc1])

    def test_cli_prepare_reports_merge(self):
        sc1 = game(self.root, 'sc1', 1, record('SFORCE31_01', 50, 1))
        sc3 = game(self.root, 'sc3', 3)
        out = subprocess.run([sys.executable, '-B', shared_saves.__file__, 'prepare', '--work', str(sc3), '--shared', str(self.shared),
                              '--migrate-from', str(sc1), '--lock'], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout)
        self.assertEqual(result['scenario'], 3)
        self.assertEqual(len(result['merge']['added']), 1)


class SessionTests(unittest.TestCase):
    """run_posix.play in shared and separate mode, with an invented executable."""

    def play(self, root, work, separate=False, state=None, after=None):
        commands = []

        def run(args, **kwargs):
            commands.append(args)
            if after:
                after(args)
            return SimpleNamespace(returncode=0)
        statuses = []
        with patch.object(sessions, 'lock', return_value=contextlib.nullcontext()), \
                patch.object(sessions, 'package_root', return_value=root/'app'), \
                patch.object(sessions, 'identities', return_value=('build', 'disc')), \
                patch.object(sessions.shared_saves, 'default_folders', return_value=[]), \
                patch.object(sessions.common, 'status', side_effect=lambda phase, message: statuses.append((phase, message))), \
                patch.object(sessions.subprocess, 'run', side_effect=run), \
                open(os.devnull, 'w') as quiet, contextlib.redirect_stderr(quiet):
            sessions.play(work, state, separate=separate, shared_dir=root/'shared', settings=[root/'launcher.json'])
        return commands, statuses

    def work(self, root, name, scenario, backup=b''):
        work = game(root, name, scenario, backup)
        (work/'native-build.txt').write_text('build-synthetic')
        (work/'build-synthetic').mkdir()
        cue = root/(name+'.cue')
        cue.write_text('Invented test disc')
        data = json.loads((work/'game.json').read_text())
        (work/'game.json').write_text(json.dumps(dict(data, cue=str(cue))))
        return work

    def test_shared_mode_uses_one_file_for_all_scenarios_and_merges_others(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sc2 = self.work(root, 'sc2', 2, record('SFORCE32_01', 100, 2))
            sc3 = self.work(root, 'sc3', 3)
            (root/'launcher.json').write_text(json.dumps({'games': {'1': {'work': str(sc2)}, '2': {'work': str(sc3)}}}))
            commands, statuses = self.play(root, sc3)
            save = Path(commands[0][commands[0].index('--save')+1])
            self.assertEqual(save, root/'shared'/'backup.bin')
            self.assertEqual(names(save), ['SFORCE32_01'])
            self.assertTrue(any('1 save(s) added' in m for _, m in statuses), statuses)
            self.assertEqual((sc2/'experimental-backup.bin').read_bytes(), record('SFORCE32_01', 100, 2))
            session = next((sc3/'sessions').iterdir())
            self.assertEqual(json.loads((session/'saves.json').read_text())['mode'], 'shared')
            self.assertTrue((sc3/'shared-backup-memory.txt').is_file())
            commands, _ = self.play(root, sc2)
            self.assertEqual(Path(commands[0][commands[0].index('--save')+1]), save)

    def test_separate_saves_keep_the_old_per_folder_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sc3 = self.work(root, 'sc3', 3, record('SFORCE33_01', 10, 3))
            commands, _ = self.play(root, sc3, separate=True)
            self.assertEqual(Path(commands[0][commands[0].index('--save')+1]), sc3/'experimental-backup.bin')
            self.assertFalse((root/'shared').exists())

    def test_native_state_session_keeps_other_scenarios(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sc1 = self.work(root, 'sc1', 1, record('SFORCE31_01', 50, 1))
            sc2 = self.work(root, 'sc2', 2)
            (root/'launcher.json').write_text(json.dumps({'games': {'0': {'work': str(sc1)}}}))
            state = sc2/'native-states/synthetic/latest.satstate'
            state.parent.mkdir(parents=True)
            state.write_bytes(b'synthetic')

            def restore_old_memory(args):
                # The loaded state's memory had no Sc1 save; the session then saved Sc2.
                Path(args[args.index('--save')+1]).write_bytes(record('SFORCE32_01', 60, 2))
            with patch.object(sessions, 'check_state'):
                self.play(root, sc2, state=state, after=restore_old_memory)
            self.assertEqual(names(root/'shared'/'backup.bin'), ['SFORCE31_01', 'SFORCE32_01'])
            session = next((sc2/'sessions').iterdir())
            receipt = json.loads((session/'session.json').read_text())
            self.assertEqual(receipt['shared_saves_guard']['restored'], [dict(device='internal', name='SFORCE31_01')])
            self.assertTrue((session/'before-native-state-load-backup.bin').is_file())

    def test_shared_folder_inside_game_data_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sc1 = self.work(root, 'sc1', 1)
            with self.assertRaisesRegex(ValueError, 'outside'):
                sessions.shared_setup(sc1, shared_dir=sc1/'shared', settings=[])


if __name__ == '__main__':
    unittest.main()
