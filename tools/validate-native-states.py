"""Compare direct native snapshot restoration with an uninterrupted external fixture."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import struct
import subprocess
import wave
import zlib

ROOT=Path(__file__).resolve().parents[1]

def external(value):
    p=Path(value).resolve()
    if p==ROOT or ROOT in p.parents:raise ValueError('State fixtures and results must remain outside the source repository')
    return p

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def parts(path):
    b=path.read_bytes()
    if b[:8]!=b'SATSTATE' or struct.unpack_from('<I',b,8)[0]!=2:raise ValueError('Unsupported snapshot')
    if zlib.crc32(b[:-4])!=struct.unpack_from('<I',b,len(b)-4)[0]:raise ValueError('Snapshot checksum mismatch')
    at=16+struct.unpack_from('<I',b,12)[0];result={}
    while at<len(b)-4:
        n=b[at];at+=1;name=b[at:at+n].decode();at+=n
        size=struct.unpack_from('<Q',b,at)[0];at+=8
        if size>len(b)-4-at or name in result:raise ValueError('Invalid snapshot part')
        result[name]=b[at:at+size];at+=size
    return result

def pcm(path):
    with wave.open(str(path),'rb') as w:
        if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(2,2,44100):raise ValueError('Unexpected audio format')
        return w.readframes(w.getnframes())

def validate(a):
    work,out,exe=external(a.work),external(a.out),external(a.exe)
    out.mkdir(parents=True,exist_ok=False)
    case=next(c for c in json.loads(a.manifest.read_text())['cases'] if c['name']==a.case)
    end=case['vblanks'];at=a.at if a.at is not None else end*3//4
    if not 0<at<end-4:raise ValueError('Snapshot point must precede the final frame')
    cue=a.cue.resolve()
    tracks=re.findall(r'^\s*FILE\s+"([^"]+)"',cue.read_text(encoding='utf-8-sig'),re.M)
    if not tracks:raise ValueError('No quoted CUE tracks')
    disc_parts=[sha(cue).upper()]+[sha(cue.parent/name).upper() for name in tracks]
    disc_id=hashlib.sha256('\n'.join(disc_parts).encode()).hexdigest()
    identity=sha(exe)+':'+disc_id
    env={**os.environ,'SF3_STATE_ID':identity,'SDL_AUDIODRIVER':'dummy'}
    recording=external(work/case['input']).read_text(encoding='utf-8-sig').strip()
    seed_hashes={key:sha(external(work/case[key])) for key in ('internal','cartridge') if case[key]}
    initial=external(work/case['state_in']) if case.get('state_in') else None
    initial_hash=sha(initial) if initial else None
    initial_parts=parts(initial) if initial else None
    first_frame=struct.unpack_from('<Q',initial_parts['video'],8)[0] if initial else 0
    first_sample=struct.unpack_from('<Q',initial_parts['sound'],1)[0] if initial else 0
    if not first_frame<at<end-4:raise ValueError('Snapshot point must follow the initial state and precede the final frame')

    def run(name,state=None,save_at=None,bad_id=False,source_parts=None):
        state=state or initial
        folder=out/name;folder.mkdir()
        for key,filename in [('internal','backup.bin'),('cartridge','backup.bin.cartridge')]:
            target=folder/filename
            if case[key]:shutil.copyfile(external(work/case[key]),target)
            else:target.write_bytes(b'')
        before={p.name:sha(p) for p in folder.glob('backup.bin*')}
        script=recording
        if state:
            saved=parts(state) if source_parts is None else source_parts
            frame=struct.unpack_from('<Q',saved['video'],8)[0]
            # No prefix inputs are supplied: this must start directly at the snapshot.
            script=','.join(s for s in recording.split(',') if s and int(s.split(':')[0])>=frame)
        (folder/'input.txt').write_text(script)
        command=[str(exe),'--headless','--cue',str(a.cue.resolve()),'--save',str(folder/'backup.bin'),
                 '--settings','-','--clock',case['clock'],'--input','@'+str(folder/'input.txt'),
                 '--vblanks',str(end),'--shot',str(end),'--dump',str(end),'--wav',str(folder/'audio.wav'),
                 '--out',str(folder),'--log',str(folder/'run.log')]
        if state:command+=['--state-in',str(state)]
        if save_at is not None:command+=['--state-out',str(folder/'quick.satstate'),'--state-at',str(save_at)]
        run_env={**env,'SF3_CRASH_DIR':str(folder),'SF3_RAM_DUMP':str(folder/'crash-wram-high.bin')}
        if bad_id:run_env['SF3_STATE_ID']='different-build-or-disc'
        with (folder/'console.log').open('wb') as log:
            p=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,env=run_env,timeout=240)
        return folder,p.returncode,before

    baseline,code,_=run('uninterrupted',save_at=at)
    if code or not (baseline/'quick.satstate').exists():raise RuntimeError('Uninterrupted fixture failed or produced no snapshot')
    snapshots=parts(baseline/'quick.satstate');frame=struct.unpack_from('<Q',snapshots['video'],8)[0]
    restored,code,_=run('restored',baseline/'quick.satstate',min(frame+120,end-2))
    results=[]
    for name,folder,state,status in [('restored',restored,baseline/'quick.satstate',code)]:
        data=parts(state);samples=struct.unpack_from('<Q',data['sound'],1)[0]
        results.append(dict(name=name,exit_code=status,
            frame_matches=sha(folder/f'shot-{end}.png')==sha(baseline/f'shot-{end}.png'),
            video_matches=sha(folder/f'dump-{end}.bin')==sha(baseline/f'dump-{end}.bin'),
            audio_matches=pcm(folder/'audio.wav')==pcm(baseline/'audio.wav')[(samples-first_sample)*4:],
            backup_matches=all((folder/n).read_bytes()==(baseline/n).read_bytes() for n in ['backup.bin','backup.bin.cartridge']),
            resumed_at=struct.unpack_from('<Q',data['video'],8)[0]))
    # Repeated snapshots must themselves be loadable, after native host stacks changed.
    second=restored/'quick.satstate'
    if not second.exists():raise RuntimeError('Restored session produced no second snapshot')
    again,status,_=run('restored-again',second)
    data=parts(second);samples=struct.unpack_from('<Q',data['sound'],1)[0]
    results.append(dict(name='restored-again',exit_code=status,
        frame_matches=sha(again/f'shot-{end}.png')==sha(baseline/f'shot-{end}.png'),
        video_matches=sha(again/f'dump-{end}.bin')==sha(baseline/f'dump-{end}.bin'),
        audio_matches=pcm(again/'audio.wav')==pcm(baseline/'audio.wav')[(samples-first_sample)*4:],
        backup_matches=all((again/n).read_bytes()==(baseline/n).read_bytes() for n in ['backup.bin','backup.bin.cartridge']),
        resumed_at=struct.unpack_from('<Q',data['video'],8)[0]))
    rejected,status,before=run('wrong-identity',baseline/'quick.satstate',bad_id=True)
    results.append(dict(name='wrong-identity',rejected=status!=0,
                        backups_unchanged=all(sha(rejected/n)==h for n,h in before.items())))
    corrupt=bytearray((baseline/'quick.satstate').read_bytes());corrupt[len(corrupt)//2]^=1
    damaged=out/'damaged.satstate';damaged.write_bytes(corrupt)
    rejected,status,before=run('damaged',damaged,source_parts=snapshots)
    results.append(dict(name='damaged',rejected=status!=0,
                        backups_unchanged=all(sha(rejected/n)==h for n,h in before.items())))
    reference,status,_=run('no-snapshot-reference')
    results.append(dict(name='saving-does-not-change-gameplay',exit_code=status,
        frame_matches=sha(reference/f'shot-{end}.png')==sha(baseline/f'shot-{end}.png'),
        video_matches=sha(reference/f'dump-{end}.bin')==sha(baseline/f'dump-{end}.bin'),
        audio_matches=pcm(reference/'audio.wav')==pcm(baseline/'audio.wav')))
    source_unchanged=all(sha(external(work/case[k]))==h for k,h in seed_hashes.items())
    if initial:source_unchanged &= sha(initial)==initial_hash
    passed=source_unchanged and all(all(v for k,v in r.items() if k.endswith(('_matches','_unchanged')) or k=='rejected') and r.get('exit_code',0)==0 for r in results)
    report=dict(passed=passed,case=a.case,executable_sha256=sha(exe),snapshot_vblank=frame,
                slave_on=bool(snapshots['machine'][-6]),source_saves_unchanged=source_unchanged,results=results,
                initial_state_sha256=initial_hash,initial_vblank=first_frame,
                caveat='Exact fixture comparison; does not certify unvisited gameplay or all snapshot times.')
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));return 0 if passed else 1

def main():
    p=argparse.ArgumentParser(__doc__)
    for name in ('work','out','exe','cue','manifest'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--case',required=True);p.add_argument('--at',type=int)
    a=p.parse_args()
    existed=a.out.exists()
    try:return validate(a)
    except (OSError,ValueError,RuntimeError,struct.error,subprocess.TimeoutExpired) as e:
        if not existed and a.out.exists():(a.out/'failure.json').write_text(json.dumps(dict(passed=False,error=str(e)),indent=2)+'\n')
        p.exit(1,str(e)+'\n')

if __name__=='__main__':raise SystemExit(main())
