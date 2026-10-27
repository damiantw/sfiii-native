"""Bounded read-only decoder for X8PC battle-model RGB555 texture sections.

Binary-layout reference: SF3Unity Assets/Scripts/SF3/BattleMesh.cs and
Decompression.cs, https://github.com/AndreasScholl/SF3Unity (MIT).
The upstream README credits https://github.com/marfsama/shiningforce3.
This implementation uses native Saturn channel quantization and configurable
SPD/ECD transparency instead of Unity's presentation color conversion.

Reference copyright and permission notice:
MIT License, Copyright (c) 2021 AndreasScholl
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import time
import uuid

DECODER_VERSION = 'x8pc-rgb555-2'
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_TEXTURE_BYTES = 64 * 1024 * 1024
MAX_TEXTURES = 4096
MAX_WIDTH = 504  # VDP1 CMDSIZE has six width bits, each representing eight texels.
MAX_HEIGHT = 255


class DecodeError(ValueError):
    pass


def supports(filename):
    return re.fullmatch(r'X8PC[0-9A-Z]+\.BIN', Path(filename).name.upper()) is not None


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.tmp-' + uuid.uuid4().hex[:8])
    try:
        temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
        for attempt in range(21):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 20:
                    raise
                time.sleep(min(.025 * (attempt + 1), .25))
    finally:
        temporary.unlink(missing_ok=True)


def decompress(data, expected_size, limit=MAX_TEXTURE_BYTES):
    """Decode the word-LZ stream without reading beyond its declared section."""
    if not 0 <= expected_size <= limit or expected_size % 2:
        raise DecodeError('Invalid or excessive decompressed texture size')
    output = bytearray()
    cursor = 0

    def word():
        nonlocal cursor
        if cursor + 2 > len(data):
            raise DecodeError('Truncated compressed word stream')
        value = (data[cursor] << 8) | data[cursor + 1]
        cursor += 2
        return value

    while True:
        flags = word()
        for bit in range(15, -1, -1):
            value = word()
            if flags & (1 << bit):
                if value == 0:
                    if len(output) != expected_size:
                        raise DecodeError('Decompressed texture length does not match its header')
                    return bytes(output), cursor
                distance = (value >> 5) * 2
                length = ((value & 31) + 2) * 2
                if distance == 0 or distance > len(output):
                    raise DecodeError('Invalid texture backreference distance')
                if len(output) + length > expected_size:
                    raise DecodeError('Compressed texture expansion exceeds declared size')
                # Deliberately allow overlapping backreferences.
                for _ in range(length):
                    output.append(output[-distance])
            else:
                if len(output) + 2 > expected_size:
                    raise DecodeError('Literal texture expansion exceeds declared size')
                output.extend((value >> 8, value & 255))


def rgba(raw16, spd=False, ecd=False):
    """Match native RGB16 texel colors; alpha depends on VDP1 SPD/ECD flags.

    End-of-row traversal after two end codes is geometry/mode dependent and is
    left to the native renderer. These are the unflipped source texel values.
    """
    if len(raw16) % 2:
        raise DecodeError('Odd RGB555 texture byte count')
    output = bytearray(len(raw16) * 2)
    for at in range(0, len(raw16), 2):
        value = (raw16[at] << 8) | raw16[at + 1]
        alpha = 0 if (value == 0 and not spd) or (value == 0x7FFF and not ecd) else 255
        output[at*2:at*2+4] = bytes(((value & 31) << 3, ((value >> 5) & 31) << 3,
                                    ((value >> 10) & 31) << 3, alpha))
    return bytes(output)


def decode(data):
    if len(data) > MAX_INPUT_BYTES:
        raise DecodeError('Battle model input exceeds the size limit')
    if data in (b'0\n', b'0\r\n'):
        return dict(dummy=True, dummy_kind='ascii-zero-placeholder', sections=[], textures=[])
    if data.startswith(b'dumm'):
        return dict(dummy=True, dummy_kind='dummy-marker', sections=[], textures=[])
    if len(data) < 0x30:
        raise DecodeError('Truncated battle model section table')
    first = struct.unpack_from('>I', data)[0]
    if first < 0x30 or first > min(len(data), 0x10000):
        raise DecodeError('Invalid battle model section table extent')
    sections = []
    terminated = False
    for at in range(0, first - 15, 16):
        start, length, padded, flags = struct.unpack_from('>4I', data, at)
        if start == 0xFFFFFFFF or (start, length, padded, flags) == (0, 0, 0, 0):
            terminated = True
            break
        if start < first or length < 1 or padded < length or start + length > len(data):
            raise DecodeError('Invalid or truncated battle model section range')
        if start + padded > len(data) and not (start + length == len(data) and padded - length < 0x800):
            raise DecodeError('Missing battle model payload or excessive final-sector padding')
        sections.append(dict(offset=start, size=length, padded_size=padded, flags=flags))
    if not terminated or len(sections) < 2:
        raise DecodeError('Missing battle model section terminator or texture sections')
    ranges = sorted((s['offset'], s['offset'] + s['padded_size']) for s in sections)
    if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
        raise DecodeError('Overlapping battle model sections')
    definition, pixels = sections[:2]
    block = data[definition['offset']:definition['offset'] + definition['size']]
    if len(block) < 0x14:
        raise DecodeError('Truncated battle texture definition header')
    header_size, count, expected_size = struct.unpack_from('>3I', block)
    if count >> 16:
        raise DecodeError(f'Unsupported battle texture definition flags: 0x{count >> 16:04X}')
    if header_size < 0x14 or header_size > len(block) or count > MAX_TEXTURES:
        raise DecodeError('Invalid battle texture definition header/count')
    if header_size + count * 8 > len(block):
        raise DecodeError('Truncated battle texture definitions')
    if expected_size > MAX_TEXTURE_BYTES:
        raise DecodeError('Battle texture output exceeds the size limit')
    definitions = []
    for index in range(count):
        width, height, address_units8, command_size = struct.unpack_from('>4H', block, header_size + index * 8)
        if not (1 <= width <= MAX_WIDTH and 1 <= height <= MAX_HEIGHT) or width % 8:
            raise DecodeError('Invalid battle texture dimensions')
        if command_size & 0xC000 or command_size != (((width // 8) << 8) | height):
            raise DecodeError('Battle texture VDP1 size disagrees with its dimensions')
        start, length = address_units8 * 8, width * height * 2
        if start + length > expected_size:
            raise DecodeError('Battle texture definition exceeds decompressed bytes')
        definitions.append(dict(index=index, width=width, height=height, byte_offset=start,
                                byte_size=length, command_size=command_size, address_units8=address_units8))
    spans = sorted((d['byte_offset'], d['byte_offset'] + d['byte_size']) for d in definitions)
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise DecodeError('Overlapping battle texture definitions')
    packed = data[pixels['offset']:pixels['offset'] + pixels['size']]
    unpacked, consumed = decompress(packed, expected_size)
    textures = []
    for entry in definitions:
        raw = unpacked[entry['byte_offset']:entry['byte_offset'] + entry['byte_size']]
        textures.append(dict(entry, raw16=raw))
    return dict(dummy=False, sections=sections, textures=textures,
                decompressed_bytes=len(unpacked), compressed_bytes_consumed=consumed,
                compressed_trailing_bytes=len(packed)-consumed)


def extract(source, store, receipt, scenario):
    source, store, receipt = Path(source).resolve(), Path(store).resolve(), Path(receipt).resolve()
    record = dict(schema='SF3-OFFLINE-EXTRACT-1', source=str(source), scenario=int(scenario),
                  decoder=DECODER_VERSION, status='unsupported', error=None, warnings=[], images=[], planes=[])
    try:
        if source.stat().st_size > MAX_INPUT_BYTES:
            raise DecodeError('Battle model input exceeds the size limit')
        data = source.read_bytes()
        record['source_sha256'] = digest(data)
        if supports(source.name):
            decoded = decode(data)
            record['sections'] = decoded['sections']
            record['dummy'] = decoded['dummy']
            record['textures_decoded'] = len(decoded['textures'])
            if 'dummy_kind' in decoded:
                record['dummy_kind'] = decoded['dummy_kind']
            for texture in decoded['textures']:
                width, height = texture['width'], texture['height']
                variants = {}
                for spd in (False, True):
                    for ecd in (False, True):
                        original = rgba(texture['raw16'], spd, ecd)
                        original_sha256 = digest(original)
                        variant = variants.setdefault(original_sha256, dict(original=original, flags=[]))
                        variant['flags'].append(dict(spd=spd, ecd=ecd))
                for original_sha256, variant in variants.items():
                    original = variant['original']
                    image_id = digest(f'{width}x{height}:'.encode('ascii') + original)
                    directory = store / image_id
                    directory.mkdir(parents=True, exist_ok=True)
                    raw_file = directory / 'original.rgba'
                    if raw_file.exists():
                        if digest(raw_file.read_bytes()) != original_sha256:
                            raise DecodeError('Cached battle image checksum mismatch')
                    else:
                        temporary = directory / ('.tmp-' + uuid.uuid4().hex[:8])
                        temporary.write_bytes(original)
                        os.replace(temporary, raw_file)
                    first_flags = variant['flags'][0]
                    image = dict(id=image_id, width=width, height=height, original_sha256=original_sha256,
                        opaque=all(a == 255 for a in original[3::4]), category='battle_models',
                        location=f"x8/texture-{texture['index']}/spd{int(first_flags['spd'])}-ecd{int(first_flags['ecd'])}",
                        pixel_format='RGB555', tileable=False, raw16_sha256=digest(texture['raw16']),
                        source_byte_offset=texture['byte_offset'], alpha_variants=variant['flags'],
                        alpha_policy='Unique exact VDP1 SPD/ECD alpha variants; RGB555 channels shifted by three')
                    atomic_json(directory / 'asset.json', dict(image, original=str(raw_file)))
                    record['images'].append(image)
            for key in ('decompressed_bytes', 'compressed_bytes_consumed', 'compressed_trailing_bytes'):
                if key in decoded:
                    record[key] = decoded[key]
            record['status'] = 'extracted' if record['images'] else 'no_images'
    except (OSError, ValueError, KeyError, struct.error) as error:
        record.update(status='failed', error=str(error), images=[])
    atomic_json(receipt, record)
    return record


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('scenario', type=int, choices=(1, 2, 3, 4))
    parser.add_argument('source', type=Path)
    parser.add_argument('store', type=Path)
    parser.add_argument('receipt', type=Path)
    args = parser.parse_args()
    result = extract(args.source, args.store, args.receipt, args.scenario)
    print(f"{args.source.name}: {result['status']}, {len(result['images'])} images")
    return 1 if result['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
