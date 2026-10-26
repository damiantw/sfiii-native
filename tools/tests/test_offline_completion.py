"""Exercise normal worker completion through the real character-pack subprocess."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'offline-assets'))
import test_character_packs as character_fixture

SOURCE = Path(__file__).resolve().parents[1] / 'offline-assets/worker.py'
spec = importlib.util.spec_from_file_location('offline_completion_worker', SOURCE)
worker = importlib.util.module_from_spec(spec)
try:
    import PIL
except ImportError:
    PIL = None
else:
    spec.loader.exec_module(worker)


@unittest.skipIf(PIL is None, 'Pillow is optional and unavailable in this runtime; graphics-builder completion unvalidated')
class OfflineCompletionTests(unittest.TestCase):
    def test_full_completion_produces_indexed_playable_character_report(self):
        fixture = character_fixture.CharacterPacksTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.asset('sprites', '/CHARACTERS.CHR', bytes((32, 248, 8, 255, 0, 0, 0, 0)))
        fixture.asset('embedded', '/MENU.BIN', bytes((64, 248, 8, 255, 0, 0, 0, 0)))
        worker.atomic_json(fixture.disc / 'catalog.json', fixture.catalog)
        worker.atomic_json(fixture.cache / 'inventory-report.json', [dict(counts=dict(extracted=2))])
        config = fixture.root / 'config.json'
        worker.atomic_json(config, dict(scenarios=[dict(scenario=2, disc='invented.cue')],
            models=['video'], categories=['world', 'sprites']))
        catalog = dict(scenario=2, profile='synthetic', assets={p['id']: p for p in fixture.catalog})
        ready = {p['id']: fixture.enhanced / p['id'] for p in fixture.catalog}
        args = ['worker.py', '--config', str(config), '--out', str(fixture.cache), '--app', str(SOURCE.parent)]
        # Skip only disc extraction and neural inference. Pack assembly, its child
        # process, alpha verification, indexing and final reports execute normally.
        with patch.object(worker.Job, 'inventory', return_value={fixture.revision: catalog}), \
             patch.object(worker.Job, 'enhance', return_value=({'video': dict(ready=ready, signature=fixture.signature)}, [])), \
             patch.object(sys, 'argv', args):
            self.assertEqual(worker.main(), 0)
        status = json.loads((fixture.cache / 'status.json').read_text())
        report = json.loads((fixture.cache / 'playable-packs-report.json').read_text())
        self.assertEqual(status['state'], 'complete')
        self.assertEqual(status['character_packs'], 1)
        self.assertEqual(report[0]['world_material_count'], 1)
        self.assertEqual(report[0]['character_material_count'], 1)
        self.assertEqual(report[0]['material_count'], 2)
        self.assertEqual(report[0]['missing'], [])
        self.assertTrue((Path(report[0]['path']) / 'materials.sf3idx').is_file())


if __name__ == '__main__':
    unittest.main()
