"""One backup memory shared by every scenario, like a single Saturn's internal memory and cartridge.

Shining Force III's own new-game import reads the previous scenario's COMPLETE record from the
backup memory. With one file per scenario the record is never there; with this shared file it is,
so no copying and no change to the game's behaviour is needed.

Files (in the shared folder, by default <data folder>/SFIII Native/Shared Backup Memory):
  backup.bin               internal memory (device 0, 32 KiB in 64-byte blocks)
  backup.bin.cartridge     4-Mbit backup cartridge (device 1, 512 KiB in 512-byte blocks)
  shared-saves.json        which per-scenario files were merged, and what happened to every save
  backup.lock              held while a game, import or merge uses these files
  migration-backups/<UTC stamp>/...  copies of the original per-scenario files and of the shared
                           files before each merge (originals in the game-data folders are untouched)

Both containers use the runtime's native record layout: name[12] comment[11] language[1]
date<u32 LE> size<u32 LE>, then the data, sorted by name. Space is counted the way the runtime's
BUP Stat/Write count it (the Saturn directory format: 34 bytes of header and block list per save,
plus one block), so a merge never produces a file the game would see as over-full.

Data-free: this module never contains game data; callers pass the player's own files."""
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile

FORMAT = 'SF3SHAREDSAVES1'
SAVE_NAME = 'backup.bin'
WORK_SAVE = 'experimental-backup.bin'
DEVICES = (('internal', '', 32768, 64), ('cartridge', '.cartridge', 524288, 512))
# Full-size save records the scenarios write (bytes); used for the capacity check only.
SAVE_SIZES = {1: 12904, 2: 16248, 3: 24344, 4: 24344}
# Record names each game writes. The Premium Disc (4) writes its record as a Scenario 3 record (SFORCE33_NN).
OWN_PREFIX = {1: 'SFORCE31_', 2: 'SFORCE32_', 3: 'SFORCE33_', 4: 'SFORCE33_'}
NAME = re.compile(r'^(SFORCE3[123])_([0-9]{2})$')


def default_dir():
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local')
    elif sys.platform == 'darwin':
        base = Path.home()/'Library/Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')
    return base/'SFIII Native'/'Shared Backup Memory'


def default_folders():
    """The launchers' default game-data folders (they keep their historical names)."""
    root = default_dir().parent
    names = ('Game', 'Game-Scenario2-v24', 'Game-Scenario3-v25_1', 'Game-Premium-Disc-v25_1') if os.name == 'nt' else (
        'Scenario1-USA', 'Scenario2-v24', 'Scenario3-v25_1', 'Premium-Disc-v25_1')
    return [root/name for name in names]


def default_settings():
    root = default_dir().parent
    return [root/'launcher.json']


def scenario_of(profile_id):
    """Scenario number (1-3) of a registered profile id such as scenario2-translation-v25_1-v2_000,
    or 4 for the Premium Disc (premium-disc-...)."""
    if str(profile_id or '').startswith('premium-disc-'):
        return 4
    match = re.match(r'^scenario([123])-', str(profile_id or ''))
    if not match:
        raise ValueError('Unknown disc profile: '+str(profile_id))
    return int(match.group(1))


def work_scenario(work):
    """Scenario of a prepared game-data folder, or None when it was never prepared."""
    for name in ['game.json', 'desktop-ready.json']:
        try:
            profile = json.loads((Path(work)/name).read_text(encoding='utf-8-sig')).get('profile_id')
            if profile:
                return scenario_of(profile)
        except (OSError, ValueError, AttributeError):
            continue
    return None


def blocks(size, block):
    return (size + 34 + block - 1)//block + 1


def usable(device):
    _, _, size, block = device
    return size//block - 2


def parse(data):
    """(records, problem): records maps name -> dict(comment, language, date, data). A damaged tail
    is reported in `problem`; the whole records before it are still returned."""
    records, at = {}, 0
    while at < len(data):
        if len(data) - at < 32:
            return records, f'truncated record header after {len(records)} saves'
        head = data[at:at + 32]
        name = head[:12].split(b'\0')[0].decode('ascii', 'replace')
        size = struct.unpack_from('<I', head, 28)[0]
        if not name or size > 524288 or at + 32 + size > len(data):
            return records, f'damaged record after {len(records)} saves'
        if name in records:
            return records, f'duplicate record {name} after {len(records)} saves'
        records[name] = dict(comment=head[12:23].split(b'\0')[0], language=head[23],
                             date=struct.unpack_from('<I', head, 24)[0], data=data[at + 32:at + 32 + size])
        at += 32 + size
    return records, None


