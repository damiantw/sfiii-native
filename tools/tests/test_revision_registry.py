"""Revision selection boundaries: no game bytes or guessed mappings."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from disc_profile import registered_profiles, profile_scenario


class RegistryTests(unittest.TestCase):
    def test_multiple_revisions_select_same_game_without_accepting_unknowns(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for identifier,scenario in [('second-old',2),('second-new',2),('premium',4)]:
                (root/(identifier+'.json')).write_text(json.dumps(dict(id=identifier,scenario=scenario)))
            self.assertEqual(profile_scenario('second-old',root),2)
            self.assertEqual(profile_scenario('second-new',root),2)
            self.assertEqual(profile_scenario('premium',root),4)
            self.assertIsNone(profile_scenario('unknown-translation',root))

    def test_duplicates_and_invalid_game_ids_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('a','b'):
                (root/(name+'.json')).write_text(json.dumps(dict(id='duplicate',scenario=2)))
            with self.assertRaisesRegex(ValueError,'duplicate'):registered_profiles(root)
            (root/'b.json').unlink()
            (root/'a.json').write_text(json.dumps(dict(id='invalid',scenario=True)))
            with self.assertRaisesRegex(ValueError,'scenario'):registered_profiles(root)
