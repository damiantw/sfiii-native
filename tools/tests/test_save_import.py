import importlib.util
import base64
import datetime
import json
import struct
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('save_import', Path(__file__).resolve().parents[1]/'import-saturn-save.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ImportTests(unittest.TestCase):
    def archive(self, root):
        data = (16240).to_bytes(4,'big') + (7).to_bytes(4,'big') + b'\x07' + bytes(16239)
        obj = dict(version=1, metadata=dict(filename='SFORCE32_03', comment='Medion', language=0,
                   saveDate='2026/10/20 13:52:00', dataSize=len(data)),
                   dataBase64=base64.b64encode(data).decode(), screenshotBase64='ignored')
        path = root/'renamed.ysbak';path.write_text(json.dumps(obj))
        return path, obj, data

    def test_scenario2_archive_preserves_metadata_and_ignores_screenshot_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path,obj,data=self.archive(root)
            original=path.read_bytes()
            obj['metadata']['screenshotUrl']='https://example.invalid/never-fetch'
            path.write_text(json.dumps(obj)); original=path.read_bytes()
            backup=root/'backup.bin'
            module.import_files(backup,'cartridge',[path])
            record=module.records(Path(str(backup)+'.cartridge').read_bytes())['SFORCE32_03']
            self.assertEqual(record[32:],data)
            self.assertEqual(record[:24],b'SFORCE32_03\0Medion\0\0\0\0\0\0')
            date=int((datetime.datetime(2026,10,20,13,52)-datetime.datetime(1980,1,1)).total_seconds()/60)
            self.assertEqual(struct.unpack_from('<II',record,24),(date,16248))
            self.assertEqual(path.read_bytes(),original)

    def test_archive_rejects_invalid_headers_payload_and_metadata_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path,obj,data=self.archive(root);backup=root/'backup.bin'
            module.import_files(backup,'internal',[path]);before=backup.read_bytes()
            for field,value in [('version',2),('dataBase64','!invalid!'),('dataBase64',base64.b64encode(data[:-1]).decode()),('metadata',[]),('metadata',{**obj['metadata'],'dataSize':1}),('metadata',{**obj['metadata'],'filename':'../../bad'}),('metadata',{**obj['metadata'],'language':True}),('metadata',{**obj['metadata'],'comment':'x'*12}),('metadata',{**obj['metadata'],'saveDate':'bad'})]:
                with self.subTest(field=field,value=value):
                    path.write_text(json.dumps({**obj,field:value}))
                    with self.assertRaises(ValueError):module.import_files(backup,'internal',[path],True)
                    self.assertEqual(backup.read_bytes(),before)
            path.write_text(json.dumps({**obj,'dataBase64':base64.b64encode(data[:-1]+b'\xff').decode()}))
            with self.assertRaisesRegex(ValueError,'checksum'):module.raw_record(path)

    def test_scenario2_capacity_and_raw_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path,obj,data=self.archive(root);backup=root/'backup.bin'
            raw=root/'SFORCE32_04.BIN';raw.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'space'):module.import_files(backup,'internal',[path,raw])
            self.assertFalse(backup.exists())
            module.import_files(backup,'cartridge',[path,raw])
            self.assertEqual(len(module.records(Path(str(backup)+'.cartridge').read_bytes())),2)

    def fixture(self, root, slot):
        payload = bytes([slot]) + bytes(12895)
        path = root/f'SFORCE31_{slot:02d}.BIN'
        path.write_bytes((12896).to_bytes(4,'big') + sum(payload).to_bytes(4,'big') + payload)
        return path

    def test_preserves_payload_existing_records_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); a=self.fixture(root,1); b=self.fixture(root,2); backup=root/'backup.bin'
            module.import_files(backup,'internal',[a]); previous=backup.read_bytes()
            report=module.import_files(backup,'internal',[b]); entries=module.records(backup.read_bytes())
            self.assertEqual(entries[a.stem][32:],a.read_bytes())
            self.assertEqual(entries[b.stem][32:],b.read_bytes())
            self.assertEqual(Path(report['previous']).read_bytes(),previous)
            before=backup.read_bytes()
            with self.assertRaises(ValueError): module.import_files(backup,'internal',[b])
            self.assertEqual(backup.read_bytes(),before)

    def test_bad_checksum_and_full_internal_are_rejected_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); saves=[self.fixture(root,i) for i in (1,2,3)]; backup=root/'backup.bin'
            module.import_files(backup,'internal',saves[:2]); previous=backup.read_bytes()
            with self.assertRaises(ValueError): module.import_files(backup,'internal',[saves[2]])
            self.assertEqual(backup.read_bytes(),previous)
            module.import_files(backup,'cartridge',saves)
            self.assertEqual(len(module.records(Path(str(backup)+'.cartridge').read_bytes())),3)
            saves[2].write_bytes(saves[2].read_bytes()[:-1]+b'\xff')
            with self.assertRaises(ValueError): module.import_files(backup,'internal',[saves[2]])
            self.assertEqual(backup.read_bytes(),previous)


if __name__ == '__main__': unittest.main()