def serialize(records):
    out = bytearray()
    for name in sorted(records):
        r = records[name]
        out += (name.encode('ascii').ljust(12, b'\0')[:12] + bytes(r['comment'])[:11].ljust(11, b'\0')
                + bytes([r['language'] & 0xFF]) + struct.pack('<II', r['date'], len(r['data'])) + r['data'])
    return bytes(out)


def used_blocks(records, device):
    return sum(blocks(len(r['data']), device[3]) for r in records.values())


def read_device(path):
    data = path.read_bytes() if path.is_file() else b''
    records, problem = parse(data)
    if problem:
        raise ValueError(f'{path} is damaged ({problem}); nothing was changed')
    return records


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def payload_sha(record):
    return hashlib.sha256(record['data']).hexdigest()


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    if os.name != 'nt':
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def write_json(path, value):
    write_atomic(path, (json.dumps(value, indent=2)+'\n').encode('utf-8'))


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')


class Busy(ValueError):
    pass


@contextlib.contextmanager
def lock(shared):
    """Exclusive use of the shared files: one game (any scenario), import or merge at a time."""
    shared = Path(shared)
    shared.mkdir(parents=True, exist_ok=True)
    message = ('Another Shining Force III game, save import or merge is using the shared backup memory ('
               + str(shared) + '). Close it first, or choose separate saves per scenario.')
    try:
        file = (shared/'backup.lock').open('a+b')
    except PermissionError as e:   # Windows: the PowerShell launcher holds it without sharing
        raise Busy(message) from e
    with file:
        if os.name == 'nt':
            import msvcrt
            try:
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as e:
                raise Busy(message) from e
            try:
                yield
            finally:
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as e:
                raise Busy(message) from e
            try:
                yield
            finally:
                fcntl.flock(file, fcntl.LOCK_UN)


def load_manifest(shared):
    path = Path(shared)/'shared-saves.json'
    if path.is_file():
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if manifest.get('format') != FORMAT:
            raise ValueError(f'{path} has an unknown format; nothing was changed')
        return manifest
    return dict(format=FORMAT, sources={}, history=[])


def free_name(prefix, taken):
    for number in range(1, 100):
        name = f'{prefix}_{number:02d}'
        if name not in taken:
            return name
    return None


