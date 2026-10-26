"""tools/sf3-block-coverage.py on invented block tables (no disc data)."""
import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / 'sf3-block-coverage.py'
HEAD = '# module crc block function insns master slave\n'


def write(d, name, rows):
    p = Path(d) / name
    p.mkdir(parents=True)
    (p / 'coverage.blocks.tsv').write_text(HEAD + ''.join(' '.join(map(str, r)) + '\n' for r in rows))


class BlockCoverageReport(unittest.TestCase):
    def test_union_groups_and_cold_functions(self):
        with tempfile.TemporaryDirectory() as d:
            a = [('BOOT', '11111111', '06004000', '06004000', 3, 1, 0), ('BOOT', '11111111', '06004006', '06004000', 2, 0, 0),
                 ('BOOT', '11111111', '06004100', '06004100', 9, 0, 0), ('X1BTL02', '22222222', '06060000', '06060000', 4, 0, 0)]
            b = [r[:5] + (0, 0) for r in a]
            b[1] = b[1][:5] + (0, 1)
            write(d, 'title-1', a)
            write(d, 'story-1', b)
            f = Path(d) / 'story-1' / 'coverage.blocks.tsv'      # compressed dumps are read the same way
            f.with_name(f.name + '.gz').write_bytes(gzip.compress(f.read_bytes()))
            f.unlink()
            out = Path(d) / 'r.json'
            subprocess.run([sys.executable, str(TOOL), 'scenario', '--name', 't', '--runs', f'title={d}/title-*',
                            f'story={d}/story-*', '--out', str(out)], check=True, capture_output=True)
            r = json.loads(out.read_text())
            t = r['total']
            self.assertEqual((t['blocks'], t['hit'], t['master'], t['slave']), (4, 2, 1, 1))
            self.assertEqual((t['functions'], t['functions_hit'], t['modules_hit']), (3, 1, 1))
            self.assertEqual(r['groups']['title']['only'], 1)
            self.assertEqual(r['groups']['story']['only'], 1)
            self.assertEqual([c['function'] for c in r['cold_in_ran_modules']], ['06004100'])
            self.assertEqual(r['cold_modules'][0]['module'], 'X1BTL02')
            self.assertTrue(r['cold_modules'][0]['label'].startswith('battle'))

    def test_refuses_report_inside_repository(self):
        p = subprocess.run([sys.executable, str(TOOL), 'scenario', '--name', 't', '--runs', 'x=/nonexistent*',
                            '--out', str(TOOL.parent / 'r.json')], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('outside the repository', p.stderr)


if __name__ == '__main__':
    unittest.main()
