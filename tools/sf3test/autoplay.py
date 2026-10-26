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
WATCH_EVERY = 30  # round 19: frames between --watch-fall HP samples


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
        self.pathing, self.blocked, self.blocked_key = False, {}, None
        self.att_miss, self.last_attack = {}, None
        self.explore = 0.0

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


def play(side, profile, frames, seed, log=None, reload=None, prelude=None, assist=None, walker=False, rearm=None,
         idle_over_turns=None, pathing=False, explore=0.0, leader=None, protect=None, watch=None, keep_away=0, avoid=None):
    """Drive `side` (already past the save's load) for `frames` frames. Returns dict(presses,
    events, sha1, resets): presses as [(frame offset, buttons)], events the map/battle changes.
    When the play-time tick falls back (the game went back to its title: a menu's quit, a game
    over), `reload(side)` is called to load the save again, if given; each such reset is logged.
    `assist` (test-only, off unless given): 'party' pokes the force's stats up each battle turn
    (memory_map.assist_writes), 'party+enemy1' also sets every enemy's HP to 1.
    `walker` (round 13): in towns, walk square spirals instead of random bursts and examine/talk
    at each corner; a door is found by walking into it (map id change). (A blocked test by picture
    did not work: town animations change the picture while the player stands at a wall.)
    `rearm` (round 26, story driver): after an 'idle' hand-over to the walker, every `rearm` walker
    legs try one aimed turn again while live enemies remain; a force unit that moves ends the
    hand-over (long battle openings and boss dialogue used to end battles as 'idle' for good).
    `idle_over_turns` overrides IDLE_OVER. `pathing` (round 26) walks battle units along a planned
    path (see plan_step) instead of greedily. `explore` (round 5, search candidates): the share of
    battle turns that aim at a random enemy, hold back or cast instead of the greedy choice.
    `leader` (round 19): the force slot whose fall loses the battle; default the lowest on-field slot
    (Sc3 Ch7 dock fight: a guest in slot 7 sat below Synbios' 31 and was kept back as the leader).
    `watch` (round 19, opt-in): force slots whose HP is sampled every WATCH_EVERY frames; a fall is
    returned in 'fell' as (frame offset, slot) even when the game revives the unit before the end (Sc2
    Ch6 Garvin fight: Medion fell, the church restored him to full HP, and the window end looked fine).
    `keep_away` (round 19, opt-in): the leader and protected units also retreat at full HP whenever a
    live enemy (HP above 1: barrels are 1/1 records) is within that many tiles (Sc3 Ch7 dock fight: Julian
    stood still at 22,26 until the Masked Monk walked up and poisoned him; the poison then drained him).
    `avoid` (round 19, opt-in): (x, y, r): the leader and protected units walk out of the tiles within r
    of (x, y) (Sc2 Ch6 Garvin fight: a scripted blast at ~525.6k (1.003) / ~495.5k (2.000) zeroes every
    unit, both sides, around 33-41,33-45, and Medion started at 36,45 and stayed there)."""
    mm = memory_map.lookup(profile)
    pol = Policy(seed)
    pol.pathing = pathing
    pol.cast = bool(assist)
    pol.explore = explore
    pol.leader = leader
    pol.protect = tuple(protect or ())
    pol.keep_away = keep_away or 0
    pol.avoid = tuple(avoid) if avoid else None
    presses, events = [], []
    fell, watch_base = [], (mm.get('units') or {}).get('force') if watch else None
    done, last_key, same, turn = 0, None, 0, 0
    prev = None
    held = None
    resets = []
    outcomes, last_outcome = [], None
    seen_outcome, seen_at = None, 0
    pokes = 0
    last_tick = None
    heading, blocked, maps_seen, leg = pol.heading, 0, set(), 0
    areas, area = [], None
    idle_over = False
    idle_turns = idle_over_turns or IDLE_OVER
    since_idle = 0

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
            if watch_base and done % WATCH_EVERY == 0:
                for k in watch:
                    a = watch_base + k * memory_map.UNIT_STRIDE + memory_map.UNIT_HP
                    if int.from_bytes(side.read(a, 2), 'big') == 0 and k not in [x for _, x in fell]:
                        fell.append((done, k))
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
                idle_over = False
            prev = (m, b)
        if b and mm.get('units') and assist:
            for addr, data in memory_map.assist_writes(side.read, mm['units'],
                                                       enemy_hp=1 if assist == 'party+enemy1' else None):
                side.write(addr, data)
                pokes += 1
        if b and mm.get('units') and not idle_over:
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
        # area key (round 14): town exits keep the map id (Sc1 church -> square stays 0x2C), but each
        # town area loads its own overlay at AREA_OVERLAY, so a change in its first bytes marks a door
        a_key = hashlib.sha1(side.read(AREA_OVERLAY, 64)).hexdigest()[:8]
        if a_key != area:
            areas.append((done, a_key))
            if log and area is not None:
                log(f'autoplay {done}: area {a_key}')
            if area is not None:
                leg = WALK_LEGS                             # new area: start a new spiral
            area = a_key
        # round 14 (Sc2 Ch1 :01 on sc2-2.000 58271484): after the enemies die the battle map turns into
        # free walking ('Nothing found', the INSPECT ring) while two enemy-table records (max HP 15
        # and 9, never moving) stay live, so 'won' never fires. No force unit moving in the table for
        # IDLE_OVER aimed turns in a row is logged as outcome 'idle' and hands over to the walker
        if b and mm.get('units') and pol.idle >= idle_turns and not idle_over and last_outcome != 'won':
            idle_over = True
            outcomes.append((done, 'idle'))
            if log:
                log(f'autoplay {done}: battle outcome idle (no unit moved for {pol.idle} turns)')
            last_outcome = 'idle'
        free = walker and (not b or (mm.get('units') and last_outcome in ('won', 'idle')))
        if rearm and free and b and idle_over and last_outcome == 'idle':
            since_idle += 1
            if since_idle >= rearm:
                since_idle = 0
                if any(e[4] > 0 for e in memory_map.read_units(side.read, mm['units']['enemies'], mm['units'].get('live'))):
                    pol.idle = 0
                    for buttons, n in aimed_turn(side, mm['units'], pol, press):
                        press(buttons, n)
                    if pol.idle == 0:          # a force unit moved: battle play again
                        idle_over, last_outcome, seen_outcome = False, None, None
                        outcomes.append((done, 'rearmed'))
                        if log:
                            log(f'autoplay {done}: aimed play again (a unit moved)')
                        continue
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
            # talk at every third corner only: dialogue (a priest's save menu) ate most of round 13
            phrase = tap(('C',), gap=30) + tap(('A',), gap=30) + tap(('C',), gap=30) * 4 + tap(('B',), gap=20) \
                if leg % 3 == 0 else tap(('B',), gap=10)
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
    return dict(fell=fell, presses=presses, events=events, resets=resets, outcomes=outcomes, attacks=pol.attacks, casts=pol.casts, pokes=pokes, legs=blocked, areas=areas, sha1=hashlib.sha1(script.encode()).hexdigest()[:12],
                script=script)


