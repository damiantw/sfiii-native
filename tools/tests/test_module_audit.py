"""Invented images: cross-module discovery, ambiguous overlays and hash rejection."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1]/'audit-modules.py'
sys.path.insert(0,str(TOOL.parent))
spec = importlib.util.spec_from_file_location('module_audit',TOOL)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
    def test_veneer_requires_in_image_even_target_and_complete_record(self):
        veneer = audit.VENEER
        self.assertEqual(audit.veneers(veneer+bytes.fromhex('06004000'),0x06004000),{0x06004000})
        for literal in ('06004001','06008000'):
            self.assertFalse(audit.veneers(veneer+bytes.fromhex(literal),0x06004000))
        self.assertFalse(audit.veneers(veneer+b'\x06\x00',0x06004000))

    def exercise(self, ambiguous=False, corrupt=False):
        with tempfile.TemporaryDirectory(prefix='sf3-audit-test-') as directory:
            w = Path(directory);(w/'extract').mkdir()
            # Caller saves PR, loads a cross-module function pointer and calls it.
            boot = audit.VENEER+bytes.fromhex('0600400c4f22d003400b00094f26000b0009000906080018')
            other = bytearray(40)
            other[:16] = audit.VENEER+bytes.fromhex('0608000c000b0009')
            other[24:28] = bytes.fromhex('000b0009')  # Not otherwise referenced locally.
            files = {'1ST.BIN':boot,'OTHER.BIN':bytes(other)}
            modules = [dict(name='BOOT',file='1ST.BIN',base='06004000',seeds=['06004000']),
                       dict(name='OTHER',file='OTHER.BIN',base='06080000',seeds=['06080000'],overlay=True)]
            if ambiguous:
                files['ALTERNATE.BIN'] = bytes(other)
                modules.append(dict(name='ALTERNATE',file='ALTERNATE.BIN',base='06080000',
                                    seeds=['06080000'],overlay=True))
            for name,data in files.items(): (w/'extract'/name).write_bytes(data)
            (w/'manifest.json').write_text(json.dumps({'files':{'/'+name:{'size':len(data),
                'sha1':hashlib.sha1(data).hexdigest()} for name,data in files.items()}}))
            (w/'hashes.json').write_text(json.dumps({'invented Track 1':{'sha256':'invented-revision'}}))
            (w/'profile.json').write_text(json.dumps({'track1_sha256':'invented-revision','modules':modules}))
            if corrupt:(w/'extract/OTHER.BIN').write_bytes(b'changed')
            result = subprocess.run([sys.executable,'-B',str(TOOL),'--work',str(w),'--out',str(w/'out'),
                                     '--profile',str(w/'profile.json')],capture_output=True,text=True)
            if corrupt:
                self.assertNotEqual(result.returncode,0)
                self.assertIn('Extracted file changed',result.stderr)
                return
            self.assertEqual(result.returncode,0,result.stderr)
            report = json.loads((w/'out/module-audit.json').read_text())
            promoted = report['cross_module_promoted_entries']
            if ambiguous:
                self.assertFalse(promoted)
                self.assertTrue(any(g['target']=='06080018' and g['status']=='ambiguous-overlay'
                                    for g in report['cross_module_gaps']))
            else:
                self.assertTrue(any(p['file']=='OTHER.BIN' and p['entry']=='06080018' for p in promoted))
                profile = json.loads((w/'out/candidate-profile.json').read_text())
                self.assertIn('06080018',profile['modules'][1]['seeds'])

    def test_cross_module_call_promotes_a_clean_entry(self): self.exercise()
    def test_ambiguous_overlay_target_is_not_broadcast(self): self.exercise(ambiguous=True)
    def test_changed_extracted_file_is_rejected(self): self.exercise(corrupt=True)


if __name__ == '__main__': unittest.main()
