"""Synthetic X8 battle-texture cases; no game data or GPU is needed."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

path = Path(__file__).resolve().parents[1] / 'offline-assets' / 'battle_textures.py'
spec = importlib.util.spec_from_file_location('battle_textures', path)
battle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(battle)


def words(*values):
    return struct.pack('>' + 'H' * len(values), *values)


def literals(raw):
    values = [(False, v[0]) for v in struct.iter_unpack('>H', raw)] + [(True, 0)]
    result = bytearray()
    for at in range(0, len(values), 16):
        group = values[at:at+16]
        flags = sum(int(command) << (15-i) for i, (command, _) in enumerate(group))
        result += words(flags, *(value for _, value in group))
    return bytes(result)


def model(raw=None, definitions=None):
    raw = raw if raw is not None else words(0, 0x7FFF, 0x8001, 0x8020, 0x8400, 0xFFFF, 0x001F, 0x03E0)
    definitions = definitions or [(8, 1, 0, 0x101)]
    block = struct.pack('>5I', 20, len(definitions), len(raw), 0, 0)
    block += b''.join(struct.pack('>4H', *entry) for entry in definitions)
    packed = literals(raw)
    data = bytearray(0x200 + len(packed))
    struct.pack_into('>4I', data, 0, 0x100, len(block), len(block), 0)
    struct.pack_into('>4I', data, 16, 0x200, len(packed), len(packed), 0)
    struct.pack_into('>4I', data, 32, 0xFFFFFFFF, 0, 0, 0)
    data[0x100:0x100+len(block)] = block
    data[0x200:] = packed
    return data


class BattleTextureTests(unittest.TestCase):
    def test_literal_decode_exact_color_and_hardware_alpha_variants(self):
        decoded = battle.decode(model())
        texture = decoded['textures'][0]
        self.assertEqual((texture['width'], texture['height']), (8, 1))
        self.assertEqual(decoded['compressed_trailing_bytes'], 0)
        rgba = battle.rgba(texture['raw16'])
        self.assertEqual(rgba[:8], bytes((0,0,0,0,248,248,248,0)))
        self.assertEqual(rgba[8:20], bytes((8,0,0,255,0,8,0,255,0,0,8,255)))
        self.assertEqual(battle.rgba(texture['raw16'], spd=True)[3], 255)
        self.assertEqual(battle.rgba(texture['raw16'], ecd=True)[7], 255)
        self.assertEqual(battle.rgba(texture['raw16'], spd=True, ecd=True)[3::4], b'\xff'*8)

    def test_overlapping_backreference_and_rejection_boundaries(self):
        expanded, consumed = battle.decompress(words(0x6000, 0xABCD, 0x20, 0), 6)
        self.assertEqual(expanded, words(0xABCD, 0xABCD, 0xABCD))
        self.assertEqual(consumed, 8)
        invalid = [(words(0x8000, 0x20), 4), (words(0x8000, 1), 4),
                   (words(0x6000, 0xABCD, 0x20, 0), 4),
                   (words(0x8000, 0), 2), (b'\x00', 2), (words(0, 0x8001), 2)]
        for data, expected in invalid:
            with self.subTest(data=data), self.assertRaises(battle.DecodeError):
                battle.decompress(data, expected)
        with self.assertRaises(battle.DecodeError):
            battle.decompress(words(0x8000, 0), battle.MAX_TEXTURE_BYTES+2)

    def test_section_truncation_overlap_and_missing_terminator(self):
        cases = []
        data = model(); cases.append(data[:-1])
        data = model(); struct.pack_into('>I', data, 16, 0x108); cases.append(data)
        data = model(); data[32:0x100] = b'\xff'*224; struct.pack_into('>I', data, 32, 0x100); cases.append(data)
        data = model(); struct.pack_into('>I', data, 4, 0xFFFFFFFF); cases.append(data)
        for data in cases:
            with self.subTest(header=data[:48]), self.assertRaises(battle.DecodeError):
                battle.decode(data)

    def test_definition_dimensions_size_and_range_are_checked(self):
        for definition in ((0,1,0,0x101), (7,1,0,0x101), (8,0,0,0x101),
                           (8,256,0,0x100), (512,1,0,0x4001), (8,1,0,0x8101),
                           (8,1,0,0x201), (8,1,3,0x101)):
            with self.subTest(definition=definition), self.assertRaises(battle.DecodeError):
                battle.decode(model(definitions=[definition]))
        with self.assertRaisesRegex(battle.DecodeError, 'Overlapping battle texture'):
            battle.decode(model(raw=b'\x80\x01'*16, definitions=[(8,1,0,0x101), (8,1,0,0x101)]))
        data = model(); struct.pack_into('>I', data, 0x104, battle.MAX_TEXTURES+1)
        with self.assertRaises(battle.DecodeError):
            battle.decode(data)
        data = model(); struct.pack_into('>I', data, 0x108, battle.MAX_TEXTURE_BYTES+2)
        with self.assertRaises(battle.DecodeError):
            battle.decode(data)

    def test_definition_offsets_preserve_padding_and_non_square_dimensions(self):
        raw = b'\x80\x01'*8 + b'\x00'*8 + b'\x84\x00'*24
        decoded = battle.decode(model(raw, [(8,1,0,0x101), (8,3,3,0x103)]))
        self.assertEqual(decoded['textures'][1]['raw16'], b'\x84\x00'*24)
        self.assertEqual(decoded['textures'][1]['byte_offset'], 24)

    def test_omitted_final_sector_padding_is_not_missing_payload(self):
        data = model()
        compressed_size = struct.unpack_from('>I', data, 20)[0]
        struct.pack_into('>I', data, 24, compressed_size+32)
        self.assertEqual(len(battle.decode(data)['textures']), 1)
        with self.assertRaises(battle.DecodeError):
            battle.decode(data[:-1])

    def test_unknown_definition_flags_are_explicit_unavailable_validation(self):
        data = model(); struct.pack_into('>I', data, 0x104, 0x00100001)
        with self.assertRaisesRegex(battle.DecodeError, 'Unsupported battle texture definition flags'):
            battle.decode(data)

    def test_extractor_receipt_and_cas_reuse_and_malformed_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root/'X8PC20A.BIN'; source.write_bytes(model())
            receipt = root/'receipt.json'; store = root/'assets'
            first = battle.extract(source, store, receipt, 2)
            self.assertEqual(first['status'], 'extracted')
            self.assertEqual(first['textures_decoded'], 1)
            self.assertEqual(len(first['images']), 4)
            self.assertEqual(len({x['id'] for x in first['images']}), 4)
            image = first['images'][0]
            self.assertEqual(image['category'], 'battle_models')
            raw = store/image['id']/'original.rgba'
            self.assertEqual(battle.digest(raw.read_bytes()), image['original_sha256'])
            self.assertEqual(battle.extract(source, store, receipt, 2)['images'], first['images'])
            source.write_bytes(model()[:-1])
            failed = battle.extract(source, store, receipt, 2)
            self.assertEqual(failed['status'], 'failed')
            self.assertFalse(failed['images'])
            self.assertTrue(failed['error'])
            self.assertEqual(json.loads(receipt.read_text())['status'], 'failed')

    def test_opaque_alpha_variants_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root/'X8PC20A.BIN'
            source.write_bytes(model(raw=b'\x80\x01'*8))
            result = battle.extract(source, root/'assets', root/'receipt.json', 2)
            self.assertEqual(len(result['images']), 1)
            self.assertEqual(result['images'][0]['alpha_variants'],
                [dict(spd=False,ecd=False),dict(spd=False,ecd=True),
                 dict(spd=True,ecd=False),dict(spd=True,ecd=True)])

    def test_explicit_family_detection_dummy_and_unsupported(self):
        self.assertTrue(battle.supports('x8pc01a.bin'))
        self.assertTrue(battle.supports('X8PC889.BIN'))
        for name in ('X014.BIN', 'X8OTHER.BIN', 'X8PC.BIN', 'X8PC01A.BIN.bak'):
            self.assertFalse(battle.supports(name))
        self.assertTrue(battle.decode(b'dummy')['dummy'])
        self.assertEqual(battle.decode(b'0\n')['dummy_kind'], 'ascii-zero-placeholder')
        self.assertTrue(battle.decode(b'dumm')['dummy'])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root/'X014.BIN'; source.write_bytes(b'not a model')
            self.assertEqual(battle.extract(source, root/'assets', root/'receipt.json', 2)['status'], 'unsupported')


if __name__ == '__main__':
    unittest.main()
