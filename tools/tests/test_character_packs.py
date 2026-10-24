"""Character-pack tests use synthetic pixels only; no game fixtures or GPU required."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'offline-assets'))


path = Path(__file__).resolve().parents[1] / 'offline-assets' / 'character_packs.py'
spec = importlib.util.spec_from_file_location('sf3_character_packs', path)
packs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packs)


class CharacterPacksTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / 'cache'
        self.out = self.root / 'combined'
        self.signature, self.revision = '1' * 64, '2' * 64
        self.world = self.cache / 'packs' / self.signature[:16]
        self.world.mkdir(parents=True)
        self.enhanced = self.cache / 'enhanced' / self.signature[:20]
        self.enhanced.mkdir(parents=True)
        packs.atomic_json(self.enhanced / 'model.json', dict(signature=self.signature, model=packs.MODELS['video']))
        self.disc = self.cache / 'discs' / self.revision[:20]
        self.disc.mkdir(parents=True)
        packs.atomic_json(self.disc / 'identity.json', dict(content_sha256=self.revision, scenario=2))
        self.catalog = []
        self.world_asset = self.asset('world', '/TOWN.MPD', bytes((248, 32, 8, 255, 0, 0, 0, 0)))
        material = self.world / self.world_asset['id']
        material.mkdir()
        for source, name in ((self.cache / 'assets' / self.world_asset['id'] / 'original.rgba', 'original.rgba'),
                             (self.enhanced / self.world_asset['id'] / 'replacement.rgba', 'replacement.rgba')):
            (material / name).write_bytes(source.read_bytes())
        (material / 'asset.txt').write_text('SF3HDASSET1\n2 1\n8 4\n0 0 1 1\n')
        (material / 'metadata.json').write_text('{}')
        self.row = dict(scenario=2, revision=self.revision, profile='synthetic', model='video',
                        material_count=1, replacement_bytes=128, missing=[], path=str(self.world))
        packs.atomic_json(self.world / 'manifest.json', self.row)

    def asset(self, category, filename, original):
        identity = hashlib.sha256(b'2x1:' + original).hexdigest()
        asset = dict(id=identity, width=2, height=1, original_sha256=hashlib.sha256(original).hexdigest(),
                     refs=[dict(category=category, file=filename, location='sprite-0/frame-0')])
        directory = self.cache / 'assets' / identity
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'original.rgba').write_bytes(original)
        # Nearest-neighbour synthetic replacement preserves exactly all alpha texels.
        row = original[:4] * 4 + original[4:] * 4
        replacement = row * 4
        directory = self.enhanced / identity
        directory.mkdir(exist_ok=True)
        (directory / 'replacement.rgba').write_bytes(replacement)
        packs.atomic_json(directory / 'ready.json', dict(original_sha256=asset['original_sha256'],
                          rgba_sha256=hashlib.sha256(replacement).hexdigest(), tileable=False))
        self.catalog.append(asset)
        return asset

    def run_pack(self):
        packs.atomic_json(self.disc / 'catalog.json', self.catalog)
        return packs.package(self.cache, self.out, self.row)

    def test_only_character_formats_pack_and_sources_stay_unchanged(self):
        character = self.asset('sprites', '/XAIRO.CHR', bytes((32, 248, 8, 255, 0, 0, 0, 0)))
        character['refs'].append(dict(category='sprites', file='/BATTLE.CHP', location='same-frame'))
        ui = self.asset('sprites', '/MENU.BIN', bytes((64, 248, 8, 255, 0, 0, 0, 0)))
        embedded = self.asset('embedded', '/MENU.CHR', bytes((96, 248, 8, 255, 0, 0, 0, 0)))
        result = self.run_pack()
        directory = Path(result['path'])
        self.assertEqual(result['material_count'], 2)
        self.assertEqual(result['character_material_count'], 1)
        self.assertEqual(result['character_candidates'], 1)
        self.assertFalse((directory / ui['id']).exists())
        self.assertFalse((directory / embedded['id']).exists())
        self.assertTrue((directory / character['id'] / 'asset.txt').read_text().endswith('\ncharacter\n'))
        self.assertEqual((directory / self.world_asset['id'] / 'asset.txt').read_text(),
                         (self.world / self.world_asset['id'] / 'asset.txt').read_text())
        self.assertEqual((directory / character['id'] / 'replacement.rgba').read_bytes(),
                         (self.enhanced / character['id'] / 'replacement.rgba').read_bytes())
        self.assertEqual(result['missing'], [])
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.run_pack()

    def test_shared_world_sprite_promotes_independent_descriptor_only(self):
        self.world_asset['refs'].append(dict(category='sprites', file='/HERO.CHP', location='frame-0'))
        before = (self.world / self.world_asset['id'] / 'asset.txt').read_bytes()
        result = self.run_pack()
        self.assertEqual(result['material_count'], 1)
        self.assertEqual(result['character_frames_already_world'], 1)
        self.assertEqual((self.world / self.world_asset['id'] / 'asset.txt').read_bytes(), before)
        self.assertTrue((Path(result['path']) / self.world_asset['id'] / 'asset.txt').read_text().endswith('character\n'))

    def test_bad_alpha_is_a_gap_even_with_valid_checksum(self):
        asset = self.asset('sprites', '/HERO.CHR', bytes((8, 8, 248, 255, 0, 0, 0, 0)))
        directory = self.enhanced / asset['id']
        replacement = bytearray((directory / 'replacement.rgba').read_bytes())
        replacement[19] = 255  # Pixel which must remain transparent.
        (directory / 'replacement.rgba').write_bytes(replacement)
        ready = packs.read_json(directory / 'ready.json')
        ready['rgba_sha256'] = hashlib.sha256(replacement).hexdigest()
        packs.atomic_json(directory / 'ready.json', ready)
        result = self.run_pack()
        self.assertEqual(result['material_count'], 1)
        self.assertIn('transparency', result['missing'][0]['error'])
        self.assertFalse((Path(result['path']) / asset['id']).exists())

    def test_corrupt_shared_alpha_cannot_promote_a_world_material(self):
        self.world_asset['refs'].append(dict(category='sprites', file='/HERO.CHP', location='frame-0'))
        replacement_path = self.world / self.world_asset['id'] / 'replacement.rgba'
        replacement = bytearray(replacement_path.read_bytes())
        replacement[19] = 255
        replacement_path.write_bytes(replacement)
        ready_path = self.enhanced / self.world_asset['id'] / 'ready.json'
        ready = packs.read_json(ready_path)
        ready['rgba_sha256'] = hashlib.sha256(replacement).hexdigest()
        packs.atomic_json(ready_path, ready)
        result = self.run_pack()
        self.assertEqual(result['character_frames_already_world'], 0)
        self.assertEqual(len(result['missing']), 1)
        self.assertFalse((Path(result['path']) / self.world_asset['id'] / 'asset.txt').read_text().endswith('character\n'))

    def test_corrupt_cache_and_missing_cache_are_visible_gaps(self):
        bad = self.asset('sprites', '/HERO.CHR', bytes((8, 248, 248, 255, 0, 0, 0, 0)))
        missing = self.asset('sprites', '/HERO.CHP', bytes((248, 8, 248, 255, 0, 0, 0, 0)))
        (self.enhanced / bad['id'] / 'replacement.rgba').write_bytes(b'corrupt')
        (self.enhanced / missing['id'] / 'ready.json').unlink()
        result = self.run_pack()
        self.assertEqual(len(result['missing']), 2)
        self.assertEqual(result['character_material_count'], 0)

    def test_rejects_ambiguous_model_or_unsafe_identity(self):
        with self.assertRaises(ValueError):
            packs.identity('../outside')
        extra = self.cache / 'enhanced' / 'ambiguous'
        extra.mkdir()
        packs.atomic_json(extra / 'model.json', dict(signature=self.signature, model=packs.MODELS['video']))
        with self.assertRaisesRegex(ValueError, 'exactly one model'):
            self.run_pack()

    def test_alpha_checks_every_row_and_dimension(self):
        original = bytes((8, 8, 8, 255, 8, 8, 8, 0)) * 2
        row = original[:4] * 4 + original[4:8] * 4
        replacement = row * 8
        self.assertTrue(packs.exact_alpha(original, replacement, 2, 2))
        self.assertFalse(packs.exact_alpha(original, replacement[:-1], 2, 2))
        replacement = bytearray(replacement)
        replacement[-1] = 255
        self.assertFalse(packs.exact_alpha(original, replacement, 2, 2))


if __name__ == '__main__':
    unittest.main()
