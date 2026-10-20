"""Read-only CHD ingestion into a verified, content-addressed external cache."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def resolve_disc(source, work, chdman, log, status):
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() == '.cue':return source
    if source.suffix.lower() != '.chd':raise ValueError('Select a Saturn CUE or CHD image.')
    chdman = Path(chdman)
    if not chdman.is_file():raise ValueError('The bundled CHD extraction tool is missing. Extract the complete application package.')
    status('disc','Checking and extracting your CHD. The original file is kept unchanged...')
    identity = sha(source)
    cache = Path(work)/'disc-cache'/identity
    receipt = cache/'receipt.json'
    if receipt.exists():
        record = json.loads(receipt.read_text())
        if record.get('source_sha256') == identity and record.get('files') and all(
            Path(n).name == n and (cache/n).is_file() and sha(cache/n) == h for n,h in record['files'].items()
        ) and (cache/'disc.cue').is_file():return cache/'disc.cue'
        raise ValueError('The cached CHD extraction changed. Choose a new game-data folder or restore its disc-cache files.')
    cache.parent.mkdir(parents=True,exist_ok=True)
    temporary = cache.parent/(identity+'.partial-'+uuid.uuid4().hex)
    temporary.mkdir()
    flags = 0x08000000 if os.name == 'nt' else 0
    # subprocess arguments are passed directly, never through a shell.
    for command in [[chdman,'verify','-i',source],
                    [chdman,'extractcd','-i',source,'-o',temporary/'disc.cue','-ob',temporary/'disc.bin']]:
        log.write('\nCHD '+json.dumps(list(map(str,command)))+'\n');log.flush()
        result = subprocess.run(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
        if result.returncode:raise ValueError('CHD verification or extraction failed. See the local disc-input.log. Parent/delta CHDs are not supported.')
    if sha(source) != identity:raise ValueError('The CHD changed during extraction; preparation was stopped.')
    files = {p.name:sha(p) for p in temporary.iterdir() if p.is_file()}
    if 'disc.cue' not in files or 'disc.bin' not in files:raise ValueError('CHD extraction did not produce a complete CD image.')
    (temporary/'receipt.json').write_text(json.dumps(dict(source_sha256=identity,files=files),indent=2)+'\n')
    # An interrupted extraction is never considered ready or reused.
    temporary.rename(cache)
    return cache/'disc.cue'
