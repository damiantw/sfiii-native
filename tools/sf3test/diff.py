"""Differential testing: the same save and the same inputs on our runtime and on a libretro reference
core (an external emulator build, never part of this repository), compared at sync points placed by
the game's own frame tick, so the reference's slower CD loads do not shift the inputs.

Compared at each sync point: the SF3 live state block (the save payload's RAM copy), the map and
battle ids, and the picture. Pure comparison helpers are unit-tested with invented data."""
import json
from pathlib import Path

from . import memory_map, saves, sweep

# Work-RAM layout of the reference core's RETRO_MEMORY_SYSTEM_RAM: the patched Yabause build used
# here exposes the high bank alone (HighWram) at offset 0.
YABAUSE_WORK_RAM = ((0x06000000, 0),)
YABAUSE_OPTIONS = {'yabause_force_hle_bios': 'enabled', 'yabause_frameskip': 'disabled',
                   'yabause_addon_cartridge': 'none'}


def block_diff(ours, theirs, skip=()):
    """Offsets where two equal-length byte strings differ, minus any in `skip` (a set of offsets)."""
    return [i for i, (a, b) in enumerate(zip(ours, theirs)) if a != b and i not in skip]


def runs(offsets):
    """Collapse sorted offsets into [start, end) ranges."""
    out = []
    for o in offsets:
        if out and out[-1][1] == o:
            out[-1][1] = o + 1
        else:
            out.append([o, o + 1])
    return out


def compare_point(v, ours, theirs, skip=()):
    """One sync point's comparison record from two {'block','frame'} dicts (frame may be None)."""
    diff = block_diff(ours['block'], theirs['block'], skip)
    rec = dict(vblank=v, core_frame=theirs.get('frame_no'),
               map=[ours['block'][memory_map.MAP_ID], theirs['block'][memory_map.MAP_ID]],
               battle=[ours['block'][memory_map.BATTLE_ID], theirs['block'][memory_map.BATTLE_ID]],
               block_bytes_differing=len(diff), block_ranges=runs(diff)[:40])
    rec['state_match'] = not diff
    return rec


def dots_over(ours, theirs, tol):
    """Dots whose largest channel error exceeds `tol`, ours centred in theirs (agent.Frame-like:
    width, height, rgb). A tolerance absorbs the reference's 16-bit colour output."""
    dx, dy = (theirs.width - ours.width) // 2, (theirs.height - ours.height) // 2
    n = 0
    for y in range(ours.height):
        a = ours.rgb[y * ours.width * 3:(y + 1) * ours.width * 3]
        o = ((y + dy) * theirs.width + dx) * 3
        b = theirs.rgb[o:o + ours.width * 3]
        if a == b:
            continue
        for x in range(0, ours.width * 3, 3):
            if max(abs(a[x] - b[x]), abs(a[x + 1] - b[x + 1]), abs(a[x + 2] - b[x + 2])) > tol:
                n += 1
    return n


def summarize(points, loaded_from=None):
    """Totals over sync points at or after `loaded_from` (the first VBlank the save is live)."""
    live = [p for p in points if loaded_from is None or p['vblank'] >= loaded_from]
    first = next((p for p in live if not p['state_match']), None)
    return dict(points=len(live), state_matches=sum(p['state_match'] for p in live),
                same_map=sum(p['map'][0] == p['map'][1] for p in live),
                first_divergence=first['vblank'] if first else None)


def run(saturn, cue, profile, core_so, record, work, vblanks, seed, every=250, tick=None, tol=24):
    """Play one save on both and compare; writes work/diff.json and side-by-side pictures."""
    from saturnrecomp import agent, reference as R

    mm = memory_map.lookup(profile)
    tick = tick or mm['tick']
    size = memory_map.PAYLOAD_SIZE[mm['scenario']]
    base = mm['state_base']
    work = Path(work)
    (work / 'core-save').mkdir(parents=True, exist_ok=True)
    (work / 'core-system').mkdir(parents=True, exist_ok=True)
    rec = dict(record, name=f"SFORCE3{mm['scenario']}_01")
    (work / 'backup.bin').write_bytes(saves.native_backup([rec]))
    if (work / 'backup.bin.cartridge').exists():
        (work / 'backup.bin.cartridge').unlink()
    (work / 'core-save' / (Path(cue).stem + '.srm')).write_bytes(saves.build_bram([rec]))

    steps = sweep.menu_inputs() + sweep.explore_inputs(sweep.LOAD_END + 60, vblanks - 30, seed)
    script = sweep.input_script(steps)
    (work / 'input.txt').write_text(script + '\n')
    presses = R.presses(script)
    checks = list(range(every, vblanks + 1, every))

    ticks, ours = {}, {}
    with agent.start(str(saturn), ['--headless', '--cue', str(cue), '--save', str(work / 'backup.bin'),
                                   '--settings', '-'], str(work / 'ours')) as r:
        for v in range(1, vblanks + 1):
            for port, buttons in presses.get(v, []):
                r.pad('+'.join(sorted(buttons)), pad=port + 1)
            ticks[v] = r.read32(tick)
            if v in checks:
                ours[v] = dict(block=r.read(base, size), frame=r.frame())
            if v < vblanks:
                r.step()

    R.WORK_RAM = YABAUSE_WORK_RAM
    core = R.Core(core_so, str(work / 'core-system'), str(cue), options=YABAUSE_OPTIONS,
                  save_dir=str(work / 'core-save'))
    theirs = {}

    def on_shot(v, n):
        theirs[v] = dict(block=core.read(base, size), frame=core.frame, frame_no=n)

    core_presses = {v: [(p, set(b)) for p, b in what] for v, what in presses.items()}
    done = R.play_synced(core, tick, ticks, core_presses, checks, vblanks * 3, on_shot)
    if done is None and core.frame is not None:     # the reference never reached our later points
        core.frame.save_png(str(work / 'core-last.png'))
    core_tick_end = core.read32(tick)

    points = []
    for v in checks:
        if v not in theirs:
            points.append(dict(vblank=v, core_frame=None, unreached=True, state_match=False,
                               map=[ours[v]['block'][memory_map.MAP_ID], None]))
            continue
        p = compare_point(v, ours[v], theirs[v])
        if ours[v]['frame'] is not None and theirs[v]['frame'] is not None:
            n, worst, pic = R.difference(ours[v]['frame'], theirs[v]['frame'])
            p.update(dots_differing=n, worst=worst,
                     dots_over_tol=dots_over(ours[v]['frame'], theirs[v]['frame'], tol))
            pic.save_png(str(work / f'side-{v}.png'))
        points.append(p)
    expect = (record['data'][memory_map.MAP_ID], record['data'][memory_map.BATTLE_ID])
    loaded = next((p['vblank'] for p in points if not p.get('unreached') and tuple(p['map']) == (expect[0], expect[0])
                   ), None)
    out = dict(profile=profile, vblanks=vblanks, seed=seed, tick=f'{tick:08X}', core_frames=done or core.frames,
               core_finished=done is not None, our_tick_end=ticks[vblanks], core_tick_end=core_tick_end,
               expected_map=expect[0], loaded_at=loaded, summary=summarize(
                   [p for p in points if not p.get('unreached')], loaded), points=points)
    (work / 'diff.json').write_text(json.dumps(out, indent=1) + '\n')
    return out
