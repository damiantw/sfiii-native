"""SH-2 interpreter fallback (native/recomp/sh2_interp.cpp): build the stdin harness and run a short
differential fuzz against saturn-recomp's sh2emu.py (invented programs, no game code).
Skipped without clang++ or the saturn-recomp checkout (.local/saturn-recomp or SF3_RECOMP_SRC)."""
import os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECOMP = Path(os.environ.get('SF3_RECOMP_SRC', ROOT / '.local' / 'saturn-recomp'))


@unittest.skipUnless(shutil.which('clang++') and (RECOMP / 'runtime' / 'include').exists(), 'needs clang++ and saturn-recomp')
class SH2InterpTest(unittest.TestCase):
    def test_differential_fuzz(self):
        with tempfile.TemporaryDirectory() as t:
            exe = Path(t) / 'sh2h'
            subprocess.run(['clang++', '-std=c++17', '-O2', '-I', str(RECOMP / 'runtime' / 'include'),
                            str(ROOT / 'native/recomp/sh2_interp.cpp'), str(ROOT / 'native/recomp/tests/sh2_interp_harness.cpp'),
                            '-o', str(exe)], check=True)
            r = subprocess.run([sys.executable, str(ROOT / 'tools/ps5/sh2interp-diff.py'), '--harness', str(exe), '--count', '100'],
                               capture_output=True, text=True, check=True)
            self.assertIn('0 skipped, 0 failures', r.stdout.splitlines()[-1])


if __name__ == '__main__':
    unittest.main()
