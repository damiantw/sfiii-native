"""SF3 differential test against a libretro reference core (bring-your-own core, disc and saves;
outputs stay outside the repository).

  python tools/sf3-diff.py --saturn BUILD/saturn --cue DISC.cue --profile scenario1-usa-v25_1 \
      --core yabause_libretro.so --save SAVES.bin --record 01 --out /private/diff/sc1 --vblanks 9000

Loads the record through the title's Continue menu on both, drives the same seeded inputs placed
by the game's frame tick, and compares the live state block, map/battle ids and the picture every
--every VBlanks. Results: OUT/diff.json and OUT/side-<vblank>.png (ours | reference | differing dots).
The reference core must expose high work RAM as RETRO_MEMORY_SYSTEM_RAM (see docs/testing-plan.md)."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / '.local' / 'saturn-recomp' / 'src'))
from sf3test import diff, memory_map, sweep  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--saturn', required=True)
    ap.add_argument('--cue', required=True)
    ap.add_argument('--profile', required=True)
    ap.add_argument('--core', required=True, help='reference libretro core (.so)')
    ap.add_argument('--save', required=True, help='backup image, .BUP or native backup holding the record')
    ap.add_argument('--record', default='01', help='record number (last two characters of its name)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--vblanks', type=int, default=9000)
    ap.add_argument('--every', type=int, default=250)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--tick', type=lambda s: int(s, 16), help='frame tick address (default: the profile\'s)')
    a = ap.parse_args()
    mm = memory_map.lookup(a.profile)
    recs = [t for t in sweep.targets_from_saves([a.save], mm['scenario']) if t['id'].endswith(':' + a.record)]
    if not recs:
        sys.exit(f'no SFORCE3{mm["scenario"]}_{a.record} record in {a.save}')
    out = diff.run(a.saturn, a.cue, a.profile, a.core, recs[0]['record'], a.out, a.vblanks, a.seed,
                   a.every, a.tick)
    print(json.dumps(dict(out['summary'], loaded_at=out['loaded_at'], core_frames=out['core_frames'])))


if __name__ == '__main__':
    main()
