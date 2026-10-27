"""Revision selection boundaries: no game bytes or guessed mappings."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from disc_profile import (LEGACY_PROFILE_FILES, LEGACY_PROFILE_IDS, canonical_profile_id, profile_scenario,
                          registered_profiles)

ROOT=Path(__file__).resolve().parents[2]


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


class RetiredProfileIdTests(unittest.TestCase):
    """Folders prepared under a retired id (the fork's scenario1-usa-translation-v25_1) keep working."""
    def test_retired_ids_resolve_to_a_registered_profile_of_the_same_game(self):
        registered={p["id"]:(path.name,p) for path,p in registered_profiles()}
        self.assertTrue(LEGACY_PROFILE_IDS)
        for old,new in LEGACY_PROFILE_IDS.items():
            self.assertNotIn(old,registered)
            self.assertIn(new,registered)
            self.assertEqual(canonical_profile_id(old),new)
            self.assertEqual(profile_scenario(old),registered[new][1]["scenario"])
        for old,new in LEGACY_PROFILE_FILES.items():
            self.assertFalse((ROOT/"profiles"/old).exists())
            self.assertIn(new,{name for name,_ in registered.values()})
        self.assertEqual(canonical_profile_id("scenario1-usa-v1_001"),"scenario1-usa-v1_001")
        self.assertEqual(profile_scenario("scenario1-usa-translation-v25_1"),1)

    def test_a_retired_id_cannot_be_registered_again(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"old.json").write_text(json.dumps(dict(id=next(iter(LEGACY_PROFILE_IDS)),scenario=1)))
            with self.assertRaisesRegex(ValueError,"profile ID"):registered_profiles(root)

    def test_alias_copies_stay_in_sync(self):
        sys.path.insert(0,str(ROOT/"desktop"))
        import ai_packs
        from sf3test import memory_map
        self.assertEqual(ai_packs.LEGACY_PROFILES,{**LEGACY_PROFILE_IDS,**LEGACY_PROFILE_FILES})
        cs=(ROOT/"desktop/Launcher.cs").read_text(encoding="utf-8")
        for old,new in LEGACY_PROFILE_IDS.items():self.assertIn("{\""+old+"\", \""+new+"\"}",cs)
        for old,new in LEGACY_PROFILE_FILES.items():
            self.assertEqual(memory_map.canonical(old),new[:-5])
            self.assertEqual(memory_map.lookup(old[:-5])["profile"],new[:-5])

    def test_artwork_records_under_a_retired_id_still_match(self):
        sys.path.insert(0,str(ROOT/"desktop"))
        import ai_packs
        with tempfile.TemporaryDirectory() as folder:
            game=Path(folder)/"game";game.mkdir()
            (game/"game.json").write_text(json.dumps(dict(profile_id="scenario1-usa-translation-v25_1",cue="never-read.cue")))
            _,profile=ai_packs.disc_profile(game,ROOT/"profiles")
        self.assertEqual(profile["id"],"scenario1-translation-v25_1")
        for value in ("scenario1-usa-translation-v25_1","scenario1-usa-v25_1.json","scenario1-translation-v25_1","scenario1-v25_1.json"):
            self.assertTrue(ai_packs.matches_profile(value,profile),value)
        self.assertFalse(ai_packs.matches_profile("usa-v1.001.json",profile))
        self.assertFalse(ai_packs.matches_profile(["not","text"],profile))