def merge(shared, sources, label=None):
    """Merge per-scenario backup files into the shared ones. `sources` is a list of game-data folders.

    Each folder's files are merged once; a folder is merged again only if its file changed since
    (for example after playing with separate saves). For every save:
      * the same data already in the shared memory (any name, either device) -> not duplicated;
      * a free name -> added under its own name on its own device;
      * a name already used by different data -> added under the lowest free SFORCE3x_NN number;
      * no room on its device -> placed on the other device; no room on either -> left out and
        reported (it stays in the original file, which is never changed or deleted).
    The caller must hold lock(shared). Returns a report dict."""
    shared = Path(shared)
    shared.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(shared)
    when = stamp()
    current = {device[0]: read_device(shared/(SAVE_NAME+device[1])) for device in DEVICES}
    before = {device[0]: serialize(current[device[0]]) for device in DEVICES}
    report = dict(time=when, label=label, merged=[], added=[], renamed=[], duplicates=[], moved=[],
                  not_migrated=[], damaged=[], backups=None)
    folders = []
    for work in sources:
        work = Path(work).resolve()
        if work not in folders:
            folders.append(work)
    # Each scenario's own folder claims its record names before later scenarios' imported copies.
    folders.sort(key=lambda w: (work_scenario(w) or 9, str(w)))
    backups = shared/'migration-backups'/when
    pending = []
    for work in folders:
        scenario = work_scenario(work)
        entry = manifest['sources'].get(str(work), {})
        for device in DEVICES:
            path = work/(WORK_SAVE+device[1])
            if not path.is_file() or path.resolve() == (shared/(SAVE_NAME+device[1])).resolve():
                continue
            sha = digest(path)
            if entry.get(device[0], {}).get('sha256') == sha:
                continue
            pending.append((work, scenario, device, path, sha))
    if not pending:
        return report
    seen = {payload_sha(r): (d, n) for d in current for n, r in current[d].items()}
    for work, scenario, device, path, sha in pending:
        tag = f'scenario{scenario or "x"}-{hashlib.sha256(str(work).encode()).hexdigest()[:8]}'
        copy = backups/tag/path.name
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, copy)
        (backups/tag/'source.txt').write_text(str(path)+'\n', encoding='utf-8')
        records, problem = parse(path.read_bytes())
        if problem:
            report['damaged'].append(dict(source=str(path), problem=problem, kept=len(records)))
        result = []
        for name in sorted(records):
            record = records[name]
            item = dict(source=str(path), name=name, device=device[0], bytes=len(record['data']))
            key = payload_sha(record)
            if key in seen:
                item['shared_as'] = dict(device=seen[key][0], name=seen[key][1])
                report['duplicates'].append(item)
                result.append(dict(item, outcome='duplicate'))
                continue
            order = [device] + [d for d in DEVICES if d is not device]
            placed = None
            for target in order:
                table = current[target[0]]
                # A name is taken when either device has it, so the game never shows two different
                # saves under one name.
                taken = set(current['internal']) | set(current['cartridge'])
                new = name if name not in taken else None
                if new is None:
                    match = NAME.match(name)
                    new = free_name(match.group(1), taken) if match else None
                if new is None:
                    continue
                if used_blocks(table, target) + blocks(len(record['data']), target[3]) > usable(target):
                    continue
                table[new] = record
                placed = (target, new)
                break
            if placed is None:
                item['reason'] = 'no free space or free name on either device'
                report['not_migrated'].append(item)
                result.append(dict(item, outcome='not migrated'))
                continue
            target, new = placed
            seen[key] = (target[0], new)
            item.update(shared_device=target[0], shared_name=new)
            report['added'].append(item)
            if new != name:
                report['renamed'].append(item)
            if target is not device:
                report['moved'].append(item)
            result.append(dict(item, outcome='added'))
        # A file with a save that did not fit is tried again (and reported again) at every launch.
        left_out = any(r['outcome'] == 'not migrated' for r in result)
        manifest['sources'].setdefault(str(work), {})[device[0]] = dict(
            sha256=None if left_out else sha, merged=when, scenario=scenario, backup=str(copy), saves=result)
        report['merged'].append(dict(source=str(path), scenario=scenario, saves=len(records)))
    for device in DEVICES:
        target = shared/(SAVE_NAME+device[1])
        if target.is_file():
            keep = backups/'shared-before-merge'/target.name
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, keep)
    for device in DEVICES:
        data = serialize(current[device[0]])
        target = shared/(SAVE_NAME+device[1])
        if data != before[device[0]] or not target.exists():
            write_atomic(target, data)
    report['backups'] = str(backups)
    manifest['history'].append({k: report[k] for k in ['time', 'label', 'merged', 'renamed', 'moved', 'not_migrated', 'damaged', 'backups']})
    write_json(shared/'shared-saves.json', manifest)
    return report


