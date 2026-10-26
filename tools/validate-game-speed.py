"""Compare a windowed native route at 1x/2x/3x; all fixtures stay external."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import wave
import struct
import zlib

REPO = Path(__file__).resolve().parents[1]


def external(value):
    path = Path(value).resolve()
    if path == REPO or REPO in path.parents:
        raise ValueError('Keep game data and test output outside the source repository')
    return path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pcm_sha(path):
    digest = hashlib.sha256()
    with wave.open(str(path), 'rb') as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (2, 2, 44100):
            raise ValueError('Unexpected virtual PCM format')
        while data := audio.readframes(65536):
            digest.update(data)
    return digest.hexdigest()


def main():
    ap = argparse.ArgumentParser(__doc__)
    for name in ('exe', 'work', 'cue', 'manifest', 'out'):
        ap.add_argument('--'+name, type=Path, required=True)
    ap.add_argument('--case', required=True)
    ap.add_argument('--frames', type=int)
    ap.add_argument('--render-scale', type=int, choices=(1, 2, 4, 5))
    ap.add_argument('--aa', action='store_true', help='Enable the optional Light AA presentation pass')
    ap.add_argument('--ray', action='store_true', help='Enable experimental GPU screen-space ray shadows')
    a = ap.parse_args()
    exe, work, cue, out = map(external, (a.exe, a.work, a.cue, a.out))
    case = next(c for c in json.loads(a.manifest.read_text())['cases'] if c['name'] == a.case)
    spec = case.get('host_speed_validation', {})
    a.frames = a.frames if a.frames is not None else spec.get('frames', 600)
    a.render_scale = a.render_scale if a.render_scale is not None else spec.get('render_scale', 5)
    end = case['vblanks']
    start = end-a.frames
    if not 0 < start < end or a.frames < 120:
        raise ValueError('Use at least 120 measured fields after boot')
    out.mkdir(parents=True, exist_ok=False)
    recording = external(work/case['input'])
    seeds = {key: sha(external(work/case[key])) if case[key] else None
             for key in ('internal', 'cartridge')}
    tracks = re.findall(r'^\s*FILE\s+"([^"]+)"', cue.read_text(encoding='utf-8-sig'), re.M)
    if not tracks:
        raise ValueError('No quoted CUE tracks')
    disc = hashlib.sha256('\n'.join([sha(cue).upper()]+[
        sha(external(cue.parent/name)).upper() for name in tracks]).encode()).hexdigest()
    identity = sha(exe)+':'+disc
    seed = out/'seed'
    seed.mkdir()
    for key, name in (('internal', 'backup.bin'), ('cartridge', 'backup.bin.cartridge')):
        (seed/name).write_bytes(external(work/case[key]).read_bytes() if case[key] else b'')
    snapshot = seed/'start.satstate'
    command = [str(exe), '--headless', '--cue', str(cue), '--save', str(seed/'backup.bin'),
               '--settings', '-', '--clock', case['clock'], '--input', '@'+str(recording),
               '--vblanks', str(start+5), '--state-at', str(start), '--state-out', str(snapshot),
               '--out', str(seed), '--log', str(seed/'run.log')]
    with (seed/'console.log').open('wb') as stream:
        subprocess.run(command, env={**os.environ, 'SF3_STATE_ID': identity},
                       stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=300)
    raw = snapshot.read_bytes()
    if raw[:8] != b'SATSTATE' or zlib.crc32(raw[:-4]) != struct.unpack_from('<I', raw, len(raw)-4)[0]:
        raise ValueError('Invalid initial native snapshot')
    cursor = 16+struct.unpack_from('<I', raw, 12)[0]
    actual_start = None
    while cursor < len(raw)-4:
        size = raw[cursor]
        name = raw[cursor+1:cursor+1+size].decode()
        cursor += 1+size
        size = struct.unpack_from('<Q', raw, cursor)[0]
        cursor += 8
        if name == 'video':
            actual_start = struct.unpack_from('<Q', raw, cursor+8)[0]
        cursor += size
    if actual_start is None or not start <= actual_start < start+5:
        raise ValueError('Snapshot missed the requested field')
    start = actual_start
    # A snapshot already contains held pad state. Supply subsequent transitions only.
    script = ','.join(token for token in recording.read_text().split(',')
                      if token.strip() and int(token.split(':')[0]) >= start)
    (out/'input.txt').write_text(script)
    results = []
    for speed in (1, 2, 3):
        folder = out/f'{speed}x'
        folder.mkdir()
        for key, name in (('internal', 'backup.bin'), ('cartridge', 'backup.bin.cartridge')):
            (folder/name).write_bytes(external(work/case[key]).read_bytes() if case[key] else b'')
        env = os.environ.copy()
        for key in ('SF3_GPU_OFFSCREEN', 'SDL_VIDEODRIVER', 'SDL_AUDIODRIVER',
                    'SF3_REPLAY_ROOT', 'SF3_REPLAY_SEED', 'SF3_CONTROLLER_DIR', 'SF3_WIDESCREEN'):
            env.pop(key, None)
        env.update(SF3_GAME_SPEED=str(speed), SF3_PERF_FROM=str(start+1),
                   SF3_AA='1' if a.aa else '0',
                   SF3_RAY_SHADOWS='1' if a.ray else '0',
                   SF3_STATE_ID=identity,
                   SF3_GPU_CAPTURE_AT=str(end),
                   SF3_CRASH_DIR=str(folder), SF3_RAM_DUMP=str(folder/'crash-wram-high.bin'))
        command = [str(exe), '--cue', str(cue), '--save', str(folder/'backup.bin'),
                   '--settings', '-', '--clock', case['clock'], '--input', '@'+str(out/'input.txt'),
                   '--state-in', str(snapshot), '--vblanks', str(end), '--shot', str(end),
                   '--dump', str(end), '--wav', str(folder/'audio.wav'),
                   '--render-scale', str(a.render_scale), '--out', str(folder),
                   '--log', str(folder/'run.log')]
        started = time.monotonic()
        result = dict(speed=speed, passed=False, command=command)
        try:
            with (folder/'console.log').open('wb') as stream:
                process = subprocess.run(command, env=env, stdout=stream,
                                         stderr=subprocess.STDOUT, timeout=300)
            log = (folder/'run.log').read_text(errors='replace')
            console = (folder/'console.log').read_text(errors='replace')+'\n'+log
            perf = re.search(r'presentation profile: (\d+) fields, ([\d.]+) seconds, ([\d.]+) fields/sec', console)
            audio = re.search(r'audio stream: (\d+) times empty, (\d+) chunks dropped, (\d+) producer waits', console)
            result.update(exit_code=process.returncode,
                          completed=f'after {end} VBlanks' in log and 'stopped (VBlank limit)' in log,
                          gpu='Geometry GPU: backend=' in log,
                          frame=sha(folder/f'shot-{end}.png'), video=sha(folder/f'dump-{end}.bin'),
                          virtual_pcm=pcm_sha(folder/'audio.wav'),
                          internal=sha(folder/'backup.bin'), cartridge=sha(folder/'backup.bin.cartridge'))
            enhanced = folder/f'gpu-shot-{end}.png'
            if enhanced.exists():
                result['gpu_frame'] = sha(enhanced)
            if perf:
                result.update(measured_fields=int(perf[1]), measured_seconds=float(perf[2]),
                              fields_per_second=float(perf[3]), achieved_multiplier=round(float(perf[3])/59.826, 3))
            if audio:
                result.update(audio_underruns=int(audio[1]), audio_dropped=int(audio[2]), audio_waits=int(audio[3]))
            result['matches_1x'] = not results or all(result.get(k) == results[0].get(k)
                                                     for k in ('frame', 'video', 'virtual_pcm', 'internal', 'cartridge', 'gpu_frame'))
            result['passed'] = (process.returncode == 0 and result['completed'] and
                                result['matches_1x'] and perf is not None and
                                result.get('audio_dropped') == 0 and 'FATAL' not in log)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            result['error'] = str(error)
        result['total_seconds'] = round(time.monotonic()-started, 3)
        results.append(result)
        print(json.dumps({k: v for k, v in result.items() if k != 'command'}), flush=True)
    unchanged = all(not case[k] or sha(external(work/case[k])) == seeds[k] for k in seeds)
    report = dict(passed=all(r['passed'] for r in results) and unchanged, case=a.case,
                  antialiasing='Light' if a.aa else 'Off',
                  ray_shadows='Low' if a.ray else 'Off',
                  executable_sha256=sha(exe), render_scale=a.render_scale, start=start, end=end,
                  clock=case['clock'], input_sha256=sha(recording), source_saves_unchanged=unchanged,
                  initial_saves=seeds, results=results)
    report['initial_state_sha256'] = sha(snapshot)
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
