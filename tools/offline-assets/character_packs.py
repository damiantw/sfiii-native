"""Build immutable world + CHR/CHP sprite + supported X8PC model texture packs.

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
SCHEMA = 'SF3-CHARACTER-PACK-2'


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


def battle_model_refs(asset):
    import battle_textures
    return [ref for ref in asset.get('refs', [])
            if ref.get('category') == 'battle_models'
            and battle_textures.supports(PurePosixPath(ref.get('file', '')).name)]


def material_kind(descriptor):
    fields = descriptor.read_text(encoding='ascii').split()
    if len(fields) not in (5, 9, 10) or fields[0] != 'SF3HDASSET1':
        raise ValueError('Invalid source material descriptor')
    kind = fields[9] if len(fields) == 10 else 'world'
    if kind not in ('character', 'world'):
        raise ValueError('Invalid source material command kind')
    return kind


def set_material_kind(descriptor, kind):
    fields = descriptor.read_text(encoding='ascii').split()
    material_kind(descriptor)
    uv = fields[5:9] if len(fields) >= 9 else ['0', '0', '1', '1']
    text = f'{fields[0]}\n{fields[1]} {fields[2]}\n{fields[3]} {fields[4]}\n' + ' '.join(uv) + '\n' + kind + '\n'
    # The source descriptor may be hardlinked. Replace only our new pack's name.
    descriptor.unlink()
    descriptor.write_text(text, encoding='ascii')


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
    battle_count = battle_bytes = battle_shared = added_bytes = added_count = shared_character_battle = 0
    included = set()
    missing, characters, battle_models, seen_auxiliary = [], set(), set(), set()
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
            sprite_refs = character_refs(asset)
            model_refs = battle_model_refs(asset)
            refs = sprite_refs + model_refs
            if not refs:
                continue
            material = identity(asset['id'])
            if material in seen_auxiliary:
                raise ValueError('Duplicate character/model identity in disc catalog')
            seen_auxiliary.add(material)
            is_character, is_battle = bool(sprite_refs), bool(model_refs)
            if is_character:characters.add(material)
            if is_battle:battle_models.add(material)
            if material in included:
                try:
                    w, h = int(asset['width']), int(asset['height'])
                    original = (staging / material / 'original.rgba').read_bytes()
                    replacement = (staging / material / 'replacement.rgba').read_bytes()
                    ready = read_json(enhanced / material / 'ready.json')
                    if sha(original) != asset['original_sha256'] or sha(original) != ready.get('original_sha256'):
                        raise ValueError('Shared world/character/model original checksum mismatch')
                    if sha(replacement) != ready.get('rgba_sha256') or not exact_alpha(original, replacement, w, h):
                        raise ValueError('Shared world/character/model checksum or exact transparency changed')
                    # Preserve already validated character provenance on identical
                    # originals. Only battle-only materials are limited to command 2.
                    descriptor = staging / material / 'asset.txt'
                    is_character = is_character or material_kind(descriptor) == 'character'
                except (OSError, ValueError, KeyError, TypeError) as error:
                    missing.append(dict(asset=material, refs=refs, error=str(error)))
                    continue
                set_material_kind(descriptor, 'character' if is_character else 'world')
                if is_character:characters.add(material)
                shared += int(is_character)
                battle_shared += int(is_battle)
                shared_character_battle += int(is_character and is_battle)
                continue
            candidates.append((asset, refs, material, is_character, is_battle))

        def emit_character(candidate):
            asset, refs, material, is_character, is_battle = candidate
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
                return None, 0, 0, is_character, is_battle, dict(asset=material, refs=refs, error=str(error))
            target = staging / material
            target.mkdir()
            local_copied = 0
            for source, name in ((original_path, 'original.rgba'), (replacement_path, 'replacement.rgba')):
                try:
                    os.link(source, target / name)
                except OSError:
                    shutil.copy2(source, target / name)
                    local_copied += source.stat().st_size
            kind = 'character' if is_character else 'world'
            (target / 'asset.txt').write_text(f'SF3HDASSET1\n{w} {h}\n{w*4} {h*4}\n0 0 1 1\n{kind}\n', encoding='ascii')
            atomic_json(target / 'metadata.json', dict(asset, refs=refs, model=row['model'],
                model_signature=signature, category='sprites' if is_character else 'battle_models',
                character_frame=is_character, battle_model_texture=is_battle,
                eligible_commands=[0,1,2] if is_character else [2],
                replacement_sha256=replacement_sha, alpha_policy='exact nearest 4x original alpha'))
            return material, len(replacement), local_copied, is_character, is_battle, None

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for material, payload_bytes, copied_bytes, is_character, is_battle, failure in pool.map(emit_character, candidates):
                if failure:
                    missing.append(failure)
                    continue
                included.add(material)
                character_bytes += payload_bytes if is_character else 0
                battle_bytes += payload_bytes if is_battle else 0
                added_bytes += payload_bytes
                copied += copied_bytes
                count += int(is_character)
                battle_count += int(is_battle)
                shared_character_battle += int(is_character and is_battle)
                added_count += 1
                if added_count % 1000 == 0:
                    print(f"Scenario {row['scenario']} {row['model']}: verified {added_count}/{len(candidates)} character/model textures", flush=True)
        record = dict(schema=SCHEMA, scenario=row['scenario'], revision=row['revision'], profile=row['profile'],
            model=row['model'], model_signature=signature, material_count=len(included),
            world_material_count=row['material_count'], character_material_count=count,
            character_frames_already_world=shared, character_candidates=len(characters),
            battle_model_material_count=battle_count, battle_models_already_world=battle_shared,
            battle_model_candidates=len(battle_models), shared_character_battle_materials=shared_character_battle,
            character_total_material_count=count+shared, battle_model_total_material_count=battle_count+battle_shared,
            replacement_bytes=world_bytes+added_bytes, character_replacement_bytes=character_bytes,
            battle_model_replacement_bytes=battle_bytes, added_unique_material_count=added_count,
            copied_payload_bytes=copied, missing_world=row.get('missing', []), missing=missing,
            missing_characters=[m for m in missing if character_refs(dict(refs=m['refs']))],
            missing_battle_models=[m for m in missing if battle_model_refs(dict(refs=m['refs']))],
            source_world=str(world), source_cache=str(cache), path=str(destination),
            scope='Original world pack plus cached CHR/CHP sprites and supported X8PC RGB555 battle-model textures. '
                  'Exact alpha preserved. Battle-only materials require distorted command 2; existing verified CHR provenance stays eligible. '
                  'Material counts are unique RGBA originals, including distinct alpha variants, and do not count texture definitions. '
                  'Menus, indexed spell effects, untextured polygons and background planes are separate gaps and remain original. '
                  'A catalog entry is not proof of gameplay matching, full character coverage or all spell effects.')
        atomic_json(staging / 'manifest.json', record)
        build_index(staging)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(destination)
        print(f"Scenario {row['scenario']} {row['model']}: {count} character frames, {battle_count} battle-model textures added; "
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
