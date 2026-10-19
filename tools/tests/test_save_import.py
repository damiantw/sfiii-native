import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('save_import', Path(__file__).resolve().parents[1]/'import-saturn-save.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ImportTests(unittest.TestCase):
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
