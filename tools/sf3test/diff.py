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


LOAD_JUMP = 600       # the tick (play time) jumps by more than this when a save is loaded
C_EVERY = 158         # menu/dialogue confirm interval (each side on its own clock)


class OurSide:
    def __init__(self, run):
        self.r, self.frames = run, 1

    def step(self):
        self.r.step()
        self.frames += 1

    def pad(self, buttons):
        self.r.pad('+'.join(sorted(buttons)))

    def read(self, addr, n):
        return self.r.read(addr, n)

    def frame(self):
        return self.r.frame()


class CoreSide:
    def __init__(self, core):
        self.c, self.frames = core, 0

    def step(self):
        self.c.run()
        self.frames += 1

    def pad(self, buttons):
        self.c.pads[0] = set(buttons)

    def read(self, addr, n):
        return self.c.read(addr, n)

    def frame(self):
        return self.c.frame


def tick_of(side, tick):
    return int.from_bytes(side.read(tick, 4), 'big')


def drive_to_load(side, tick, start_ticks, limit, start_frames=None):
    """Title and Continue menu on one side: START when the boot tick reaches each of `start_ticks`
    (or at `start_frames`, appending the ticks there to `start_ticks`), then C every C_EVERY frames
    until the tick jumps (the save's play time is restored). Returns the frame of the load, or None."""
    pending = list(start_frames if start_frames else start_ticks)
    release, last_c, prev = None, None, tick_of(side, tick)
    while side.frames < limit:
        now = tick_of(side, tick)
        if start_frames and pending and side.frames >= pending[0]:
            start_ticks.append(now)
        if prev is not None and now - prev > LOAD_JUMP:
            side.pad(())
            return side.frames
        prev = now
        if release is not None and side.frames >= release:
            side.pad(())
            release = None
        if pending and (side.frames >= pending[0] if start_frames else now >= pending[0]):
            pending.pop(0)
            side.pad(('START',))
            release, last_c = side.frames + 8, side.frames
        elif not pending and release is None and (last_c is None or side.frames - last_c >= C_EVERY):
            side.pad(('C',))
            release, last_c = side.frames + 8, side.frames
        side.step()
    return None


def run(saturn, cue, profile, core_so, record, work, vblanks, seed, every=250, tick=None, tol=24):
    """Play one save on both and compare; writes work/diff.json and side-by-side pictures.

    Each side drives the title and Continue menu on its own (dialogue speed differs with CD timing),
    until the save's play-time tick is restored; from there the same seeded inputs and the sync
    points are placed by that tick, which both sides count identically while the game runs."""
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

    # ours: the boot ticks at our START presses, the load, then seeded inputs and sync points by tick
    with agent.start(str(saturn), ['--headless', '--cue', str(cue), '--save', str(work / 'backup.bin'),
                                   '--settings', '-'], str(work / 'ours')) as r:
        ours = OurSide(r)
        start_ticks = []
        our_load = drive_to_load(ours, tick, start_ticks, vblanks, start_frames=(1100, 1308))
        steps = sweep.explore_inputs(1, max(vblanks - (our_load or vblanks), 2), seed)
        presses = R.presses(sweep.input_script(steps))
        place, events, ours_at = R.Place(), [], {}
        for k in range(1, (vblanks - our_load + 1) if our_load else 0):
            for _, buttons in presses.get(k, []):
                ours.pad(buttons)
            at = place.step(tick_of(ours, tick))
            if k in presses:
                events.append((at, 'pad', presses[k][0][1]))
            if k % every == 0:
                events.append((at, 'check', k))
                ours_at[k] = dict(block=ours.read(base, size), frame=ours.frame(), at=at,
                                  wram=ours.read(0x06000000, 0x100000))
            ours.step()
        our_end = tick_of(ours, tick)

    R.WORK_RAM = YABAUSE_WORK_RAM
    core = R.Core(core_so, str(work / 'core-system'), str(cue), options=YABAUSE_OPTIONS,
                  save_dir=str(work / 'core-save'))
    theirs = CoreSide(core)
    core_load = drive_to_load(theirs, tick, start_ticks, vblanks * 3)
    theirs_at, j, place = {}, 0, R.Place()
    events.sort(key=lambda e: (e[0], e[1] != 'pad'))
    while core_load is not None and j < len(events) and theirs.frames < vblanks * 4:
        now = place.step(tick_of(theirs, tick))
        while j < len(events) and events[j][0] <= now:
            _, kind, what = events[j]
            if kind == 'pad':
                theirs.pad(what)
            else:
                theirs_at[what] = dict(block=theirs.read(base, size), frame=theirs.frame(),
                                       frame_no=theirs.frames, wram=theirs.read(0x06000000, 0x100000))
            j += 1
        theirs.step()
    core_end = tick_of(theirs, tick)
    if j < len(events) and theirs.frame() is not None:
        theirs.frame().save_png(str(work / 'core-last.png'))

    points = []
    for k in sorted(ours_at):
        if k not in theirs_at:
            points.append(dict(vblank=k, core_frame=None, unreached=True, state_match=False,
                               map=[ours_at[k]['block'][memory_map.MAP_ID], None]))
            continue
        p = compare_point(k, ours_at[k], theirs_at[k])
        p['wram_bytes_differing'] = sum(a != b for a, b in zip(ours_at[k]['wram'], theirs_at[k]['wram']))
        p['block_changed_since_load'] = ours_at[k]['block'] != ours_at[min(ours_at)]['block']
        a, b = ours_at[k]['frame'], theirs_at[k]['frame']
        if a is not None and b is not None:
            n, worst, pic = R.difference(a, b)
            p.update(dots_differing=n, worst=worst, dots_over_tol=dots_over(a, b, tol))
            pic.save_png(str(work / f'side-{k}.png'))
        points.append(p)
    out = dict(profile=profile, vblanks=vblanks, seed=seed, tick=f'{tick:08X}',
               our_load_vblank=our_load, core_load_frame=core_load, core_frames=theirs.frames,
               our_tick_end=our_end, core_tick_end=core_end,
               expected_map=record['data'][memory_map.MAP_ID],
               note='vblank in points counts from our load',
               summary=summarize([p for p in points if not p.get('unreached')]),
               unreached=sum(1 for p in points if p.get('unreached')), points=points)
    (work / 'diff.json').write_text(json.dumps(out, indent=1) + '\n')
    return out
