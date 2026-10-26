"""Validate the optional first-run downloader with synthetic files, never game data."""
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

SOURCE = Path(__file__).resolve().parents[1] / 'offline-assets/bootstrap.py'
spec = importlib.util.spec_from_file_location('offline_bootstrap', SOURCE)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def test_verified_cached_archive_does_not_contact_upstream(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            payload = b'Invented portable tool archive'
            archive = cache / 'test.zip'; archive.write_bytes(payload)
            record = dict(filename=archive.name, url='https://invalid.invalid/must-not-be-contacted',
                          sha256=hashlib.sha256(payload).hexdigest())
            self.assertEqual(bootstrap.download(record, cache), archive)

    def test_corrupt_cache_is_replaced_by_verified_sha512_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); cache = root / 'cache'; cache.mkdir()
            source = root / 'source'; source.write_bytes(b'Invented clean upstream bytes')
            archive = cache / 'sdk.zip'; archive.write_bytes(b'corrupted')
            record = dict(filename=archive.name, url=source.as_uri(), sha512=bootstrap.digest(source, 'sha512'))
            bootstrap.download(record, cache)
            self.assertEqual(archive.read_bytes(), source.read_bytes())
            self.assertFalse(archive.with_name(archive.name + '.partial').exists())

    def test_invalid_download_never_replaces_verified_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); cache = root / 'cache'; cache.mkdir()
            source = root / 'source'; source.write_bytes(b'unexpected bytes')
            record = dict(filename='tool.zip', url=source.as_uri(), sha256='0' * 64)
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                bootstrap.download(record, cache)
            self.assertFalse((cache / 'tool.zip').exists())
            self.assertFalse((cache / 'tool.zip.partial').exists())

    def test_archive_traversal_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, member in (('traversal', '../outside'), ('absolute', '/outside')):
                archive = root / (name + '.zip')
                with zipfile.ZipFile(archive, 'w') as output:
                    output.writestr(member, 'invented')
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    bootstrap.extract_zip(archive, root / name)
            archive = root / 'symlink.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                member = zipfile.ZipInfo('link'); member.create_system = 3
                member.external_attr = 0o120777 << 16
                output.writestr(member, '../outside')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                bootstrap.extract_zip(archive, root / 'symlink')

    def test_source_repository_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / '.git').mkdir()
            with self.assertRaisesRegex(ValueError, 'outside a source repository'):
                bootstrap.external(root / 'nested/builder')

    def test_selected_upstream_libraries_strip_long_archive_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); archive = root / 'upstream.zip'; destination = root / 'source'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('upstream-long-commit/SF3Lib/source.cs', 'allowed')
                output.writestr('upstream-long-commit/CommonLib/source.cs', 'allowed')
                output.writestr('upstream-long-commit/UnrelatedEditor/source.cs', 'excluded')
            bootstrap.extract_zip(archive, destination, 'upstream-long-commit/', ('SF3Lib/', 'CommonLib/'))
            self.assertEqual((destination / 'SF3Lib/source.cs').read_text(), 'allowed')
            self.assertEqual((destination / 'CommonLib/source.cs').read_text(), 'allowed')
            self.assertFalse((destination / 'UnrelatedEditor').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows preparation path alias')
    def test_temporary_drive_alias_removed_after_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, 'invented failure'):
                with bootstrap.short_build_root(root) as alias:
                    self.assertLess(len(str(alias)), 5)
                    (alias / 'invented.txt').write_text('same user-local folder')
                    raise RuntimeError('invented failure')
            self.assertEqual((root / 'invented.txt').read_text(), 'same user-local folder')
            self.assertFalse(alias.exists())


if __name__ == '__main__':
    unittest.main()
