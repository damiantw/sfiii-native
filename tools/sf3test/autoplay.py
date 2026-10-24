"""Closed-loop autoplay for SF3 runs: a seeded input driver that reads the game's state each few
VBlanks (map id, battle id, the picture) and picks what to press next, to reach more of the game than
the sweep's blind presses. It drives a side (diff.OurSide over the port's --agent socket, or
diff.CoreSide over Beetle Saturn), so the same policy runs on both; every press is recorded as an
--input script (VBLANK:BUTTONS) whose hash names the run.

Policy, by state:
  town/field (battle id 0): walk bursts in a varied direction, talk/examine (A, C), open and close
    the menus (B, START, a direction, C, then B back out), and C through any dialogue;
  battle (battle id set): per turn, move the cursor a few steps toward the side the enemies are on
    (a direction per battle, turned when nothing changes), C for the command menu, pick Attack /
    Magic / Item / Stay (the menu's four directions), C, a target, C, then C through the animation;
  stuck (the picture unchanged for a while): B out, START, then a random direction and C.
A battle ends when its battle id clears or the map changes; the driver logs each change.
Pure: no game data; the runner needs a built `saturn`, a disc and saves, all outside the repo."""
import hashlib
import random

from . import memory_map

DIRS = ('UP', 'DOWN', 'LEFT', 'RIGHT')
TAP = 6                 # frames a tap is held
GAP = 10                # frames between taps
STUCK_CHECKS = 6        # unchanged picture samples before the escape phrase
SAMPLE = 30             # frames between picture samples


def frame_key(frame):
    """A cheap hash of a frame (every 7th byte), to tell whether the picture moves."""
    rgb = getattr(frame, 'rgb', None) or getattr(frame, 'data', b'') or b''
    return hashlib.sha1(bytes(rgb[::7])).hexdigest()[:12]


def tap(buttons, hold=TAP, gap=GAP):
    return [(tuple(buttons), hold), ((), gap)]


class Policy:
    """Seeded phrase chooser. `next_phrase(state)` -> [(buttons, frames)], state a dict with
    map, battle, stuck (bool), turn (int, battle turns so far)."""

    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.heading = self.rng.choice(DIRS)

    def town(self):
        r = self.rng.random()
        if r < 0.45:                                   # walk, sometimes with a turn
            d = self.rng.choice(DIRS)
            out = [((d,), self.rng.randint(12, 70))]
            if self.rng.random() < 0.4:
                out.append(((self.rng.choice(DIRS),), self.rng.randint(8, 40)))
            return out + [((), 6)]
        if r < 0.70:                                   # talk / examine, then through the dialogue
            out = tap(('A',)) if self.rng.random() < 0.5 else tap(('C',))
            for _ in range(self.rng.randint(2, 6)):
                out += tap(('C',), gap=self.rng.randint(14, 40))
            return out
        if r < 0.88:                                   # a menu: open, move, pick, back out
            out = tap((self.rng.choice(('B', 'START', 'A')),), gap=20)
            for _ in range(self.rng.randint(0, 3)):
                out += tap((self.rng.choice(DIRS),))
            if self.rng.random() < 0.6:
                out += tap(('C',), gap=20) + tap((self.rng.choice(DIRS),)) + tap(('C',), gap=20)
            return out + tap(('B',), gap=16) + tap(('B',), gap=16)
        return tap(('C',), gap=30) * self.rng.randint(1, 4)

    def battle(self, turn):
        out = []
        for _ in range(self.rng.randint(1, 5)):        # move toward the enemies' side
            d = self.heading if self.rng.random() < 0.7 else self.rng.choice(DIRS)
            out += tap((d,), hold=8, gap=8)
        out += tap(('C',), gap=24)                     # command menu
        r = self.rng.random()
        cmd = 'UP' if r < 0.5 else 'LEFT' if r < 0.7 else 'RIGHT' if r < 0.8 else 'DOWN'
        out += tap((cmd,), gap=12) + tap(('C',), gap=24)
        if cmd in ('LEFT', 'RIGHT'):                   # magic/item: first entry, its level, target
            out += tap((self.rng.choice(DIRS),)) + tap(('C',), gap=20)
        for _ in range(self.rng.randint(0, 2)):        # target choice
            out += tap((self.rng.choice(DIRS),))
        out += tap(('C',), gap=30)
        for _ in range(self.rng.randint(3, 7)):        # animation, messages, enemy turns
            out += tap(('C',), gap=self.rng.randint(25, 60))
        if self.rng.random() < 0.15:                   # nothing happened: back out and stay
            out += tap(('B',)) + tap(('B',)) + tap(('C',), gap=20) + tap(('DOWN',)) + tap(('C',), gap=30)
        return out

    def stuck(self):
        self.heading = self.rng.choice([d for d in DIRS if d != self.heading])
        return (tap(('B',), gap=16) * 2 + tap(('START',), gap=30) + tap(('B',), gap=16)
                + [((self.rng.choice(DIRS),), 30), ((), 6)] + tap(('C',), gap=30) + tap(('A',), gap=30))

    def next_phrase(self, state):
        if state.get('stuck'):
            return self.stuck()
        return self.battle(state.get('turn', 0)) if state.get('battle') else self.town()


def play(side, profile, frames, seed, log=None):
    """Drive `side` (already past the save's load) for `frames` frames. Returns dict(presses,
    events, sha1): presses as [(frame offset, buttons)], events the map/battle changes."""
    mm = memory_map.lookup(profile)
    pol = Policy(seed)
    presses, events = [], []
    done, last_key, same, turn = 0, None, 0, 0
    prev = None
    held = None

    def state():
        m = side.read(mm['map_id'], 1)[0]
        b = side.read(mm['battle_id'], 1)[0]
        return m, b

    while done < frames:
        m, b = state()
        if prev is None or (m, b) != prev:
            events.append((done, m, b))
            if log:
                log(f'autoplay {done}: map {m:02X} battle {b:02X}')
            if prev and b and prev[1] != b:
                turn = 0
            prev = (m, b)
        phrase = pol.next_phrase(dict(map=m, battle=b, stuck=same >= STUCK_CHECKS, turn=turn))
        if same >= STUCK_CHECKS:
            same = 0
        if b:
            turn += 1
        for buttons, n in phrase:
            if buttons != held:
                side.pad(buttons)
                presses.append((done, '+'.join(sorted(buttons))))
                held = buttons
            for _ in range(n):
                side.step()
                done += 1
                if done % SAMPLE == 0:
                    k = frame_key(side.frame())
                    same = same + 1 if k == last_key else 0
                    last_key = k
                if done >= frames:
                    break
            if done >= frames:
                break
    script = script_text(presses)
    return dict(presses=presses, events=events, sha1=hashlib.sha1(script.encode()).hexdigest()[:12],
                script=script)


def script_text(presses, offset=0):
    """Presses (relative frames) as an --input script, shifted by `offset` (the load's VBlank)."""
    return ','.join(f'{offset + f}:{b}' for f, b in presses)


def replay(side, presses, frames):
    """Press a recorded autoplay script on another side (Beetle) from its own load on. Each side's
    game runs the same frames from the load, so the script lines up as far as both sides' timing
    agrees (CD reads differ: expect it to drift in loads)."""
    at = {}
    for f, b in presses:
        at.setdefault(f, []).append(b)
    for k in range(frames):
        for b in at.get(k, []):
            side.pad(tuple(x for x in b.split('+') if x))
        side.step()
