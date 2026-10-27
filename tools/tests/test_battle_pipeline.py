"""Battle-model pipeline boundaries; all artwork and binaries here are invented."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

APP = Path(__file__).resolve().parents[1] / 'offline-assets'
sys.path.insert(0, str(APP))
import battle_textures
import character_packs
import index_packs
import test_character_packs as fixtures

HAS_PILLOW = importlib.util.find_spec('PIL') is not None
if HAS_PILLOW:
    spec = importlib.util.spec_from_file_location('battle_pipeline_worker', APP / 'worker.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)


class BattlePackTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CharacterPacksTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def model(self, name='/X8PC01A.BIN', category='battle_models'):
        return self.fixture.asset(category, name, bytes((8, 32, 248, 255, 0, 0, 0, 0)))

    def test_battle_only_is_command_two_and_counted_separately(self):
        asset = self.model()
        result = self.fixture.run_pack()
        material = Path(result['path']) / asset['id']
        self.assertTrue((material / 'asset.txt').read_text().endswith('\nworld\n'))
        record, _, _ = index_packs.material(material)
        self.assertEqual(index_packs.RECORD.unpack(record)[4], 0)
        metadata = character_packs.read_json(material / 'metadata.json')
        self.assertEqual(metadata['eligible_commands'], [2])
        self.assertFalse(metadata['character_frame'])
        self.assertTrue(metadata['battle_model_texture'])
        self.assertEqual(result['character_material_count'], 0)
        self.assertEqual(result['battle_model_material_count'], 1)
        self.assertEqual(result['battle_model_candidates'], 1)
        self.assertEqual(result['replacement_bytes'], self.fixture.row['replacement_bytes'] + 128)
        self.assertEqual(result['material_count'], 2)
        self.assertEqual(result['missing_battle_models'], [])

    def test_world_chr_battle_collision_preserves_chr_without_duplicate_payload(self):
        asset = self.fixture.world_asset
        asset['refs'].extend([dict(category='sprites', file='/HERO.CHR', location='frame'),
                              dict(category='battle_models', file='/X8PC01A.BIN', location='texture')])
        before = (self.fixture.world / asset['id'] / 'asset.txt').read_bytes()
        result = self.fixture.run_pack()
        self.assertEqual(result['material_count'], 1)
        self.assertEqual(result['replacement_bytes'], self.fixture.row['replacement_bytes'])
        self.assertEqual(result['character_frames_already_world'], 1)
        self.assertEqual(result['battle_models_already_world'], 1)
        self.assertEqual(result['shared_character_battle_materials'], 1)
        self.assertEqual((self.fixture.world / asset['id'] / 'asset.txt').read_bytes(), before)
        self.assertTrue((Path(result['path']) / asset['id'] / 'asset.txt').read_text().endswith('\ncharacter\n'))

    def test_shared_new_chr_battle_texture_retains_chr_and_deduplicates_bytes(self):
        asset = self.model()
        asset['refs'].append(dict(category='sprites', file='/HERO.CHP', location='frame'))
        result = self.fixture.run_pack()
        self.assertEqual(result['material_count'], 2)
        self.assertEqual(result['added_unique_material_count'], 1)
        self.assertEqual(result['character_material_count'], 1)
        self.assertEqual(result['battle_model_material_count'], 1)
        self.assertEqual(result['shared_character_battle_materials'], 1)
        self.assertEqual(result['replacement_bytes'], self.fixture.row['replacement_bytes'] + 128)
        self.assertTrue((Path(result['path']) / asset['id'] / 'asset.txt').read_text().endswith('\ncharacter\n'))

    def test_existing_character_descriptor_survives_battle_only_catalog_alias(self):
        asset = self.fixture.world_asset
        asset['refs'] = [dict(category='battle_models', file='/X8PC01A.BIN', location='texture')]
        descriptor = self.fixture.world / asset['id'] / 'asset.txt'
        descriptor.write_text(descriptor.read_text() + 'character\n')
        result = self.fixture.run_pack()
        self.assertTrue((Path(result['path']) / asset['id'] / 'asset.txt').read_text().endswith('\ncharacter\n'))
        self.assertEqual(result['character_frames_already_world'], 1)

    def test_unrelated_bins_ui_categories_and_inexact_names_are_excluded(self):
        for category, name in [('battle_models', '/MENU.BIN'), ('battle_models', '/X8PC.BIN'),
                               ('battle_models', '/X8PC01A.BIN.extra'), ('battle_models', '/X8ELEM01.BIN'),
                               ('embedded', '/X8PC01A.BIN')]:
            ref = dict(category=category, file=name)
            self.assertEqual(character_packs.battle_model_refs(dict(refs=[ref])), [])
        self.assertEqual(len(character_packs.battle_model_refs(dict(refs=[dict(category='battle_models', file='/x8pc01a.bin')]))), 1)

    def test_changed_alpha_is_visible_battle_gap_even_with_updated_checksum(self):
        asset = self.model()
        path = self.fixture.enhanced / asset['id'] / 'replacement.rgba'
        replacement = bytearray(path.read_bytes()); replacement[19] = 255
        path.write_bytes(replacement)
        ready = character_packs.read_json(path.parent / 'ready.json')
        ready['rgba_sha256'] = hashlib.sha256(replacement).hexdigest()
        character_packs.atomic_json(path.parent / 'ready.json', ready)
        result = self.fixture.run_pack()
        self.assertEqual(result['battle_model_material_count'], 0)
        self.assertEqual(len(result['missing_battle_models']), 1)
        self.assertEqual(result['missing_characters'], [])
        self.assertIn('transparency', result['missing_battle_models'][0]['error'])
        self.assertFalse((Path(result['path']) / asset['id']).exists())


@unittest.skipUnless(HAS_PILLOW, 'Pillow unavailable: battle worker integration is unvalidated')
class BattleWorkerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = worker.Job({}, self.root / 'out', APP)

    def regular_decoder(self, command, log, timeout):
        worker.atomic_json(Path(command[-1]), dict(status='unsupported', images=[]))
        return 0

    def test_resumed_world_membership_preserves_old_pack_without_stale_materials(self):
        fixture = fixtures.CharacterPacksTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        job = worker.Job({}, fixture.cache, APP)
        first = fixture.world_asset
        second = fixture.asset('world', '/OTHER.MPD', bytes((16, 32, 48, 255, 0, 0, 0, 0)))
        cache = {'video': dict(signature=fixture.signature,
                              ready={a['id']: fixture.enhanced / a['id'] for a in (first, second)})}
        catalog = dict(scenario=2, profile='synthetic', assets={a['id']: a for a in (first, second)})
        old = job.pack({fixture.revision: catalog}, cache)[0]
        catalog['assets'] = {first['id']: first}
        new = job.pack({fixture.revision: catalog}, cache)[0]
        self.assertNotEqual(old['path'], new['path'])
        self.assertTrue((Path(old['path']) / second['id']).exists())
        self.assertFalse((Path(new['path']) / second['id']).exists())
        self.assertEqual(new['material_count'], 1)
        self.assertEqual(job.pack({fixture.revision: catalog}, cache)[0]['path'], new['path'])
        fixture.catalog = [first]
        character_packs.atomic_json(fixture.disc / 'catalog.json', fixture.catalog)
        result = character_packs.package(fixture.cache, fixture.out, new)
        self.assertEqual(result['material_count'], 1)

    def test_parser_revision_invalidates_only_exact_model_receipts(self):
        base = 'original-library-fingerprint'
        first = worker.decoder_fingerprint(base, 'X8PC01A.BIN')
        with mock.patch.object(battle_textures, 'DECODER_VERSION', 'invented-next-revision'):
            self.assertNotEqual(worker.decoder_fingerprint(base, 'X8PC01A.BIN'), first)
            for name in ('X8ELEM01.BIN', 'X8PC.BIN', 'MENU.BIN', 'TOWN.MPD', 'HERO.CHR'):
                self.assertEqual(worker.decoder_fingerprint(base, name), base)

    def test_malformed_recognized_model_is_failed_not_unsupported_or_empty_pass(self):
        source = self.root / 'X8PC01A.BIN'; source.write_bytes(b'invented truncated model')
        receipt = self.root / 'receipt.json'
        with mock.patch.object(self.job, 'run_process', self.regular_decoder):
            result = self.job.decode_file(Path('unused-extractor'), 2, source, receipt, self.root / 'tool.log',
                                          worker.sha(source), 'fresh-parser-fingerprint')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['images'], [])
        self.assertTrue(result['error'])
        self.assertEqual(json.loads(receipt.read_text())['decoder_sha256'], 'fresh-parser-fingerprint')

    def test_fallback_does_not_consume_other_binary_or_override_primary_failure(self):
        with mock.patch.object(battle_textures, 'extract') as fallback:
            for name in ('MENU.BIN', 'X8ELEM01.BIN', 'X8PC.BIN'):
                source = self.root / name; source.write_bytes(b'invented')
                with mock.patch.object(self.job, 'run_process', self.regular_decoder):
                    result = self.job.decode_file(Path('unused'), 2, source, self.root / (name + '.json'),
                                                  self.root / 'tool.log', worker.sha(source), 'base')
                self.assertEqual(result['status'], 'unsupported')
            source = self.root / 'X8PC01A.BIN'; source.write_bytes(b'invented')
            def failed(command, log, timeout):
                worker.atomic_json(Path(command[-1]), dict(status='failed', images=[], error='primary decoder failure'))
                return 1
            with mock.patch.object(self.job, 'run_process', failed):
                result = self.job.decode_file(Path('unused'), 2, source, self.root / 'failed.json',
                                              self.root / 'tool.log', worker.sha(source), 'base')
            self.assertEqual(result['error'], 'primary decoder failure')
            fallback.assert_not_called()

    def test_successful_primary_decoder_is_never_overwritten_by_fallback(self):
        source = self.root / 'X8PC01A.BIN'; source.write_bytes(b'invented')
        def decoded(command, log, timeout):
            worker.atomic_json(Path(command[-1]), dict(status='extracted', images=[dict(id='invented-primary-image')]))
            return 0
        with mock.patch.object(self.job, 'run_process', decoded), mock.patch.object(battle_textures, 'extract') as fallback:
            result = self.job.decode_file(Path('unused'), 2, source, self.root / 'decoded.json',
                                          self.root / 'tool.log', worker.sha(source), 'base')
        self.assertEqual(result['images'], [dict(id='invented-primary-image')])
        fallback.assert_not_called()

    def test_old_character_checkbox_enables_models_without_enabling_embedded_ui(self):
        self.assertIn('battle_models', worker.effective_categories({}))
        selected = worker.effective_categories(dict(categories=['world', 'sprites', 'backgrounds']))
        self.assertIn('battle_models', selected)
        self.assertNotIn('embedded', selected)
        self.assertNotIn('battle_models', worker.effective_categories(dict(categories=['world'])))


if __name__ == '__main__':
    unittest.main()
