"""Invented overlay containers: preserve identity, bounds and distinct same-address images."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOLS))
from module_images import expand_modules, image_bytes, verified_source


class ModuleImages(unittest.TestCase):
    def test_stack_return_configuration_requires_a_complete_saved_pr_wrapper(self):
        module=dict(file='UNIT.BIN',base='06010000',stack_return_calls=['06010002'])
        raw=bytes.fromhex('4f22400b00094f26')
        self.assertEqual(image_bytes(module,raw),raw)
        for pc in ('06010000','06010001','06010004','06010008'):
            with self.subTest(pc=pc),self.assertRaisesRegex(ValueError,'verified PR-save'):
                image_bytes({**module,'stack_return_calls':[pc]},raw)
        for at in (0,2,6):
            corrupt=bytearray(raw);corrupt[at]^=1
            with self.subTest(at=at),self.assertRaisesRegex(ValueError,'verified PR-save'):
                image_bytes(module,corrupt)

    def test_entry_boundaries_and_wrapping_load_addresses(self):
        # A complete SH-2 instruction must fit; an odd trailing byte is not code.
        module=dict(file='UNIT.BIN',base='06010000',seeds=['06010000','06010002'])
        self.assertEqual(image_bytes(module,b'\0'*5),b'\0'*5)
        for seed in ('0600FFFE','06010001','06010004','06010006'):
            with self.subTest(seed=seed),self.assertRaisesRegex(ValueError,'Module entry'):
                image_bytes({**module,'seeds':[seed]},b'\0'*5)
        for base in ('-2','06010001','FFFFFFFE'):
            with self.subTest(base=base),self.assertRaisesRegex(ValueError,'load address'):
                image_bytes({**module,'base':base,'seeds':[]},b'\0'*5)
        self.assertEqual(image_bytes(dict(file='UNIT.BIN',base='FFFFFFFE',seeds=['FFFFFFFE']),b'\0'*2),b'\0'*2)

    def test_audit_and_generation_reject_invalid_flat_module_entries(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);_,manifest,_=self.fixture(root)
            (root/'manifest.json').write_text(json.dumps(manifest))
            (root/'hashes.json').write_text(json.dumps({'track':{'sha256':'invented'}}))
            profile=dict(track1_sha256='invented',modules=[dict(name='PACK',file='PACK.BIN',
                base='06010000',seeds=['06010080'],overlay=True)])
            (root/'profile.json').write_text(json.dumps(profile))
            for tool,extra in [('audit-modules.py',[]),('generate.py',['--framework','saturn-recomp'])]:
                command=[sys.executable,'-X','utf8','-B',str(TOOLS/tool),'--work',str(root),
                         '--profile',str(root/'profile.json'),'--out',str(root/tool),*extra]
                result=subprocess.run(command,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('Module entry is outside',result.stderr)

    def test_export_target_needs_a_complete_instruction(self):
        module=dict(file='UNIT.BIN',base='06010000',required_veneer_offsets=[0])
        header=bytes.fromhex('d001402b000900090601000c')
        with self.assertRaisesRegex(ValueError,'export points outside'):
            image_bytes(module,header+b'\0')
        self.assertEqual(image_bytes(module,header+b'\0\x09'),header+b'\0\x09')

    def fixture(self, root):
        (root/'extract').mkdir()
        def chunk(value):
            veneer=bytes.fromhex('d001402b00090009')+bytes.fromhex('06010024')
            return (veneer*3+bytes([0xE0,value])+bytes.fromhex('000b0009')).ljust(64,b'\0')
        raw=chunk(1)+chunk(2)
        (root/'extract/PACK.BIN').write_bytes(raw)
        manifest=dict(files={'/PACK.BIN':dict(size=len(raw),sha1=hashlib.sha1(raw).hexdigest())})
        profile=dict(track1_sha256='invented',modules=[],module_containers=[dict(
            file='PACK.BIN',prefix='EFFECT_',base='06010000',chunk_bytes='40',count=2,
            entry_offsets=[0,12,24],evidence='Invented fixed-size loader fixture')])
        return profile,manifest,raw

    def test_first_and_last_images_have_distinct_identity_and_expand_idempotently(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);profile,manifest,raw=self.fixture(root)
            modules=expand_modules(profile,manifest)
            self.assertEqual([m['offset'] for m in modules],['0','40'])
            self.assertEqual([m['base'] for m in modules],['06010000']*2)
            images=[image_bytes(m,verified_source(root,m,manifest)[1]) for m in modules]
            self.assertEqual(images,[raw[:64],raw[64:]])
            self.assertNotEqual(hashlib.sha256(images[0]).digest(),hashlib.sha256(images[1]).digest())
            expanded={**profile,'modules':modules}
            expanded['modules'][0]['seeds'].append('06010024')
            self.assertEqual(expand_modules(expanded,manifest),expanded['modules'])

    def test_wrong_layout_collisions_and_out_of_range_slices_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);profile,manifest,raw=self.fixture(root)
            for key,value in [('count',3),('chunk_bytes','20'),('base','06010001'),('entry_offsets',[64]),('prefix','../escape')]:
                changed=copy.deepcopy(profile);changed['module_containers'][0][key]=value
                with self.subTest(field=key),self.assertRaises(ValueError):expand_modules(changed,manifest)
            module=expand_modules(profile,manifest)[0]
            for key,value in [('offset','-1'),('offset','80'),('bytes','81')]:
                changed={**module,key:value}
                with self.subTest(field=key,value=value),self.assertRaises(ValueError):image_bytes(changed,raw)
            collided={**profile,'modules':[{**module,'base':'06020000'}]}
            with self.assertRaises(ValueError):expand_modules(collided,manifest)

    def test_whole_container_hash_and_each_export_are_checked(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);profile,manifest,raw=self.fixture(root);module=expand_modules(profile,manifest)[0]
            # Damage outside the selected slice must still invalidate its source.
            damaged=bytearray(raw);damaged[-1]^=1;(root/'extract/PACK.BIN').write_bytes(damaged)
            with self.assertRaisesRegex(ValueError,'changed'):verified_source(root,module,manifest)
            for literal in ('06010041','06020000'):
                damaged=bytearray(raw);damaged[8:12]=bytes.fromhex(literal)
                with self.subTest(literal=literal),self.assertRaisesRegex(ValueError,'outside'):image_bytes(module,damaged)

    def test_audit_and_emitter_include_both_images_as_callable_overlays(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);profile,manifest,raw=self.fixture(root)
            (root/'manifest.json').write_text(json.dumps(manifest))
            (root/'hashes.json').write_text(json.dumps({'invented track':{'sha256':'invented'}}))
            (root/'profile.json').write_text(json.dumps(profile));out=root/'audit';generated=root/'generated'
            commands=[['audit-modules.py','--work',root,'--profile',root/'profile.json','--out',out],
                      ['generate.py','--framework','saturn-recomp','--work',root,'--profile',out/'candidate-profile.json','--out',generated],
                      ['check-module-build.py','--audit',out/'module-audit.json','--generated',generated,'--out',root/'emission.json','--player']]
            for name,*args in commands:
                p=subprocess.run([sys.executable,'-X','utf8','-B',str(TOOLS/name),*map(str,args)],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            report=json.loads((out/'module-audit.json').read_text());self.assertEqual(report['bulk_modules'],2)
            self.assertEqual(report['blockers'],[])
            self.assertEqual({m['source_file'] for m in report['modules']},{'PACK.BIN'})
            self.assertFalse((root/'extract/EFFECT_00.BIN').exists())
            for index in range(2):
                table=(generated/f'p_effect_{index:02x}_table.cpp').read_text()
                self.assertIn('true',table)
                self.assertEqual((root/'modules'/f'EFFECT_{index:02X}.BIN').read_bytes(),raw[index*64:(index+1)*64])
            # Direct generation from the compact source profile must also mark
            # every derived image callable, without relying on prior expansion.
            direct=root/'direct'
            p=subprocess.run([sys.executable,'-X','utf8','-B',str(TOOLS/'generate.py'),
                '--framework','saturn-recomp','--work',str(root),'--profile',str(root/'profile.json'),
                '--out',str(direct)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            for index in range(2):self.assertIn('true',(direct/f'p_effect_{index:02x}_table.cpp').read_text())


if __name__=='__main__':unittest.main()
