"""On-console generator skeleton (native/recomp/gen): discovery, code cache, RW->RX loader, thunk backend.
Invented code only. Skipped without clang++ on x86-64 Linux or the saturn-recomp checkout."""
import os, platform, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECOMP = Path(os.environ.get('SF3_RECOMP_SRC', ROOT / '.local' / 'saturn-recomp'))


# the units the skeleton test links (the gen tools' mains and the runtime-bound loaders are not)
SKELETON = ('backend_x64_thunk.cpp', 'code_cache.cpp', 'discover.cpp', 'loader_posix.cpp')


@unittest.skipUnless(shutil.which('clang++') and platform.machine() in ('x86_64', 'AMD64') and platform.system() == 'Linux'
                     and (RECOMP / 'runtime' / 'include').exists(), 'needs clang++, x86-64 Linux and saturn-recomp')
class GenSkeletonTest(unittest.TestCase):
    def test_skeleton(self):
        n = ROOT / 'native/recomp'
        with tempfile.TemporaryDirectory() as t:
            exe = Path(t) / 'gent'
            subprocess.run(['clang++', '-std=c++20', '-O2', '-I', str(RECOMP / 'runtime/include'), str(n / 'sh2_interp.cpp'),
                            *(str(n / 'gen' / f) for f in SKELETON), str(n / 'tests/gen_skeleton_test.cpp'), '-o', str(exe)], check=True)
            r = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == '__main__':
    unittest.main()
