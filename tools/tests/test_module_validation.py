"""Invented module metadata: distinguish build success, unknown mappings and execution."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
import json
import subprocess
import sys

spec = importlib.util.spec_from_file_location('module_validation', Path(__file__).resolve().parents[1]/'validate-modules.py')
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


class ModuleValidation(unittest.TestCase):
    def test_missing_mapping_and_missing_export_do_not_pass_with_an_existing_build(self):
        profile = {'modules':[{'name':'KNOWN','file':'KNOWN.BIN'}]}
        rows = [dict(file='KNOWN.BIN',status='configured',entry_points=['06001000','06001008']),
                dict(file='UNKNOWN.BIN',status='needs-load-address-review')]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'p_known_table.cpp').write_text('{0x06001000u, f_example}')
            result = validation.matrix({'modules':rows},profile,root,True,{'KNOWN'})
            self.assertFalse(result[0]['compiled'])
            self.assertEqual(result[0]['missing_entries'],['06001008'])
            self.assertTrue(result[0]['executed_in_tested_routes'])
            self.assertFalse(result[1]['mapped'])
            self.assertFalse(result[1]['compiled'])
            self.assertTrue(all(not r['gameplay_certified'] for r in result))

    def test_emission_and_a_built_file_do_not_hide_discovery_or_indirect_findings(self):
        profile = {'modules':[{'name':'KNOWN','file':'KNOWN.BIN'}]}
        audit = {'modules':[dict(file='KNOWN.BIN',status='configured',entry_points=['06001000'],
                                 problems=[{'reason':'invented invalid path'}],unresolved=[{'kind':'indirect call'}])]}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d);(root/'p_known_table.cpp').write_text('{0x06001000u, f_example}')
            row = validation.matrix(audit,profile,root,True,set())[0]
            self.assertTrue(row['compiled'])
            self.assertFalse(row['executed_in_tested_routes'])
            self.assertFalse(row['gameplay_certified'])
            self.assertEqual((row['discovery_problems'],row['indirect_sites']),(1,1))
            self.assertFalse(validation.matrix(audit,profile,root,False,set())[0]['compiled'])

    def test_mapping_conflict_cannot_be_accepted_from_a_table_at_the_expected_address(self):
        profile = {'modules':[{'name':'KNOWN','file':'KNOWN.BIN'}]}
        audit = {'modules':[dict(file='KNOWN.BIN',status='needs-load-address-review',
                                 mapping_conflict='invented conflicting bases',entry_points=['06001000'])]}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d);(root/'p_known_table.cpp').write_text('{0x06001000u, f_example}')
            row = validation.matrix(audit,profile,root,True,{'KNOWN'})[0]
            self.assertFalse(row['mapped']);self.assertFalse(row['compiled'])

    def test_reuse_accepts_extra_discovered_entries_but_rejects_changed_revision_or_image_extent(self):
        source = dict(content_sha256='invented-disc',model_bases={},modules=[
            dict(name='KNOWN',file='KNOWN.BIN',base='06001000',bytes='80',seeds=['06001000'])])
        candidate = copy.deepcopy(source);candidate['modules'][0]['seeds'].append('06001008')
        validation.verify_reused_profile(source,candidate)
        for field in ('content_sha256','model_bases'):
            changed=copy.deepcopy(candidate);changed[field]='changed'
            with self.subTest(field=field),self.assertRaises(ValueError):validation.verify_reused_profile(source,changed)
        for field,value in [('base','06002000'),('bytes','40'),('seeds',[])]:
            changed=copy.deepcopy(candidate);changed['modules'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validation.verify_reused_profile(source,changed)

    def test_missing_inventory_is_unavailable_and_fails_instead_of_passing_an_empty_suite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cue=root/'invented.cue';cue.touch()
            config=dict(cmake='not-invoked',revisions=[dict(id='synthetic-missing',
                profile=str(validation.ROOT/'profiles/usa-v1.001.json'),inventory=str(root/'absent'),cue=str(cue))])
            manifest=root/'manifest.json';manifest.write_text(json.dumps(config));out=root/'results'
            process=subprocess.run([sys.executable,'-B',str(Path(validation.__file__)),
                                    '--manifest',str(manifest),'--out',str(out)],capture_output=True,text=True)
            self.assertNotEqual(process.returncode,0)
            result=json.loads((out/'report.json').read_text())
            self.assertFalse(result['mapped_module_builds_passed'])
            self.assertFalse(result['complete_static_validation'])
            row=result['revisions'][0];self.assertFalse(row['available']);self.assertFalse(row['build_gate_passed'])
            self.assertIn('inventory unavailable',row['error'])


if __name__ == '__main__':
    unittest.main()
