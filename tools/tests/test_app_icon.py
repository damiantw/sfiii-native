"""Invented ICO containers; no game artwork is required by source tests."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('desktop_package',Path(__file__).resolve().parents[1]/'package-desktop.py')
package=importlib.util.module_from_spec(spec);spec.loader.exec_module(package)

class IconTests(unittest.TestCase):
    def test_ico_directory_bounds_and_image_payload_are_preserved(self):
        image=b'invented encoded image'
        valid=struct.pack('<HHH',0,1,1)+bytes([16,16,0,0])+struct.pack('<HHII',1,32,len(image),22)+image
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'art.ico';path.write_bytes(valid)
            self.assertEqual(package.read_icon(path),valid)
            for broken in (b'not an icon',valid[:5],valid[:21],valid[:-1],valid[:2]+b'\x02\0'+valid[4:],valid[:4]+b'\0\0'+valid[6:],valid[:18]+struct.pack('<I',6)+valid[22:]):
                path.write_bytes(broken)
                with self.subTest(size=len(broken)),self.assertRaises(ValueError):package.read_icon(path)

if __name__=='__main__':unittest.main()
