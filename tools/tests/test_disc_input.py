"""Synthetic CHD boundary/cache tests; no game images are included."""
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'desktop'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import disc_input
from disc_profile import content_id, verify_inventory, identify

class DiscInputTests(unittest.TestCase):
    def test_chd_extracts_once_and_revalidates_cache(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'disc 測試.CHD';source.write_bytes(b'synthetic compressed data')
            tool=root/'chdman.exe';tool.touch()
            def fake(command,**kwargs):
                if command[1]=='extractcd':
                    Path(command[command.index('-o')+1]).write_text('synthetic cue')
                    Path(command[command.index('-ob')+1]).write_bytes(b'synthetic track')
                return types.SimpleNamespace(returncode=0)
            with patch.object(disc_input.subprocess,'run',side_effect=fake) as run:
                cue=disc_input.resolve_disc(source,root/'work',tool,io.StringIO(),lambda *a:None)
                self.assertEqual(run.call_count,2)
                self.assertEqual(disc_input.resolve_disc(source,root/'work',tool,io.StringIO(),lambda *a:None),cue)
                self.assertEqual(run.call_count,2)
                cue.with_name('disc.bin').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'cached CHD extraction changed'):
                    disc_input.resolve_disc(source,root/'work',tool,io.StringIO(),lambda *a:None)
            self.assertEqual(source.read_bytes(),b'synthetic compressed data')

    def test_failed_chd_is_never_published_as_ready(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'bad.chd';source.touch();tool=root/'chdman.exe';tool.touch()
            with patch.object(disc_input.subprocess,'run',return_value=types.SimpleNamespace(returncode=1)):
                with self.assertRaisesRegex(ValueError,'verification or extraction failed'):
                    disc_input.resolve_disc(source,root/'work',tool,io.StringIO(),lambda *a:None)
            self.assertFalse(list((root/'work').rglob('receipt.json')))

    def test_cue_passthrough_needs_no_chd_tool(self):
        with tempfile.TemporaryDirectory() as d:
            cue=Path(d)/'disc.cue';cue.touch()
            self.assertEqual(disc_input.resolve_disc(cue,Path(d)/'work','missing',None,None),cue.resolve())

    def test_manifest_identity_detects_code_audio_and_ip_changes(self):
        original={'files':{'/BOOT':{'sha1':'synthetic','size':10}},'audio':{'02':{'sha1':'audio'}},'ip_sha1':'header'}
        for key in original:
            other={**original,key:{}}
            self.assertNotEqual(content_id(original),content_id(other))
        self.assertEqual(content_id(original),content_id(dict(reversed(list(original.items())))))

    def test_content_identity_accepts_other_track_layout_but_rejects_changed_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m={'files':{'/BOOT':{'sha1':'synthetic'}}}
            (root/'manifest.json').write_text(json.dumps(m));profile={'content_sha256':content_id(m)}
            self.assertEqual(verify_inventory(root,profile),m)
            (root/'manifest.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'contents do not match'):verify_inventory(root,profile)

    def test_same_translation_product_header_does_not_confuse_scenarios(self):
        # Both translations can use SF3TRANS. Only full content identity selects
        # the profile; a plausible header or a renamed dump is insufficient.
        import types
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            manifests=[{'files':{'/1ST.BIN':{'sha1':name,'size':64}},'audio':{},'ip_sha1':name}
                       for name in ('invented-scenario2','invented-scenario3')]
            for scenario,manifest in zip((2,3),manifests):
                (root/f'scenario{scenario}.json').write_text(json.dumps({'id':f'synthetic-{scenario}','scenario':scenario,'content_sha256':content_id(manifest)}))
            disc=types.SimpleNamespace(ip=types.SimpleNamespace(product='SF3TRANS',version='V25.1'))
            for scenario,manifest in zip((2,3),manifests):
                self.assertEqual(identify(disc,manifest,root)[1]['scenario'],scenario)
            for key in ('files','audio','ip_sha1'):
                changed={**manifests[1],key:'different contents'}
                with self.assertRaisesRegex(ValueError,'Unsupported disc contents'):identify(disc,changed,root)

if __name__=='__main__':unittest.main()