WALK_HOLD = 24
IDLE_OVER = 30
AREA_OVERLAY = 0x0605F000   # Sc1 town overlays (X1*) all load here (coverage.tsv module addresses)
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
MISS_PHANTOM = 3
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
    share = n / max(t, 1)
    if share > 0.02 and not flat_blue_rows(w, h, rgb):
        return 0.0                 # round 26: blue water (Sc1 Battle 30's canals), not a window
    return share


def flat_blue_rows(w, h, rgb, run_min=48):
    """Rows of the lower 3/8 holding a run of `run_min` window-blue pixels whose colour steps by
    2 or less: windows are flat colour across, water is textured (none such rows in it)."""
    rows = 0
    for y in range(h * 5 // 8, h, 2):
        row, run, prev = y * w * 3, 0, None
        for x in range(w):
            r, g, b = rgb[row + x * 3], rgb[row + x * 3 + 1], rgb[row + x * 3 + 2]
            ok = b >= 60 and b > r + 35 and b > g + 20 and r < 70
            if ok and prev and abs(b - prev[1]) <= 2 and abs(g - prev[0]) <= 2:
                run += 1
                if run >= run_min:
                    rows += 1
                    break
            else:
                run = 0
            prev = (g, b) if ok else None
    return rows


def hud_up(frame, run_min=48):
    """The unit panel at the top of the picture (name, class, level, HP/MP bars) is up: a battle
    unit is under control. In the free cursor mode (round 5: Sc1 Battle 22, entered by B on the
    unit's start tile) it is gone and the D-pad moves the cursor, not the unit. Rows of the top band
    with a flat window-blue run of `run_min` pixels (textured water has none)."""
    if frame is None:                  # no picture (unit tests): take it as unit control
        return True
    w, h, rgb = frame.width, frame.height, frame.rgb
    rows = 0
    for y in range(h * 3 // 100, h // 5, 2):
        row, run, prev = y * w * 3, 0, None
        for x in range(w // 4, w * 3 // 4):
            r, g, b = rgb[row + x * 3], rgb[row + x * 3 + 1], rgb[row + x * 3 + 2]
            ok = b >= 60 and b > r + 35 and b > g + 20 and r < 70
            if ok and prev and abs(b - prev[1]) <= 2 and abs(g - prev[0]) <= 2:
                run += 1
                if run >= run_min:
                    rows += 1
                    break
            else:
                run = 0
            prev = (g, b) if ok else None
    return rows >= 3


def battle_outcome(rd, units):
    """'won' when no enemy on the field has HP left, 'lost' when no force unit has, else None."""
    enemies = memory_map.read_units(rd, units['enemies'], units.get('live'))
    force = memory_map.read_units(rd, units['force'], units.get('live'))
    if not any(e[4] > 0 for e in enemies):      # a defeated enemy leaves the field (flag 0x40 clears)
        return 'won'
    if not any(f[4] > 0 for f in force):
        return 'lost'
    return None


def next_to(p, live):
    """True when a live enemy stands on a tile next to `p` (walls and drops are not in the unit
    tables, so a unit can be stuck with free-looking tiles around it)."""
    return any(abs(p[0] - e[0]) + abs(p[1] - e[1]) == 1 for e in live)


STEP = {'RIGHT': (1, 0), 'LEFT': (-1, 0), 'UP': (0, 1), 'DOWN': (0, -1)}


def step_of(p, d):
    return (p[0] + STEP[d][0], p[1] + STEP[d][1])


def plan_step(p, live, occupied, blocked, size=64, limit=6000, passable=frozenset()):
    """First direction of a shortest path from `p` to a tile next to a live enemy, over a
    size x size grid where unseen tiles are taken as open (optimistic planning: a failed step marks
    its edge, `blocked` counts failures per edge; two failures close it, one makes it dear).
    Tiles other units hold are closed, except `passable` ones (the unit's own force: a unit walks
    through its allies but cannot stop on one). None when no tile is reachable."""
    import heapq
    goals = {(x + dx, y + dy) for x, y in live for dx, dy in STEP.values()} - occupied - set(passable)
    if not goals:
        return None
    h = lambda q: min(abs(q[0] - g[0]) + abs(q[1] - g[1]) for g in goals)
    heap, best, first, n = [(h(p), 0, p)], {p: 0}, {p: None}, 0
    while heap and n < limit:
        f, g, q = heapq.heappop(heap)
        n += 1
        if q in goals:
            return first[q]
        if g > best.get(q, 1 << 30):
            continue
        for d in STEP:
            r = step_of(q, d)
            if not (0 <= r[0] < size and 0 <= r[1] < size) or (r in occupied and r not in passable):
                continue
            fails = blocked.get((q, r), 0)
            if fails >= 2:
                continue
            ng = g + 1 + 6 * fails
            if ng < best.get(r, 1 << 30):
                best[r] = ng
                first[r] = first[q] or d
                heapq.heappush(heap, (ng + h(r), ng, r))
    return None


LEADER_SAFE = 0.6


def retreat_path(p, live, allies, blocked, reach=5, size=64):
    """Directions from `p` to the free tile within `reach` steps farthest from every live enemy
    (allies are walked through but not ended on, enemies and known-blocked edges are not
    crossed); [] when no tile is farther than `p` itself."""
    def dist(q):
        return min(abs(q[0] - e[0]) + abs(q[1] - e[1]) for e in live) if live else 0
    enemies = set(live)
    best, best_key = [], (dist(p), 0)
    seen = {p: []}
    frontier = [p]
    for depth in range(1, reach + 1):
        nxt = []
        for q in frontier:
            for d in DIRS:
                r = step_of(q, d)
                if r in seen or r in enemies or blocked.get((q, r)) or not (0 <= r[0] < size and 0 <= r[1] < size):
                    continue
                seen[r] = seen[q] + [d]
                nxt.append(r)
                if r not in allies and (dist(r), -depth) > best_key:
                    best, best_key = seen[r], (dist(r), -depth)
        frontier = nxt
    return best


def is_hurt(read, table, slot, share):
    """True when force record `slot` has less than `share` of its max HP."""
    e = read(table + slot * memory_map.UNIT_STRIDE, memory_map.UNIT_STRIDE)
    hp = int.from_bytes(e[memory_map.UNIT_HP:memory_map.UNIT_HP + 2], 'big')
    top = int.from_bytes(e[memory_map.UNIT_MAX_HP:memory_map.UNIT_MAX_HP + 2], 'big')
    return top > 0 and hp < share * top


def aimed_turn(side, units, pol, press):
    """Closed-loop battle turn. Probe which force unit is under control (tap toward the enemies,
    see whose x/y moved), walk it step by step toward the nearest live enemy (checking the unit
    table after each step, turning to the other axis when blocked), open the command ring, Attack
    when next to an enemy, else Hold. Returns the trailing phrase (messages, enemy turns)."""
    rd = side.read

    def pos():
        return {k: (x, y) for k, x, y, f, hp in memory_map.read_units(rd, units['force'], units.get('live'))}

    enemies = memory_map.read_units(rd, units['enemies'], units.get('live'))
    key = tuple(sorted(e[0] for e in enemies))           # a new battle (enemy roster): forget edges
    if key != pol.blocked_key:
        pol.blocked, pol.blocked_key, pol.phantoms = {}, key, set()
        pol.att_miss, pol.last_attack = {}, None
    phantoms = getattr(pol, 'phantoms', set())
    hp_of = {k: hp for k, x, y, f, hp in enemies}
    la = getattr(pol, 'last_attack', None)
    if la:
        # round 19 (Sc3 Ch7 dock fight): stale enemy records left from the harbour fight sit next to
        # force units; Attack on one finds no target and the turn never ends, so every candidate
        # replayed the same loop. An attack that leaves the adjacent records' HP unchanged MISS_PHANTOM
        # times marks them as phantoms for this battle
        keys, hp0 = la
        pol.last_attack = None
        if sum(hp_of.get(k, 0) for k in keys) == hp0:
            pol.att_miss[keys] = pol.att_miss.get(keys, 0) + 1
            if pol.att_miss[keys] >= MISS_PHANTOM:
                pol.phantoms = phantoms = phantoms | set(keys)
        else:
            pol.att_miss.pop(keys, None)
    live = [(x, y) for k, x, y, f, hp in enemies if hp > 0 and k not in phantoms]
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
        moved = [k for k in before if k in now and now[k] != before[k]]   # a unit that left the table did not move
        if moved:
            break
    if not moved and not hud_up(side.frame()) and getattr(pol, 'cursor_b', 0) < 2:
        # round 5 (Sc1 Battle 22 search): nothing moved and no unit panel: the free cursor (B on
        # the start tile enters it; C there opens the field menu or a member's status, which the
        # menu branch above backed out of by B into the cursor again), so the turn sat for 6k
        # VBlanks with the leader next to an enemy. B puts the cursor back on the unit
        pol.cursor_b = getattr(pol, 'cursor_b', 0) + 1
        pol.recentred = getattr(pol, 'recentred', 0) + 1
        return tap(('B',), gap=60)
    pol.cursor_b = 0
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
        if pol.idle % 4 == 3:
            # the unit under control cannot move (boxed in by its own force on a bridge or in a
            # corridor), so the probe never finds it: end its turn with Hold (C, ring DOWN, C)
            pol.holds = getattr(pol, 'holds', 0) + 1
            return [(('C',), 6), ((), 30), ((RING['hold'],), 6), ((), 14), (('C',), 6), ((), 40)] + tap(('C',), gap=40) * 2
        return tap(('B',), gap=16) if pol.idle % 3 == 0 else tap(('C',), gap=30)
    pol.idle = 0
    me = moved[0]
    steps = 1
    # search candidates (round 5): some turns aim at a random enemy, hold back, or cast
    goal, hold_back, cast_pick = live, False, False
    if pol.explore and pol.rng.random() < pol.explore:
        r = pol.rng.random()
        if r < 0.5:
            goal = [pol.rng.choice(live)]
        elif r < 0.75:
            hold_back = True
        else:
            cast_pick = True
        pol.explored = getattr(pol, 'explored', 0) + 1

    def dist(p):
        return min(abs(p[0] - e[0]) + abs(p[1] - e[1]) for e in live)

    # the leader (the force's first on-field slot) losing all HP loses the battle (round 3: Sc1
    # Battle 22 lost with Synbios at 18 HP walking up to the boss). Round 4 (fresh :25 run): the
    # leader walked to the front of the Battle 22 bridge at full HP, stood between two enemies and
    # fell 30k VBlanks later. So the leader never advances: B returns the probe step and it only
    # attacks what is already in reach; below LEADER_SAFE of max HP it walks away from the
    # enemies (through teammates, to a free tile)
    cautious = False
    lead = pol.leader if getattr(pol, 'leader', None) in before else min(before)
    if me == lead or me in (getattr(pol, 'protect', None) or ()):
        press(('B',), 6)
        press((), 20)
        if not hud_up(side.frame()):
            # round 19 (Sc3 Ch7 dock fight, Julian at 22,26): this B put the unit back and also left
            # the free cursor up (no unit panel), so the retreat steps moved the cursor and the C
            # presses opened members' status panels, every turn for 30k VBlanks. A second B puts
            # the cursor back on the unit (its panel returns) and the steps move the unit again
            press(('B',), 6)
            press((), 40)
            pol.recentred = getattr(pol, 'recentred', 0) + 1
        cautious = True
        pol.cautious = getattr(pol, 'cautious', 0) + 1
        now = pos()
        ka = getattr(pol, 'keep_away', 0)
        threats = [(x, y) for k, x, y, f, hp in enemies if hp > 1 and k not in phantoms]
        near_threat = bool(ka and me in now and threats and
                           min(abs(now[me][0] - e[0]) + abs(now[me][1] - e[1]) for e in threats) <= ka)
        av = getattr(pol, 'avoid', None)
        in_zone = bool(av and me in now and abs(now[me][0] - av[0]) + abs(now[me][1] - av[1]) <= av[2])
        if me in now and (in_zone or near_threat or is_hurt(rd, units['force'], me, LEADER_SAFE)):
            path = retreat_path(now[me], [av[:2]] if in_zone else live, {v for k, v in now.items() if k != me}, pol.blocked,
                                reach=8 if in_zone else 5)
            for i, d in enumerate(path):
                q = pos().get(me)
                if q is None:
                    break
                press((d,), 8)
                press((), 10)
                if pos().get(me, q) == q:          # a wall early on; later it is the move range's end
                    if i < 2:
                        pol.blocked[(q, step_of(q, d))] = 1
                    break
                pol.retreats = getattr(pol, 'retreats', 0) + 1
    if hold_back and not cautious:
        press(('B',), 6)
        press((), 20)
    if pol.pathing and not cautious and not hold_back:
        fails = 0
        for _ in range(16):
            now = pos()
            if me not in now:                      # the mover left the roster mid-turn (fell, withdrew)
                break
            p = now[me]
            if dist(p) <= 1 or fails >= 8 or (goal is not live and min(abs(p[0] - e[0]) + abs(p[1] - e[1]) for e in goal) <= 1):
                break
            allies = {v for k, v in now.items() if k != me}
            # allies are walked through (round 2: a force packed on the Battle 22 bridge or in the
            # Sc3 final room had no path with allies as walls, so every unit held for 120k VBlanks)
            d = plan_step(p, goal, allies | set(live), pol.blocked, passable=allies)
            if d is None:
                break
            press((d,), 8)
            press((), 10)
            if pos().get(me, p) != p:
                steps += 1
                pol.blocked.pop((p, step_of(p, d)), None)
            else:                                  # wall, cliff or the end of the move range
                q = step_of(p, d)                  # early in the move it is not the range's end
                pol.blocked[(p, q)] = pol.blocked.get((p, q), 0) + (2 if steps <= 2 else 1)
                fails += 1
    for _ in range(0 if pol.pathing or cautious or hold_back else 10):
        p = pos().get(me)
        if p is None or dist(p) <= 1:
            break
        tx, ty = min(live, key=lambda e: abs(e[0] - p[0]) + abs(e[1] - p[1]))
        dx = ('RIGHT' if tx > p[0] else 'LEFT') if tx != p[0] else None
        dy = ('UP' if ty > p[1] else 'DOWN') if ty != p[1] else None
        order = [d for d in ((dx, dy) if abs(tx - p[0]) >= abs(ty - p[1]) else (dy, dx)) if d]
        went = False
        for d in order:
            press((d,), 8)
            press((), 10)
            if pos().get(me, p) != p:
                went, steps = True, steps + 1
                break
        if not went:                               # blocked or out of movement range
            break
    if me not in pos():                            # gone mid-move: close whatever the game shows
        return tap(('C',), gap=30)
    for _ in range(4):                             # never end on a tile another force unit holds
        now = pos()
        if me not in now:
            return tap(('C',), gap=30)
        if now[me] not in [v for k, v in now.items() if k != me]:
            break
        p = now[me]
        for d in ('LEFT', 'UP', 'DOWN', 'RIGHT'):
            press((d,), 8)
            press((), 10)
            q = pos()
            if me not in q or (q[me] != p and q[me] not in [v for k, v in q.items() if k != me]):
                break
    now = pos()
    ghost = [k for k, x, y, f, hp in enemies if hp > 0 and me in now and (x, y) == now[me]]
    if ghost:
        # standing on a live enemy record's tile (round 4: Sc3 Ch7:12 record 8 at 11,51 is walked
        # over, so it is not on the field): stop aiming at it for the rest of this battle
        pol.phantoms = phantoms | set(ghost)
        live[:] = [(x, y) for k, x, y, f, hp in enemies if hp > 0 and k not in pol.phantoms]
    if not live:
        press(('B',), 6)
        press((), 20)
        return [(('C',), 6), ((), 30), ((RING['hold'],), 6), ((), 14), (('C',), 6), ((), 40)] + tap(('C',), gap=40) * 2
    if me in now and (ghost or now[me] in [v for k, v in now.items() if k != me]):
        # still on a teammate's tile (round 4: Sc1 Battle 22 bridge, a unit probed onto a packed
        # line wandered over teammates for 60k VBlanks; C does nothing there) or a phantom
        # enemy's: B puts it back on its start tile, which is free, and the turn ends from there
        press(('B',), 6)
        press((), 20)
        pol.returns = getattr(pol, 'returns', 0) + 1
    if me not in pos():
        return tap(('C',), gap=30)
    adjacent = dist(pos()[me]) <= 1
    press(('C',), 6)
    press((), 30)                                  # command ring, cursor on Hold
    near = me in pos() and dist(pos()[me]) <= 2                    # first-level spells reach 2 tiles (Blaze, Heal)
    cast_now = (near and pol.cast and pol.tried.get(me, 0) % 2 == 0) or (near and cast_pick)
    # round 19 (Sc3 Ch7 dock fight, search v55): the leader and protected units never cast. Julian's
    # first spell is Egress, and a random cast took the force out of the fight to the church, which
    # the battle-over check took for a win (the battle byte went to the field and a story bit was set)
    cast_now = cast_now and not cautious
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
        mp = pos().get(me)
        keys = tuple(sorted(k for k, x, y, f, hp in enemies if hp > 0 and k not in getattr(pol, 'phantoms', set()) and mp
                            and abs(x - mp[0]) + abs(y - mp[1]) <= 1))
        if keys:
            pol.last_attack = (keys, sum(hp_of.get(k, 0) for k in keys))
        press((RING['attack'],), 6)
        press((), 14)
        press(('C',), 6)
        press((), 30)                              # target choice, nearest enemy highlighted
        press(('C',), 6)
        press((), 40)
        pol.attacks += 1
    else:
        # not next to an enemy by the unit table: take the ring's own choice. The game opens the
        # ring on Attack when something is in reach and on Hold otherwise (probe, round 3), and a
        # large enemy (the Sc3 Ch7:12 boss, max HP 2400) covers more tiles than its record's x/y,
        # so units standing next to it never attacked. C confirms the default (Hold ends the turn;
        # Attack opens the target choice, the next C confirms the highlighted target).
        press(('C',), 6)
        press((), 30)
        press(('C',), 6)
        press((), 40)
        pol.defaults = getattr(pol, 'defaults', 0) + 1
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
