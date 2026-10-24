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
        self.idle = 0
        self.attacks = 0
        self.cast, self.casts, self.tried = False, 0, {}

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

    def aim(self, force, enemies, active):
        """Battle turn aimed at the nearest live enemy: walk the active unit (a force slot, found by
        which record moved after a probe tap) toward it, attack when next to it, else stay."""
        me = next(((x, y) for k, x, y, f, hp in force if k == active), None)
        live = [(x, y) for k, x, y, f, hp in enemies if hp > 0]
        if me is None or not live:
            return tap(('C',), gap=30) * 3
        tx, ty = min(live, key=lambda e: abs(e[0] - me[0]) + abs(e[1] - me[1]))
        x, y = me
        out = []
        for _ in range(8):                             # greedy steps, stop next to the target
            if abs(tx - x) + abs(ty - y) <= 1:
                break
            if abs(tx - x) >= abs(ty - y):
                d, x = ('RIGHT', x + 1) if tx > x else ('LEFT', x - 1)
            else:
                d, y = ('UP', y + 1) if ty > y else ('DOWN', y - 1)
            out += tap((d,), hold=8, gap=10)
        out += tap(('C',), gap=24)                     # command menu
        if abs(tx - x) + abs(ty - y) <= 1:
            out += tap(('UP',), gap=12) + tap(('C',), gap=24) + tap(('C',), gap=40)   # attack, target
        else:
            out += tap(('DOWN',), gap=12) + tap(('C',), gap=30)                       # stay
        for _ in range(5):                             # animation, messages, enemy turns
            out += tap(('C',), gap=40)
        return out

    def stuck(self):
        self.heading = self.rng.choice([d for d in DIRS if d != self.heading])
        return (tap(('B',), gap=16) * 2 + tap(('START',), gap=30) + tap(('B',), gap=16)
                + [((self.rng.choice(DIRS),), 30), ((), 6)] + tap(('C',), gap=30) + tap(('A',), gap=30))

    def next_phrase(self, state):
        if state.get('stuck'):
            return self.stuck()
        return self.battle(state.get('turn', 0)) if state.get('battle') else self.town()


