"""Synthetic writer tests; fixtures use the external system temporary directory."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'offline-assets' / 'index_packs.py'
SPEC = importlib.util.spec_from_file_location('sf3_index_packs', SOURCE)
index = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(index)


class PackIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'manifest.json').write_text('{}', encoding='utf-8')
        self.material = self.root / ('a' * 64)
        self.material.mkdir()
        (self.material / 'asset.txt').write_text('SF3HDASSET1\n1 1\n4 4\n0 0 1 1\ncharacter\n')
        (self.material / 'original.rgba').write_bytes(bytes((248, 0, 0, 255)))
        (self.material / 'replacement.rgba').write_bytes(bytes((0, 248, 0, 255)) * 16)

    def test_format_and_integrity_match_native_contract(self):
        report = index.build_index(self.root)
        data = (self.root / index.NAME).read_bytes()
        magic, version, header, total, marker_hash, body_hash, count, reserved, marker_size, tail = index.HEADER.unpack_from(data)
        self.assertEqual((magic, version, header, total, count, reserved, marker_size, tail),
                         (b'SF3HDIX1', 1, 64, len(data), 1, 0, 2, 0))
        self.assertEqual(marker_hash, index.fnv(b'{}'))
        self.assertEqual(body_hash, index.fnv(data[64:]))
        fields = index.RECORD.unpack_from(data, 64)
        self.assertEqual(fields[:8], (1, 1, 4, 4, 1, 81, 4, 0))
        self.assertEqual(fields[8:], (0., 0., 1., 1.))
        self.assertEqual(data[112:-4], ('a' * 64 + '/replacement.rgba').encode('ascii'))
        self.assertEqual(data[-4:], bytes((248, 0, 0, 255)))
        self.assertEqual(report['materials'], 1)

    def test_bad_payload_preserves_previous_index_and_cleans_temporary(self):
        index.build_index(self.root)
        before = (self.root / index.NAME).read_bytes()
        (self.material / 'replacement.rgba').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'payload size'):
            index.build_index(self.root)
        self.assertEqual((self.root / index.NAME).read_bytes(), before)
        self.assertFalse(list(self.root.glob('.sf3idx-*')))

    def test_changed_manifest_aborts_atomic_publish(self):
        index.build_index(self.root)
        before = (self.root / index.NAME).read_bytes()
        original = index.material
        def mutate(directory):
            result = original(directory)
            (self.root / 'manifest.json').write_text(json.dumps(dict(revision=2)))
            return result
        with mock.patch.object(index, 'material', mutate):
            with self.assertRaisesRegex(ValueError, 'changed during indexing'):
                index.build_index(self.root)
        self.assertEqual((self.root / index.NAME).read_bytes(), before)
        self.assertFalse(list(self.root.glob('.sf3idx-*')))

    def test_nonfinite_uv_and_unsafe_material_names_rejected(self):
        (self.material / 'asset.txt').write_text('SF3HDASSET1\n1 1\n4 4\nnan 0 1 1\n')
        with self.assertRaisesRegex(ValueError, 'UV'):
            index.build_index(self.root)
        self.material.rename(self.root / '.hidden')
        with self.assertRaisesRegex(ValueError, 'Unsafe material'):
            index.build_index(self.root)

    def test_builder_report_avoids_recursive_payload_scan_and_rejects_escape(self):
        parent = self.root / 'collection'
        pack = parent / 'pack'
        pack.mkdir(parents=True)
        self.material.rename(pack / self.material.name)
        (self.root / 'manifest.json').rename(pack / 'manifest.json')
        report = parent / 'packs-report.json'
        report.write_text(json.dumps([dict(path=str(pack))]))
        with mock.patch.object(sys, 'argv', ['index_packs.py', str(parent)]), \
                mock.patch.object(Path, 'rglob', side_effect=AssertionError('Recursive discovery is unnecessary')), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(index.main(), 0)
        self.assertTrue((pack / index.NAME).is_file())
        report.write_text(json.dumps([dict(path=str(self.root))]))
        with mock.patch.object(sys, 'argv', ['index_packs.py', str(parent)]):
            with self.assertRaisesRegex(ValueError, 'escapes'):
                index.main()


if __name__ == '__main__':
    unittest.main()
