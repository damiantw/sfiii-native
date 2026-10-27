"""Revision identity independent of BIN splitting, filenames and CHD compression."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def registered_profiles(profiles=ROOT/'profiles'):
    """Only explicitly shipped revision profiles authorize native preparation."""
    records = []
    seen = set()
    for path in sorted(Path(profiles).glob('*.json')):
        profile = json.loads(path.read_text(encoding='utf-8-sig'))
        identifier = profile.get('id')
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError('Invalid or duplicate revision profile ID')
        if type(profile.get('scenario')) is not int or profile['scenario'] not in (1,2,3,4):
            raise ValueError('Invalid revision scenario')
        seen.add(identifier)
        records.append((path,profile))
    return records

def profile_scenario(identifier, profiles=ROOT/'profiles'):
    return next((p['scenario'] for _,p in registered_profiles(profiles) if p['id']==identifier), None)

def content_id(manifest):
    return hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def identify(disc, manifest, profiles=ROOT/'profiles'):
    identity = content_id(manifest)
    for path, profile in registered_profiles(profiles):
        if profile.get('content_sha256') == identity:
            return path, profile
    raise ValueError('Unsupported disc contents (unregistered revision): '+disc.ip.product+' '+disc.ip.version+
                     ' (content ID '+identity+'). File names and patch labels are not sufficient to choose native load addresses. '
                     'This revision needs its own reviewed profile; existing saves and builds were not replaced.')

def verify_inventory(work, profile):
    manifest = json.loads((Path(work)/'manifest.json').read_text())
    if profile.get('content_sha256'):
        if content_id(manifest) != profile['content_sha256']:
            raise ValueError('Inventory contents do not match the selected revision profile')
    else:
        hashes = json.loads((Path(work)/'hashes.json').read_text())
        if not any(v['sha256'] == profile['track1_sha256'] for v in hashes.values()):
            raise ValueError('Inventory revision does not match profile')
    return manifest