def play(side, profile, frames, seed, log=None, reload=None, prelude=None, assist=None, walker=False):
    """Drive `side` (already past the save's load) for `frames` frames. Returns dict(presses,
    events, sha1, resets): presses as [(frame offset, buttons)], events the map/battle changes.
    When the play-time tick falls back (the game went back to its title: a menu's quit, a game
    over), `reload(side)` is called to load the save again, if given; each such reset is logged.
    `assist` (test-only, off unless given): 'party' pokes the force's stats up each battle turn
    (memory_map.assist_writes), 'party+enemy1' also sets every enemy's HP to 1.
    `walker` (round 13): in towns, walk square spirals instead of random bursts and examine/talk
    at each corner; a door is found by walking into it (map id change). (A blocked test by picture
    did not work: town animations change the picture while the player stands at a wall.)"""
    mm = memory_map.lookup(profile)
    pol = Policy(seed)
    pol.cast = bool(assist)
    presses, events = [], []
    done, last_key, same, turn = 0, None, 0, 0
    prev = None
    held = None
    resets = []
    outcomes, last_outcome = [], None
    seen_outcome, seen_at = None, 0
    pokes = 0
    last_tick = None
    heading, blocked, maps_seen, leg = pol.heading, 0, set(), 0

    def state():
        m = side.read(mm['map_id'], 1)[0]
        b = side.read(mm['battle_id'], 1)[0]
        return m, b

    def press(buttons, n):
        nonlocal held, done, same, last_key
        if done >= frames:
            return
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

    for buttons, n in prelude_phrase(PRELUDES[prelude]) if prelude else ():
        press(buttons, n)
    want = memory_map.PAYLOAD_SIZE[mm['scenario']] - 8
    size_ok = side.read(mm['state_base'], 4) == want.to_bytes(4, 'big')
    while done < frames:
        t = int.from_bytes(side.read(mm['tick'], 4), 'big')
        # the size word alone is not enough: a battle reuses the block's head (Sc1 Battle 1 lost
        # it 90 frames in while still playing), so the title also needs map and battle id 0
        lost = (size_ok and side.read(mm['state_base'], 4) != want.to_bytes(4, 'big')
                and side.read(mm['map_id'], 1)[0] == 0 and side.read(mm['battle_id'], 1)[0] == 0)
        if lost or (last_tick is not None and t + 100 < last_tick):
            resets.append(done)
            events.append((done, -1, -1))
            if log:
                log(f'autoplay {done}: back at the title (tick {last_tick} -> {t}, state block lost {lost})')
            if reload:
                start = side.frames
                side.pad(())
                held = ()
                reload(side)
                done += side.frames - start
                prev = None
                t = int.from_bytes(side.read(mm['tick'], 4), 'big')
        last_tick = t
        m, b = state()
        if prev is None or (m, b) != prev:
            events.append((done, m, b))
            if log:
                log(f'autoplay {done}: map {m:02X} battle {b:02X}')
            if prev and b and prev[1] != b:
                turn = 0
            prev = (m, b)
        if b and mm.get('units') and assist:
            for addr, data in memory_map.assist_writes(side.read, mm['units'],
                                                       enemy_hp=1 if assist == 'party+enemy1' else None):
                side.write(addr, data)
                pokes += 1
        if b and mm.get('units'):
            # debounced: the on-field flag clears for a while in attack scenes (round 11), so an
            # outcome counts once it has read the same for OUTCOME_HOLD frames
            raw_oc = battle_outcome(side.read, mm['units'])
            if raw_oc != seen_outcome:
                seen_outcome, seen_at = raw_oc, done
            oc = seen_outcome if done - seen_at >= OUTCOME_HOLD or seen_outcome is None else last_outcome
            if oc != last_outcome:
                outcomes.append((done, oc))
                if log:
                    log(f'autoplay {done}: battle outcome {oc}')
                last_outcome = oc
        # after a won battle the map stays a battle map (battle id set) with free walking
        # (Sc1 Central Saraband after Battle 1): the walker takes over once no enemy is alive
        free = walker and (not b or (mm.get('units') and last_outcome == 'won'))
        if b and mm.get('units') and same < STUCK_CHECKS and not free:
            phrase = aimed_turn(side, mm['units'], pol, press)
        elif free:
            # a square spiral out from where the town starts: legs of 1, 1, 2, 2, 3, 3 ... x
            # WALK_HOLD frames turning clockwise, starting again (with a random first heading)
            # after WALK_LEGS legs or on a map change; examine and talk at the end of each leg (C,
            # A, then C through any dialogue, which takes a shop or bar's first choice)
            if m not in maps_seen or leg >= WALK_LEGS:
                maps_seen.add(m)
                leg, heading = 0, pol.rng.choice(CLOCKWISE)
            press((heading,), WALK_HOLD * (1 + leg // 2))
            leg += 1
            blocked += 1
            heading = CLOCKWISE[(CLOCKWISE.index(heading) + 1) % 4]
            phrase = tap(('C',), gap=30) + tap(('A',), gap=30) + tap(('C',), gap=30) * 4 + tap(('B',), gap=20)
        else:
            phrase = pol.next_phrase(dict(map=m, battle=b, stuck=same >= STUCK_CHECKS, turn=turn))
        if same >= STUCK_CHECKS:
            same = 0
        if b:
            turn += 1
        for buttons, n in phrase:
            press(buttons, n)
            if done >= frames:
                break
    script = script_text(presses)
    return dict(presses=presses, events=events, resets=resets, outcomes=outcomes, attacks=pol.attacks, casts=pol.casts, pokes=pokes, legs=blocked, sha1=hashlib.sha1(script.encode()).hexdigest()[:12],
                script=script)


WALK_HOLD = 24
WALK_LEGS = 24
CLOCKWISE = ('UP', 'RIGHT', 'DOWN', 'LEFT')


# Scripted input segments run before autoplay (round 10, sc1-usa b92d515b, black-box walks):
# 'BUTTONS*hold' = hold for that many frames then release for 10, 'wN' = wait N frames.
PRELUDES = {
    # Sc1 Ch1:01 (save record 01, church map 0x2C): down the aisle and out of the door to the
    # town square in front of the church (map id stays 0x2C), about 900 frames
    'sc1-church-exit': 'w60,DOWN*60,DOWN*60,RIGHT*90,DOWN*90,DOWN*90,RIGHT*90,DOWN*90,w120',
}


def prelude_phrase(text):
    out = []
    for c in text.split(','):
        if c.startswith('w'):
            out.append(((), int(c[1:])))
        else:
            b, _, k = c.partition('*')
            out += [(tuple(b.split('+')), int(k or 6)), ((), 10)]
    return out


STEP = {'RIGHT': (1, 0), 'LEFT': (-1, 0), 'UP': (0, 1), 'DOWN': (0, -1)}
# Sc1 battle command ring (round 10/11, binary sc1-usa b92d515b): C opens it, after a step or
# without one (round 11: a boxed-in unit's C opened it and Attack hit); cursor starts on Hold;
# UP = Attack, LEFT = Magic, RIGHT = Item, DOWN = Hold. Attack with no one in reach says
# 'There is no target...'; with a target, the next C picks the highlighted enemy and the next C confirms.
OUTCOME_HOLD = 600
RING = {'attack': 'UP', 'magic': 'LEFT', 'item': 'RIGHT', 'hold': 'DOWN'}


def panel_share(frame):
    """Share of the lower 3/8 of the picture covered by the game's dark-blue window colour (menus,
    the command ring's label, messages); about 0 on an open battle field. A black-box picture test."""
    w, h, rgb = frame.width, frame.height, frame.rgb
    n = t = 0
    for y in range(h * 5 // 8, h, 4):
        row = y * w * 3
        for x in range(0, w, 4):
            r, g, b = rgb[row + x * 3], rgb[row + x * 3 + 1], rgb[row + x * 3 + 2]
            t += 1
            n += b >= 60 and b > r + 35 and b > g + 20 and r < 70
    return n / max(t, 1)


def battle_outcome(rd, units):
    """'won' when no enemy on the field has HP left, 'lost' when no force unit has, else None."""
    enemies = memory_map.read_units(rd, units['enemies'])
    force = memory_map.read_units(rd, units['force'])
    if not any(e[4] > 0 for e in enemies):      # a defeated enemy leaves the field (flag 0x40 clears)
        return 'won'
    if not any(f[4] > 0 for f in force):
        return 'lost'
    return None


def next_to(p, live):
    """True when a live enemy stands on a tile next to `p` (walls and drops are not in the unit
    tables, so a unit can be stuck with free-looking tiles around it)."""
    return any(abs(p[0] - e[0]) + abs(p[1] - e[1]) == 1 for e in live)


def aimed_turn(side, units, pol, press):
    """Closed-loop battle turn. Probe which force unit is under control (tap toward the enemies,
    see whose x/y moved), walk it step by step toward the nearest live enemy (checking the unit
    table after each step, turning to the other axis when blocked), open the command ring, Attack
    when next to an enemy, else Hold. Returns the trailing phrase (messages, enemy turns)."""
    rd = side.read

    def pos():
        return {k: (x, y) for k, x, y, f, hp in memory_map.read_units(rd, units['force'])}

    enemies = memory_map.read_units(rd, units['enemies'])
    live = [(x, y) for k, x, y, f, hp in enemies if hp > 0]
    if not live:
        return tap(('C',), gap=30) * 4
    if panel_share(side.frame()) > 0.02:          # a menu or message is up: back out (B), or C
        pol.idle += 1
        if pol.idle % 5 == 0:
            return tap(('C',), gap=30) * 6
        return tap(('C',), gap=30) if pol.idle % 3 == 0 else tap(('B',), gap=20)
    before = pos()
    cx = sum(e[0] for e in live) / len(live)
    lead = next(iter(before.values()), (0, 0))
    moved = []
    for d in (('LEFT', 'RIGHT') if cx < lead[0] else ('RIGHT', 'LEFT')) + ('UP', 'DOWN'):
        press((d,), 8)
        press((), 10)
        now = pos()
        moved = [k for k in before if now.get(k) != before[k]]
        if moved:
            break
    if not moved:
        # Nothing moved: a message (C), a menu left open (B), or (round 11) a unit that cannot
        # step (enemies, teammates or terrain all round). The ring opens on C without a step too, so
        # every other idle turn tries Attack in place (C, UP, C, C); with no one in reach the
        # game says so and the trailing C closes it.
        pol.idle += 1
        if pol.idle % 5 == 0:
            # a prompt that wants a choice (round 12: 'What will you drop for the Medical Herb?'
            # when a full inventory gets an item): C through it, nothing in between to back out
            return tap(('C',), gap=30) * 6
        if pol.idle % 2 == 0 and any(next_to(p, live) for p in before.values()):
            pol.attacks += 1
            return [(('C',), 6), ((), 30), ((RING['attack'],), 6), ((), 14), (('C',), 6), ((), 30),
                    (('C',), 6), ((), 40)] + tap(('C',), gap=40) * 4
        return tap(('B',), gap=16) if pol.idle % 3 == 0 else tap(('C',), gap=30)
    pol.idle = 0
    me = moved[0]
    steps = 1

    def dist(p):
        return min(abs(p[0] - e[0]) + abs(p[1] - e[1]) for e in live)

    for _ in range(10):
        p = pos()[me]
        if dist(p) <= 1:
            break
        tx, ty = min(live, key=lambda e: abs(e[0] - p[0]) + abs(e[1] - p[1]))
        dx = ('RIGHT' if tx > p[0] else 'LEFT') if tx != p[0] else None
        dy = ('UP' if ty > p[1] else 'DOWN') if ty != p[1] else None
        order = [d for d in ((dx, dy) if abs(tx - p[0]) >= abs(ty - p[1]) else (dy, dx)) if d]
        went = False
        for d in order:
            press((d,), 8)
            press((), 10)
            if pos()[me] != p:
                went, steps = True, steps + 1
                break
        if not went:                               # blocked or out of movement range
            break
    for _ in range(4):                             # never end on a tile another force unit holds
        now = pos()
        if now[me] not in [v for k, v in now.items() if k != me]:
            break
        p = now[me]
        for d in ('LEFT', 'UP', 'DOWN', 'RIGHT'):
            press((d,), 8)
            press((), 10)
            q = pos()
            if q[me] != p and q[me] not in [v for k, v in q.items() if k != me]:
                break
    adjacent = dist(pos()[me]) <= 1
    press(('C',), 6)
    press((), 30)                                  # command ring, cursor on Hold
    near = dist(pos()[me]) <= 2                    # first-level spells reach 2 tiles (Blaze, Heal)
    cast_now = near and pol.cast and pol.tried.get(me, 0) % 2 == 0
    if near and pol.cast:
        pol.tried[me] = pol.tried.get(me, 0) + 1
    if cast_now:
        # --assist runs: each unit's turns alternate Magic and Attack, Magic first (first spell, its first level, the
        # highlighted target, confirm); a unit with no spells gets a message the trailing C closes
        press((RING['magic'],), 6)
        press((), 14)
        for _ in range(4):
            press(('C',), 6)
            press((), 30)
        pol.attacks += 1
        pol.casts += 1
    elif adjacent:
        press((RING['attack'],), 6)
        press((), 14)
        press(('C',), 6)
        press((), 30)                              # target choice, nearest enemy highlighted
        press(('C',), 6)
        press((), 40)
        pol.attacks += 1
    else:
        press((RING['hold'],), 6)
        press((), 14)
        press(('C',), 6)
        press((), 30)
    return tap(('C',), gap=40) * 4


def reload_menu(side, profile, limit):
    """Back at the title: START and C in turn every 80 frames until the state block holds a loaded
    save again (its size word is right for 120 frames), or `limit` frames."""
    mm = memory_map.lookup(profile)
    want = (memory_map.PAYLOAD_SIZE[mm['scenario']] - 8).to_bytes(4, 'big')
    good, n = 0, 0
    for k in range(limit):
        good = good + 1 if side.read(mm['state_base'], 4) == want else 0
        if good >= 120:
            side.pad(())
            return True
        if k % 80 == 0:
            n += 1
            side.pad(('START',) if n % 2 else ('C',))
        elif k % 80 == 8:
            side.pad(())
        side.step()
    side.pad(())
    return False


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