def capacity(shared, scenario):
    """Space left on both shared devices, and warnings for a scenario about to play."""
    shared = Path(shared)
    need = SAVE_SIZES.get(scenario)
    devices, warnings = {}, []
    game = 'Premium Disc' if scenario == 4 else f'Scenario {scenario}'
    for device in DEVICES:
        records = read_device(shared/(SAVE_NAME+device[1]))
        used = used_blocks(records, device)
        free = max(0, usable(device) - used)
        fits = free//blocks(need, device[3]) if need else None
        devices[device[0]] = dict(used_blocks=used, free_blocks=free, usable_blocks=usable(device),
                                  saves=len(records), new_saves_that_fit=fits,
                                  blocks_per_save=blocks(need, device[3]) if need else None)
    if need:
        internal, cartridge = devices['internal'], devices['cartridge']
        if not internal['new_saves_that_fit'] and not cartridge['new_saves_that_fit']:
            warnings.append(f'Shared backup memory is full: no room for a new {game} save on the internal memory '
                            f'({internal["free_blocks"]} blocks free, {internal["blocks_per_save"]} needed) or the cartridge '
                            f'({cartridge["free_blocks"]} free, {cartridge["blocks_per_save"]} needed). You can still save over an '
                            f'existing {game} record; delete old records in the game to make room. Existing saves are never overwritten by a failed save.')
        elif cartridge['new_saves_that_fit'] is not None and internal['new_saves_that_fit'] + cartridge['new_saves_that_fit'] <= 1:
            warnings.append(f'Shared backup memory is almost full: room for only one more new {game} save '
                            f'(internal {internal["free_blocks"]} blocks free, cartridge {cartridge["free_blocks"]} free).')
        elif not internal['new_saves_that_fit']:
            warnings.append(f'Internal memory has {internal["free_blocks"]} free blocks; a new {game} save needs '
                            f'{internal["blocks_per_save"]}. Save to the cartridge ({cartridge["new_saves_that_fit"]} more fit there).')
    return dict(devices=devices, warnings=warnings)


def snapshot(shared):
    return {device[0]: read_device(Path(shared)/(SAVE_NAME+device[1])) for device in DEVICES}


def guard_foreign(shared, scenario, before, reason='native state load'):
    """After a session that restored a native state (which brings back the whole backup memory of
    that moment), put the other scenarios' saves back as they were before the session. This
    scenario's own saves are kept as the session left them. Returns a report dict."""
    shared = Path(shared)
    own = OWN_PREFIX.get(scenario)
    after = snapshot(shared)
    report = dict(reason=reason, restored=[], removed=[], not_restored=[])
    if own is None:
        report['skipped'] = 'unknown scenario'
        return report
    result = {}
    for device in DEVICES:
        mine = {n: r for n, r in after[device[0]].items() if n.startswith(own)}
        theirs_after = {n: r for n, r in after[device[0]].items() if not n.startswith(own)}
        theirs = {n: r for n, r in before[device[0]].items() if not n.startswith(own)}
        for n in sorted(set(theirs) | set(theirs_after)):
            if n not in theirs:
                report['removed'].append(dict(device=device[0], name=n))
            elif theirs_after.get(n, {}).get('data') != theirs[n]['data']:
                report['restored'].append(dict(device=device[0], name=n))
        result[device[0]] = dict(mine, **theirs)
    if not report['restored'] and not report['removed']:
        return report
    when = stamp()
    keep = shared/'migration-backups'/(when+'-after-state-load')
    for device in DEVICES:
        path = shared/(SAVE_NAME+device[1])
        if path.is_file():
            keep.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, keep/path.name)
        records = result[device[0]]
        while used_blocks(records, device) > usable(device):
            # The session's own new saves used space the other scenarios' saves had; keep every save:
            # the overflow is written beside the shared files and reported, never dropped.
            name = next(n for n in sorted(records, reverse=True) if not n.startswith(own))
            report['not_restored'].append(dict(device=device[0], name=name))
            keep.mkdir(parents=True, exist_ok=True)
            (keep/(name+'.native.bin')).write_bytes(serialize({name: records.pop(name)}))
        write_atomic(path, serialize(records))
    report['backup'] = str(keep)
    return report


def publish_own(shared, scenario, source):
    """Publish a replay session's backup (source, without suffix) into the shared memory: only this
    scenario's records are taken from it; other scenarios' saves stay as they are."""
    before = snapshot(shared)
    for device in DEVICES:
        path = Path(str(source)+device[1])
        if path.is_file():
            records, problem = parse(path.read_bytes())
            if problem:
                raise ValueError(f'{path} is damaged ({problem}); the shared backup memory was not changed')
            prefix = OWN_PREFIX[scenario]
            own = {n: r for n, r in records.items() if n.startswith(prefix)}
            before[device[0]] = dict({n: r for n, r in before[device[0]].items() if not n.startswith(prefix)}, **own)
            if used_blocks(before[device[0]], device) > usable(device):
                raise ValueError('The replay save does not fit beside the other scenarios\' saves; it remains in '+str(path))
    for device in DEVICES:
        write_atomic(Path(shared)/(SAVE_NAME+device[1]), serialize(before[device[0]]))


