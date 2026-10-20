"""Revision identity independent of BIN splitting, filenames and CHD compression."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def content_id(manifest):
    return hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def identify(disc, manifest, profiles=ROOT/'profiles'):
    identity = content_id(manifest)
    for path in sorted(Path(profiles).glob('*.json')):
        profile = json.loads(path.read_text(encoding='utf-8-sig'))
        if profile.get('content_sha256') == identity:
            return path, profile
    raise ValueError('Unsupported disc contents: '+disc.ip.product+' '+disc.ip.version+
                     '. This build supports Scenario 1 USA V1.001 and the registered Scenario 2 translation v24 dump.')

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
