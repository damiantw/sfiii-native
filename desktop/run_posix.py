"""Native sessions, backups and direct state/replay restarts for Linux/macOS."""
import contextlib
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import uuid
import zlib

sys.dont_write_bytecode = True
from prepare_posix import APP, PAYLOAD, common, lock, package_root
from ai_packs import validate_selection
import shared_saves


def within(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('Requested checkpoint is outside this installation.')
    return path


def selected_build(work):
    name = (work/'native-build.txt').read_text().strip()
    if not re.fullmatch(r'build-[A-Za-z0-9_-]+', name):
        raise ValueError('Invalid native build selection.')
    return within(work/name,work)


def identities(exe, cue):
    tracks = re.findall(r'^\s*FILE\s+"([^"]+)"',cue.read_text(encoding='utf-8-sig'),re.M)
    if not tracks:
        raise ValueError('CUE has no quoted tracks.')
    parts = [common.sha(cue).upper()]+[common.sha(cue.parent/name).upper() for name in tracks]
    import hashlib
    return common.sha(exe), hashlib.sha256('\n'.join(parts).encode()).hexdigest()


def check_state(path, identity):
    if not path.is_file() or not 20 <= path.stat().st_size <= 128*1024*1024:
        raise ValueError('Missing or invalid native state.')
    data = path.read_bytes()
    if data[:8] != b'SATSTATE' or struct.unpack_from('<I',data,8)[0] != 2:
        raise ValueError('Unsupported native state format.')
    size = struct.unpack_from('<I',data,12)[0]
    if size > 256 or 16+size > len(data)-4 or zlib.crc32(data[:-4]) != struct.unpack_from('<I',data,len(data)-4)[0]:
        raise ValueError('Damaged native state; current progress was not changed.')
    if data[16:16+size] != identity.encode():
        raise ValueError('State belongs to another native build or disc.')


def copy_if_present(source, destination):
    if source.is_file():
        shutil.copy2(source,destination)
        return True
    return False


def shared_setup(work, separate=False, shared_dir=None, settings=None, extra=()):
    """(shared folder or None, session report). Merges this and the other known game-data folders'
    per-scenario saves into the shared backup memory once, then checks its space."""
    if separate:
        return None, dict(mode='separate', save=str(work/'experimental-backup.bin'), messages=[])
    shared = Path(shared_dir).resolve() if shared_dir else shared_saves.default_dir()
    if shared == work or work in shared.parents:
        raise ValueError('The shared backup memory folder must be outside the game-data folder.')
    settings = shared_saves.default_settings() if settings is None else settings
    extra = list(extra)+shared_saves.default_folders()
    report = shared_saves.prepare_session(work,shared,settings,extra)
    report['mode'] = 'shared'
    (work/'shared-backup-memory.txt').write_text(
        'This game uses the backup memory shared by all scenarios:\n'+str(shared/'backup.bin')+'\n'
        'Any experimental-backup.bin in this folder was merged into it once and is kept unchanged;\n'
        'it is used again only when you choose separate saves per scenario.\n')
    return shared, report


def play(work, native_state=None, headless=0, separate=False, shared_dir=None, settings=None, extra=()):
    work = common.external_work(work,package_root())
    with lock(work), contextlib.ExitStack() as stack:
        if not separate:
            stack.enter_context(shared_saves.lock(Path(shared_dir).resolve() if shared_dir else shared_saves.default_dir()))
        shared, saves = shared_setup(work,separate,shared_dir,settings,extra)
        for message in saves['messages']:
            common.status('saves',message)
            print('SF3 saves: '+message,file=sys.stderr)
        game = json.loads((work/'game.json').read_text())
        artwork_environment = validate_selection(work, APP/'profiles')
        build = selected_build(work)
        exe, cue = build/'saturn', Path(game['cue']).resolve(strict=True)
        build_id, disc_id = identities(exe,cue)
        identity = build_id+':'+disc_id
        state_root = work/'native-states'/(build_id[:16]+'-'+disc_id[:16])
        replay_root = work/'replay-checkpoints'
        replay = None
        while True:
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'-'+uuid.uuid4().hex[:6]
            session = work/'sessions'/stamp
            seed = session/'replay-seed'
            seed.mkdir(parents=True)
            (work/'last-session.txt').write_text(str(session))
            (seed/'build-id.txt').write_text(build_id)
            (seed/'disc-id.txt').write_text(disc_id)
            clock = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
            context = dict(format='SF3REPLAY1',clock=clock,executableSha256=build_id,discSha256=disc_id)
            save, settings = (shared/shared_saves.SAVE_NAME if shared else work/'experimental-backup.bin'), work/'settings.ini'
            for source,target in [(save,seed/'backup.bin'),(Path(str(save)+'.cartridge'),seed/'backup.bin.cartridge')]:
                if not copy_if_present(source,target):
                    target.write_bytes(b'')
            copy_if_present(settings,seed/'settings.ini')
            common.atomic_json(seed/'context.json',context)
            resume = None
            if replay:
                replay = within(replay,replay_root)
                result = subprocess.run([str(build/'replay_checkpoint'),'verify',str(replay),str(seed)],check=True,capture_output=True,text=True)
                resume = int(result.stdout.strip())
                for name in ['context.json','build-id.txt','disc-id.txt','backup.bin','backup.bin.cartridge','settings.ini']:
                    copy_if_present(replay/'seed'/name,seed/name)
                if not (replay/'seed/backup.bin.cartridge').exists():
                    (seed/'backup.bin.cartridge').write_bytes(b'')
                if not (replay/'seed/settings.ini').exists():
                    (seed/'settings.ini').unlink(missing_ok=True)
                context = json.loads((seed/'context.json').read_text(encoding='utf-8-sig'))
                save, settings = session/'replay-backup.bin', session/'replay-settings.ini'
                shutil.copy2(seed/'backup.bin',save)
                shutil.copy2(seed/'backup.bin.cartridge',Path(str(save)+'.cartridge'))
                copy_if_present(seed/'settings.ini',settings)
            for name in ['experimental-backup.bin','experimental-backup.bin.cartridge','settings.ini','controller-mappings.txt']:
                copy_if_present(work/name,session/('before-'+name))
            if shared:
                for suffix in ['','.cartridge']:
                    copy_if_present(shared/(shared_saves.SAVE_NAME+suffix),session/('before-shared-backup.bin'+suffix))
            common.atomic_json(session/'saves.json',saves)
            (session/'input.txt').write_text('')
            args = [str(exe),'--cue',str(cue),'--save',str(save),'--settings',str(settings),
                    '--clock',context['clock'],'--out',str(session),'--log',str(session/'run.log'),
                    '--record-input',str(session/'input.txt')]
            if native_state:
                if replay:
                    raise ValueError('Choose a native state or a replay, not both.')
                native_state = within(native_state,work/'native-states')
                check_state(native_state,identity)
                shutil.copy2(native_state,session/'loaded.satstate')
                live = save.parent
                presence = {name:copy_if_present(live/name,session/('before-native-state-load-'+name))
                            for name in [save.name,save.name+'.cartridge']}
                common.atomic_json(session/'before-native-state-load.json',presence)
                args += ['--state-in',str(session/'loaded.satstate')]
            if replay:
                args += ['--input','@'+str(replay/'input.txt'),'--resume',str(resume),'--resume-label','Loading replay checkpoint']
            if headless:
                args += ['--headless','--vblanks',str(headless)]
            env = {k:v for k,v in os.environ.items() if not k.startswith('SF3_')}
            env.update(SF3_CONTROLLER_DIR=str(work),SF3_CRASH_DIR=str(session),SF3_RAM_DUMP=str(session/'crash-wram-high.bin'),
                       SF3_REPLAY_ROOT=str(replay_root),SF3_REPLAY_SEED=str(seed),SF3_STATE_ROOT=str(state_root),SF3_STATE_ID=identity)
            env.update(artwork_environment)
            receipt = dict(executable_sha256=build_id,arguments=args,exit_code=None,replay=str(replay) if replay else None,
                           native_state=str(native_state) if native_state else None,live_replay_progress_published=False)
            common.atomic_json(session/'session.json',receipt)
            before = shared_saves.snapshot(shared) if shared and native_state and not replay else None
            with (session/'console.log').open('wb') as log:
                result = subprocess.run(args,env=env,stdout=log,stderr=subprocess.STDOUT)
            receipt['exit_code'] = result.returncode
            if before is not None:
                # A native state brings back the whole backup memory of its moment; keep the other
                # scenarios' saves as they were before this session.
                guard = shared_saves.guard_foreign(shared,saves['scenario'],before)
                receipt['shared_saves_guard'] = guard
                if guard['restored'] or guard['removed']:
                    common.status('saves','Kept the other scenarios\' saves as they were before the native state load ('
                                  +str(len(guard['restored'])+len(guard['removed']))+' record(s)); copies in '+guard['backup'])
                if guard['not_restored']:
                    common.status('saves','WARNING: no room to restore '+', '.join(r['name'] for r in guard['not_restored'])+'; kept in '+guard['backup'])
            common.atomic_json(session/'session.json',receipt)
            # Replay saves remain in their session; never adopt historical progress implicitly.
            if result.returncode:
                raise RuntimeError('Game stopped with an error. Local details: '+str(session))
            replay = native_state = None
            if (session/'reload-request.txt').is_file():
                replay = within(Path((session/'reload-request.txt').read_text().strip()),replay_root)
            if (session/'native-state-request.txt').is_file():
                native_state = within(Path((session/'native-state-request.txt').read_text().strip()),work/'native-states')
            if not replay and not native_state:
                return


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--work',type=Path,required=True)
    p.add_argument('--state',type=Path)
    p.add_argument('--headless-fields',type=int,default=0)
    p.add_argument('--separate-saves',action='store_true',
                   help='use this folder\'s own experimental-backup.bin (the old behaviour: no automatic scenario transfer)')
    p.add_argument('--shared-saves',type=Path,default=None,metavar='DIR',
                   help='folder of the backup memory shared by all scenarios (default: '+str(shared_saves.default_dir())+')')
    p.add_argument('--launcher-settings',type=Path,action='append',default=None,
                   help='launcher settings whose game-data folders are merged once (default: the launcher\'s own)')
    p.add_argument('--migrate-from',type=Path,action='append',default=[],metavar='WORK',
                   help='another game-data folder whose saves are merged once into the shared memory')
    a = p.parse_args()
    try:
        play(a.work,a.state,a.headless_fields,a.separate_saves,a.shared_saves,a.launcher_settings,a.migrate_from)
    except Exception as e:
        print(str(e),file=sys.stderr)
        sys.exit(1)
