"""Synthetic Git index checks; no real credentials or game files."""
import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('source_package',Path(__file__).resolve().parents[1]/'check-source-package.py')
checker=importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

class SourcePackageTests(unittest.TestCase):
    def exercise(self, name, text, tracked=True, changed_text=None):
        with tempfile.TemporaryDirectory(prefix='sf3-source-test-') as directory:
            root=Path(directory)
            subprocess.run(['git','init','-q',str(root)],check=True)
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
            subprocess.run(['git','-C',str(root),'add',name],check=True)
            if changed_text is not None:path.write_text(changed_text)
            old_root,old_argv=checker.ROOT,sys.argv
            try:
                checker.ROOT=root;sys.argv=['check-source-package.py']+(['--tracked'] if tracked else [])
                with contextlib.redirect_stdout(io.StringIO()):return checker.main()
            finally:checker.ROOT=old_root;sys.argv=old_argv

    def test_source_is_accepted(self):
        self.assertEqual(self.exercise('native/example.cpp','// Invented source\n'),0)

    def test_debug_and_binary_paths_are_rejected_even_as_plain_text(self):
        for name in ['native/save.bin','research/history.md','native/capture.json']:
            self.assertEqual(self.exercise(name,'Invented data'),1)

    def test_index_blob_is_checked_instead_of_working_copy(self):
        self.assertEqual(self.exercise('native/example.cpp','bad\0blob',changed_text='// Clean working copy'),1)

    def test_secret_and_personal_path_are_rejected(self):
        for text in ['ghp_'+'x'*32,'C:'+'\\Users\\'+'Example\\private.txt']:
            self.assertEqual(self.exercise('native/example.cpp',text),1)

if __name__=='__main__':unittest.main()