def known_folders(work, settings=()):
    """The current game-data folder, folders named in launcher settings files, and the default ones."""
    folders = [Path(work)]
    for path in settings:
        try:
            value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        games = value.get('games') if isinstance(value, dict) else None
        for entry in (games or {}).values():
            if isinstance(entry, dict) and entry.get('work'):
                folders.append(Path(entry['work']))
        if isinstance(value, dict) and value.get('work'):
            folders.append(Path(value['work']))
    return [f for f in folders if (f/'game.json').is_file() or (f/'desktop-ready.json').is_file()]


def describe(report):
    """Short player-facing summary of a merge report."""
    if not report['merged']:
        return ''
    text = (f'Shared backup memory: merged {len(report["merged"])} per-scenario file(s), '
            f'{len(report["added"])} save(s) added, {len(report["duplicates"])} duplicate(s) skipped')
    if report['renamed']:
        text += ', renamed ' + ', '.join(f'{r["name"]}->{r["shared_name"]}' for r in report['renamed'])
    if report['moved']:
        text += ', moved to the other device ' + ', '.join(f'{r["shared_name"]} ({r["shared_device"]})' for r in report['moved'])
    text += '. Originals kept, copies in '+str(report['backups'])+'.'
    if report['not_migrated']:
        text += (' WARNING: ' + str(len(report['not_migrated'])) + ' save(s) did not fit and stay only in their original file: '
                 + ', '.join(f'{r["name"]} ({r["source"]})' for r in report['not_migrated']) + '.')
    if report['damaged']:
        text += ' WARNING: damaged file(s), only the whole saves before the damage were merged: ' + ', '.join(d['source'] for d in report['damaged']) + '.'
    return text


def prepare_session(work, shared, settings=(), extra=()):
    """Merge known folders, then check space for this folder's scenario. Caller holds lock(shared)."""
    scenario = work_scenario(work)
    report = merge(shared, known_folders(work, settings) + [Path(p) for p in extra], label='launch '+str(work))
    room = capacity(shared, scenario)
    messages = [m for m in [describe(report)] if m] + room['warnings']
    return dict(scenario=scenario, save=str(Path(shared)/SAVE_NAME), merge=report, capacity=room, messages=messages)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare', help='merge per-scenario files and check space (caller holds the lock)')
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--shared', type=Path, default=None)
    p.add_argument('--settings', type=Path, action='append', default=[])
    p.add_argument('--migrate-from', type=Path, action='append', default=[])
    p.add_argument('--lock', action='store_true', help='take the shared lock (when the caller does not hold it)')
    g = sub.add_parser('guard', help='restore other scenarios\' saves after a native state load')
    g.add_argument('--work', type=Path, required=True)
    g.add_argument('--shared', type=Path, default=None)
    g.add_argument('--before', type=Path, required=True, help='copy of backup.bin before the session (.cartridge beside it)')
    u = sub.add_parser('publish', help='publish a replay session\'s own-scenario saves into the shared memory')
    u.add_argument('--work', type=Path, required=True)
    u.add_argument('--shared', type=Path, default=None)
    u.add_argument('--source', type=Path, required=True)
    s = sub.add_parser('status', help='space on the shared devices')
    s.add_argument('--shared', type=Path, default=None)
    s.add_argument('--scenario', type=int, choices=[1, 2, 3])
    a = ap.parse_args(argv)
    shared = a.shared or default_dir()
    try:
        if a.command == 'prepare':
            context = lock(shared) if a.lock else contextlib.nullcontext()
            with context:
                result = prepare_session(a.work, shared, a.settings or default_settings(),
                                         a.migrate_from + default_folders())
        elif a.command == 'guard':
            before = {d[0]: read_device(Path(str(a.before)+d[1])) for d in DEVICES}
            result = guard_foreign(shared, work_scenario(a.work), before)
        elif a.command == 'publish':
            publish_own(shared, work_scenario(a.work), a.source)
            result = dict(published=str(a.source))
        else:
            result = capacity(shared, a.scenario)
        print(json.dumps(result, indent=2, default=str))
    except (OSError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
