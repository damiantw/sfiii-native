"""Synthetic SH-2 discovery checks; requires the configured source dependency."""
from pathlib import Path
import sys
import unittest

framework=Path(__file__).resolve().parents[2]/'.local/saturn-recomp/src'
sys.path.insert(0,str(framework))
try:
    from saturnrecomp.sh2 import Image
    from saturnrecomp.recomp.discover import Program
except ImportError:
    Image=Program=None

@unittest.skipUnless(Program,'framework source unavailable; run dependency setup')
class DelaySlots(unittest.TestCase):
    def test_control_transfer_in_a_delay_slot_is_not_speculative_code(self):
        # Includes non-delayed conditional branches, which also cause slot-illegal exceptions.
        for slot in [0x8900,0x8B00,0x8D00,0x8F00,0xA000,0xB000,0x402B,0x400B,0x000B,0x002B,0x0023,0x0003,0xC300]:
            data=b''.join(w.to_bytes(2,'big') for w in [0x0603,slot,0x000B,0x0009])
            program=Program(Image(data,0x6000000),[0x6000000])
            self.assertEqual(program.funcs[0x6000000].bad,('bad slot',0x6000002),hex(slot))

    def test_normal_store_and_nop_slots_remain_valid(self):
        for slot in [0x0009,0x2041]:
            data=b''.join(w.to_bytes(2,'big') for w in [0x000B,slot])
            program=Program(Image(data,0x6000000),[0x6000000])
            self.assertIsNone(program.funcs[0x6000000].bad)

if __name__=='__main__':unittest.main()
