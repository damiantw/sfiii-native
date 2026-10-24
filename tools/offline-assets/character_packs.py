"""Build immutable world + CHR/CHP sprite packs from an existing offline artwork cache.

No extraction, upscaling, network access, runtime changes or game activation occurs.
Every accepted sprite retains the source dimensions and exact nearest-scaled alpha.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import time
import uuid
from index_packs import build_index


MODELS = {'video': 'realesr-animevideov3', 'anime': 'realesrgan-x4plus-anime',
          'general': 'realesrgan-x4plus'}
SCHEMA = 'SF3-CHARACTER-PACK-1'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(data):
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


def external(path):
    path = Path(path).resolve()
    if any((folder / '.git').exists() for folder in (path, *path.parents)):
        raise ValueError('Pack output must be outside a source repository')
    return path


def character_refs(asset):
    return [ref for ref in asset.get('refs', [])
            if ref.get('category') == 'sprites'
            and PurePosixPath(ref.get('file', '')).suffix.upper() in ('.CHR', '.CHP')]


def identity(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Invalid content-addressed material identity')
    return value


def exact_alpha(original, replacement, w, h, scale=4):
    """Validate the complete alpha plane, including transparent animation boundaries."""
    if len(original) != w * h * 4 or len(replacement) != w * h * scale * scale * 4:
        return False
    alpha = original[3::4]
    enlarged = bytearray()
    for y in range(h):
        row = b''.join(bytes((a,)) * scale for a in alpha[y*w:(y+1)*w])
        enlarged.extend(row * scale)
    return replacement[3::4] == enlarged


def material_files(source, destination):
    """Link immutable payloads; preserve an independent pack on filesystems without links."""
    destination.mkdir()
    copied = 0
    for name in ('asset.txt', 'original.rgba', 'replacement.rgba', 'metadata.json'):
        path = source / name
        if not path.is_file():
            raise ValueError('Incomplete world material: ' + str(source))
        try:
            os.link(path, destination / name)
        except OSError:
            shutil.copy2(path, destination / name)
            copied += path.stat().st_size
    return copied


def select_disc(cache, row):
    matches = []
    for path in (cache / 'discs').iterdir():
        if not (path / 'identity.json').is_file():
            continue
        record = read_json(path / 'identity.json')
        if record.get('content_sha256') == row['revision'] and record.get('scenario') == row['scenario']:
            matches.append(path)
    if len(matches) != 1:
        raise ValueError('Expected exactly one matching disc inventory')
    return matches[0]


def select_model_cache(cache, row, world):
    matches = []
    for path in (cache / 'enhanced').iterdir():
        if not (path / 'model.json').is_file():
            continue
        record = read_json(path / 'model.json')
        signature = record.get('signature', '')
        # Native world packs use the first sixteen model-signature digits.
        if record.get('model') == MODELS[row['model']] and world.name == signature[:16]:
            identity(signature)
            matches.append((path, signature))
    if len(matches) != 1:
        raise ValueError('Expected exactly one model cache matching the existing world pack')
    return matches[0]


def package(cache, output, row, workers=4):
    if not 1 <= workers <= 16:
        raise ValueError('Choose between one and sixteen packaging workers')
    cache, output = Path(cache).resolve(), external(output)
    world = Path(row['path']).resolve()
    manifest = read_json(world / 'manifest.json')
    for key in ('scenario', 'revision', 'profile', 'model', 'material_count', 'replacement_bytes'):
        if manifest.get(key) != row.get(key):
            raise ValueError('World manifest/report mismatch: ' + key)
    disc = select_disc(cache, row)
    assets = read_json(disc / 'catalog.json')
    enhanced, signature = select_model_cache(cache, row, world)
    destination = external(output / ('scenario-' + str(row['scenario'])) / row['model'])
    if destination.exists():
        raise ValueError('Pack already exists; preserve it and choose a new output directory: ' + str(destination))
    output.mkdir(parents=True, exist_ok=True)
    staging = output / ('_pending-' + uuid.uuid4().hex[:8])
    staging.mkdir()
    count = world_bytes = character_bytes = copied = shared = 0
    included = set()
    missing, characters = [], set()
    try:
        for source in world.iterdir():
            if not source.is_dir() or not (source / 'asset.txt').is_file():
                continue
            material = identity(source.name)
            copied += material_files(source, staging / material)
            included.add(material)
            world_bytes += (source / 'replacement.rgba').stat().st_size
        if len(included) != row['material_count'] or world_bytes != row['replacement_bytes']:
            raise ValueError('World material count or payload size changed after its report was written')
        candidates = []
        for asset in assets:
            refs = character_refs(asset)
            if not refs:
                continue
            material = identity(asset['id'])
            if material in characters:
                raise ValueError('Duplicate character identity in disc catalog')
            characters.add(material)
            if material in included:
                try:
                    w, h = int(asset['width']), int(asset['height'])
                    original = (staging / material / 'original.rgba').read_bytes()
                    replacement = (staging / material / 'replacement.rgba').read_bytes()
                    ready = read_json(enhanced / material / 'ready.json')
                    if sha(original) != asset['original_sha256'] or sha(original) != ready.get('original_sha256'):
                        raise ValueError('Shared world/character original checksum mismatch')
                    if sha(replacement) != ready.get('rgba_sha256') or not exact_alpha(original, replacement, w, h):
                        raise ValueError('Shared world/character checksum or exact transparency changed')
                except (OSError, ValueError, KeyError, TypeError) as error:
                    missing.append(dict(asset=material, refs=refs, error=str(error)))
                    continue
                # The original world descriptor is hardlinked: replace only this new pack's
                # name before marking a legitimate shared character frame.
                descriptor = staging / material / 'asset.txt'
                descriptor_text = descriptor.read_text(encoding='ascii').rstrip() + '\ncharacter\n'
                descriptor.unlink()
                descriptor.write_text(descriptor_text, encoding='ascii')
                shared += 1
                continue
            candidates.append((asset, refs, material))

        def emit_character(candidate):
            asset, refs, material = candidate
            try:
                w, h = int(asset['width']), int(asset['height'])
                if not (1 <= w <= 1024 and 1 <= h <= 1024):
                    raise ValueError('Unsupported native texture dimensions')
                original_path = cache / 'assets' / material / 'original.rgba'
                replacement_path = enhanced / material / 'replacement.rgba'
                ready = read_json(enhanced / material / 'ready.json')
                original, replacement = original_path.read_bytes(), replacement_path.read_bytes()
                original_sha = sha(original)
                if original_sha != asset['original_sha256'] or original_sha != ready.get('original_sha256'):
                    raise ValueError('Original checksum mismatch')
                if sha(f'{w}x{h}:'.encode() + original) != material:
                    raise ValueError('Original content identity mismatch')
                replacement_sha = sha(replacement)
                if replacement_sha != ready.get('rgba_sha256'):
                    raise ValueError('Replacement checksum mismatch')
                if not exact_alpha(original, replacement, w, h):
                    raise ValueError('Dimensions or exact nearest-scaled transparency changed')
            except (OSError, ValueError, KeyError, TypeError) as error:
                # Cache gaps remain explicit, and the runtime falls back to original artwork.
                return None, 0, 0, dict(asset=material, refs=refs, error=str(error))
            target = staging / material
            target.mkdir()
            local_copied = 0
            for source, name in ((original_path, 'original.rgba'), (replacement_path, 'replacement.rgba')):
                try:
                    os.link(source, target / name)
                except OSError:
                    shutil.copy2(source, target / name)
                    local_copied += source.stat().st_size
            (target / 'asset.txt').write_text(f'SF3HDASSET1\n{w} {h}\n{w*4} {h*4}\n0 0 1 1\ncharacter\n', encoding='ascii')
            atomic_json(target / 'metadata.json', dict(asset, refs=refs, model=row['model'],
                model_signature=signature, category='sprites', character_frame=True,
                replacement_sha256=replacement_sha, alpha_policy='exact nearest 4x original alpha'))
            return material, len(replacement), local_copied, None

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for material, payload_bytes, copied_bytes, failure in pool.map(emit_character, candidates):
                if failure:
                    missing.append(failure)
                    continue
                included.add(material)
                character_bytes += payload_bytes
                copied += copied_bytes
                count += 1
                if count % 1000 == 0:
                    print(f"Scenario {row['scenario']} {row['model']}: verified {count}/{len(candidates)} character frames", flush=True)
        record = dict(schema=SCHEMA, scenario=row['scenario'], revision=row['revision'], profile=row['profile'],
            model=row['model'], model_signature=signature, material_count=len(included),
            world_material_count=row['material_count'], character_material_count=count,
            character_frames_already_world=shared, character_candidates=len(characters),
            replacement_bytes=world_bytes+character_bytes, character_replacement_bytes=character_bytes,
            copied_payload_bytes=copied, missing_world=row.get('missing', []), missing=missing,
            source_world=str(world), source_cache=str(cache), path=str(destination),
            scope='Original world pack plus cached CHR/CHP sprite frames. Exact alpha preserved. '
                  'Menus and embedded UI excluded. A catalog entry is not proof of gameplay matching or full character coverage.')
        atomic_json(staging / 'manifest.json', record)
        build_index(staging)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(destination)
        print(f"Scenario {row['scenario']} {row['model']}: {count} character frames added; "
              f"{len(missing)} unavailable; {record['replacement_bytes']/1048576:.1f} MiB replacement payload", flush=True)
        return record
    except BaseException:
        # Preserve staging for inspection; it is never referenced by a completed report.
        raise


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--cache', type=Path, required=True, help='Completed graphics builder output')
    parser.add_argument('--output', type=Path, required=True, help='New external combined-pack directory')
    parser.add_argument('--scenario', type=int, choices=(1, 2, 3), action='append', help='Repeat to select scenarios; default all')
    parser.add_argument('--model', choices=tuple(MODELS), action='append', help='Repeat to select styles; default all')
    parser.add_argument('--workers', type=int, default=4, help='Parallel cache checks and file packaging, 1-16; no GPU work')
    args = parser.parse_args()
    rows = [row for row in read_json(args.cache / 'packs-report.json')
            if row['scenario'] in (args.scenario or (1, 2, 3)) and row['model'] in (args.model or MODELS)]
    keys = [(r['scenario'], r['model']) for r in rows]
    if len(keys) != len(set(keys)) or not rows:
        raise ValueError('Pack report is empty or has ambiguous scenario/style entries')
    expected = {(scenario, model) for scenario in (args.scenario or (1, 2, 3))
                for model in (args.model or MODELS)}
    if set(keys) != expected:
        raise ValueError('Requested scenario/style world packs are unavailable: ' + str(sorted(expected - set(keys))))
    report_path = external(args.output) / 'packs-report.json'
    reports = read_json(report_path) if report_path.exists() else []
    if not isinstance(reports, list):
        raise ValueError('Existing combined-pack report is invalid')
    if set(keys).intersection((r['scenario'], r['model']) for r in reports):
        raise ValueError('Selected scenario/styles are already reported; choose a new output directory')
    for row in rows:
        reports.append(package(args.cache, args.output, row, args.workers))
        atomic_json(report_path, reports)


if __name__ == '__main__':
    main()
