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
from . import tactics

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
        self.heal, self.heal_at, self.heal_fail, self.heal_check, self.sigs = (), 0.6, {}, None, {}
        self.heal_item = ()
        self.leader_attack, self.hit = None, {}
        self.tactics, self.still, self.root_epos, self.tac_check, self.tac_fail = {}, {}, None, None, {}

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
         idle_over_turns=None, pathing=False, explore=0.0, leader=None, protect=None, watch=None, keep_away=0, avoid=None, focus=None, heal=None, heal_at=None, escort=None, heal_item=None, leader_attack=None, tactics=None, root_epos=None):
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
    unit, both sides, around 33-41,33-45, and Medion started at 36,45 and stayed there).
    `focus` (round 19, opt-in): enemy slots the other units path to first while alive (Sc3 Ch7 dock fight:
    the Masked Monk, enemy 1, was never attacked and poisoned Julian, then Synbios).
    `leader_attack` (round 27, opt-in, with pathing): a share S; on its turn the leader walks to and
    attacks an enemy it can finish (HP at most its best hit) or one under S of max HP, within
    LEADER_REACH steps and never through the `avoid` zone, instead of only striking what is in reach.
    `tactics` (round 29, opt-in): dict(hold_until=N, ranged, casters, healers, item_attack slots), see
    aimed_turn and tactics.py; `root_epos` {enemy slot: (x, y)} at the search root marks enemies that
    have not moved since as stationary (the --hold-until threats, the --protect heavy hitters)."""
    mm = memory_map.lookup(profile)
    pol = Policy(seed)
    pol.pathing = pathing
    pol.cast = bool(assist)
    pol.explore = explore
    pol.leader = leader
    pol.protect = tuple(protect or ())
    pol.keep_away = keep_away or 0
    pol.avoid = tuple(avoid) if avoid else None
    pol.focus = tuple(focus or ())
    pol.heal, pol.heal_at, pol.heal_fail, pol.heal_check = tuple(heal or ()), heal_at or LEADER_SAFE, {}, None
    pol.heal_item = tuple(heal_item or ())
    pol.leader_attack = leader_attack
    pol.tactics = dict(tactics or {})
    pol.root_epos = root_epos
    pol.escort = escort
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
        if not b and memory_map.in_battle(side.read, mm):
            b = 0xFF          # round 27: Sc2 V1.003 map 0x49 fights with battle id 0 (memory_map.BATTLE_ACTIVE)
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
    # round 27 (Sc2 v1.003 war-machine fight): the panel sits lower, beside the land-effect box,
    # with only 4 flat rows (y 18-21 of 240) above its name; every other row from 3% to 20% missed
    # them, so the panel read as gone: the probe and the leader's turn pressed B into the free
    # cursor and nobody moved for 15k VBlanks until the blast. Every row to a quarter, 4 rows
    rows = 0
    for y in range(h * 3 // 100, h // 4):
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
    return rows >= 4


ESCORT_R = 4                          # --escort: enemies this close to the escorted unit are the targets
HEAL_WALK = 6                         # --heal-item: a hurt ward this close draws the carrier to it
ESCORT_GUARD = 8                      # --escort: units ring the escort while an enemy is this close
SIGS = {}                             # force table -> {slot: panel name bits}, kept across play() calls
SIG_TOL = 20                          # name-line pixels two looks at one unit's panel may differ by


def panel_sig(frame, run_min=48):
    """(bits, enemy) for the unit panel at the top of the picture, or None when none is up. bits is
    the white text of the name line (14 rows by 88 pixels from the panel's left edge), the same for
    one unit from turn to turn (the HP digits sit below it); enemy is a red name (enemy panels).
    Round 27 (Sc3 Ch7 dock fight): Gracia stood boxed in at 20,26 all fight, so the probe never saw
    her move and her turns never reached the cautious or --heal branch; her panel names her."""
    if frame is None:
        return None
    w, h, rgb = frame.width, frame.height, frame.rgb

    def px(x, y):
        i = (y * w + x) * 3
        return rgb[i], rgb[i + 1], rgb[i + 2]

    def blue(r, g, b):
        return b >= 60 and b > r + 35 and b > g + 20 and r < 70

    for y in range(h * 3 // 100, h // 4):
        run, prev = 0, None
        for x in range(w // 4, w * 7 // 8):
            r, g, b = px(x, y)
            ok = blue(r, g, b)
            if ok and prev and abs(b - prev[1]) <= 2 and abs(g - prev[0]) <= 2:
                run += 1
                if run >= run_min:
                    x0 = x - run
                    while x0 > 0 and blue(*px(x0 - 1, y)):
                        x0 -= 1
                    if y + 22 > h or x0 + 90 > w:
                        return None
                    # round 27 (v71 probe): the attack scene shows the defender's name panel up top
                    # too (Gracia's, while a Masked Pegasus struck her), so her 'turn' cast into the
                    # scene. Only the field panel has the land-effect box beside it on the left
                    le = sum(1 for yy in range(y, y + 20) for xx in range(max(0, x0 - 50), max(0, x0 - 3))
                             if blue(*px(xx, yy)))
                    if le < 150:
                        return None
                    bits = tuple(1 if sum(px(xx, yy)) > 600 else 0
                                 for yy in range(y + 2, y + 16) for xx in range(x0 + 2, x0 + 90))
                    red = sum(1 for yy in range(y, min(h, y + 22)) for xx in range(x0, x0 + 90)
                              for (rr, gg, bb) in (px(xx, yy),) if rr > 170 and gg < 110 and bb < 110)
                    return bits, red >= 12
            else:
                run = 0
            prev = (g, b) if ok else None
    return None


def panel_unit(pol, sig, slots, tol=SIG_TOL):
    """The force slot whose learned panel name matches sig (None when unknown or an enemy panel).
    A force panel no learned name matches belongs to the one on-field slot not learned yet, when
    exactly one is left (a unit boxed in from the first turn)."""
    if not sig or sig[1]:
        return None
    sigs = pol.sigs
    for k, b in sigs.items():
        if sum(p != q for p, q in zip(b, sig[0])) <= tol:
            return k
    left = [k for k in slots if k not in sigs]
    if len(left) == 1 and len(sigs) >= 1:
        sigs[left[0]] = sig[0]
        return left[0]
    return None


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


# round 27 (Sc2 V1.003 Ch6 war machine, map 0x49): the camera there is turned a quarter, so pad RIGHT
# steps y-1 and UP x+1 (Hazuki at 12,4); every planned step went the wrong way or into a wall. The
# probe step of each turn shows which way a pad direction goes: ROTATIONS maps a planned direction
# (STEP's sense) to the pad direction that makes it under the turn seen
ROTATIONS = (lambda a, b: (a, b), lambda a, b: (-b, a), lambda a, b: (-a, -b), lambda a, b: (b, -a))


def learn_turn(pressed, delta):
    """The rotation index under which pad `pressed` steps by `delta`, or None (not one step)."""
    for i, rot in enumerate(ROTATIONS):
        if rot(*STEP[pressed]) == tuple(delta):
            return i
    return None


def pad_for(d, turn):
    """The pad direction that steps the way `d` means in STEP, under rotation index `turn`."""
    if not turn:
        return d
    return next(k for k in STEP if ROTATIONS[turn](*STEP[k]) == STEP[d])


def plan_step(p, live, occupied, blocked, size=64, limit=6000, passable=frozenset(), goals=None):
    """First direction of a shortest path from `p` to a tile next to a live enemy, over a
    size x size grid where unseen tiles are taken as open (optimistic planning: a failed step marks
    its edge, `blocked` counts failures per edge; two failures close it, one makes it dear).
    Tiles other units hold are closed, except `passable` ones (the unit's own force: a unit walks
    through its allies but cannot stop on one). None when no tile is reachable."""
    import heapq
    goals = (set(goals) if goals is not None else  # tactics: given end tiles
             {(x + dx, y + dy) for x, y in live for dx, dy in STEP.values()}) - occupied - set(passable)
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


def retreat_path(p, live, allies, blocked, reach=5, size=64, avoid=None):
    """Directions from `p` to the free tile within `reach` steps farthest from every live enemy
    (allies are walked through but not ended on, enemies and known-blocked edges are not
    crossed); [] when no tile is farther than `p` itself. With `avoid` (x, y, r) it never ends in that zone
    (v123, Sc2 Ch6: a hurt Medion backed away from the enemies into the blast tiles and stayed there)."""
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
                if avoid and abs(r[0] - avoid[0]) + abs(r[1] - avoid[1]) <= avoid[2]:
                    continue
                if r not in allies and (dist(r), -depth) > best_key:
                    best, best_key = seen[r], (dist(r), -depth)
        frontier = nxt
    return best


LEADER_REACH = 4                      # --leader-attack: steps the leader walks to a target


def leader_target(p, targets, occupied, avoid=None, reach=LEADER_REACH):
    """--leader-attack: of `targets` [(x, y)], the one with a free tile next to it (not in `occupied`,
    not within the avoid zone (x, y, r)) nearest the leader at `p`, at most `reach` steps; None if none."""
    best = None
    for tx, ty in targets:
        for dx, dy in STEP.values():
            q = (tx + dx, ty + dy)
            d = abs(q[0] - p[0]) + abs(q[1] - p[1])
            if d > reach or (q in occupied and q != p):
                continue
            if avoid and abs(q[0] - avoid[0]) + abs(q[1] - avoid[1]) <= avoid[2]:
                continue
            if best is None or d < best[0]:
                best = (d, (tx, ty))
    return best and best[1]


def unit_hp_of(read, table, slot):
    e = read(table + slot * memory_map.UNIT_STRIDE + memory_map.UNIT_HP, 2)
    return int.from_bytes(e, 'big')


def unit_mp_of(read, table, slot):
    return read(table + slot * memory_map.UNIT_STRIDE + memory_map.UNIT_MP, 1)[0]


def is_hurt(read, table, slot, share):
    """True when force record `slot` has less than `share` of its max HP."""
    e = read(table + slot * memory_map.UNIT_STRIDE, memory_map.UNIT_STRIDE)
    hp = int.from_bytes(e[memory_map.UNIT_HP:memory_map.UNIT_HP + 2], 'big')
    top = int.from_bytes(e[memory_map.UNIT_MAX_HP:memory_map.UNIT_MAX_HP + 2], 'big')
    return top > 0 and hp < share * top


def heal_due(rd, units, pol, me):
    """A --heal unit below heal_at with MP for a first-level cast, whose casts have not failed twice."""
    return (me in getattr(pol, 'heal', ()) and pol.heal_fail.get(me, 0) < 2
            and is_hurt(rd, units['force'], me, pol.heal_at) and unit_mp_of(rd, units['force'], me) >= 3)


def heal_cast(rd, units, pol, me, ring='magic', target=None, caster=None, aim=None):
    """Ring Magic, first spell, first level, default target (the caster itself for Heal); the next
    turn checks the target's HP rose (pol.heal_check: target, its HP, the caster charged on a miss).
    ring='item' uses the first item instead (Items, Use, first item, default target)"""
    t = me if target is None else target
    pol.heal_check = (t, unit_hp_of(rd, units['force'], t), me if caster is None else caster)
    pol.casts += 1
    pick = [((aim,), 6), ((), 20)] if aim else []      # --healers: move the target cursor onto an ally
    return ([(('C',), 6), ((), 30), ((RING[ring],), 6), ((), 14)]
            + [(('C',), 6), ((), 30)] * 2 + pick + [(('C',), 6), ((), 30)] * 2 + tap(('C',), gap=40) * 4)


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
        pol.turn = 0
        pol.att_miss, pol.last_attack = {}, None
        pol.still, pol.tac_check = {}, None
        pol.sigs = SIGS.setdefault(units['force'], {})
    phantoms = getattr(pol, 'phantoms', set())
    hp_of = {k: hp for k, x, y, f, hp in enemies}
    la = getattr(pol, 'last_attack', None)
    if la:
        # round 19 (Sc3 Ch7 dock fight): stale enemy records left from the harbour fight sit next to
        # force units; Attack on one finds no target and the turn never ends, so every candidate
        # replayed the same loop. An attack that leaves the adjacent records' HP unchanged MISS_PHANTOM
        # times marks them as phantoms for this battle
        keys, hp0 = la[:2]
        pol.last_attack = None
        hp1 = sum(hp_of.get(k, 0) for k in keys)
        if len(la) > 2 and hp1 < hp0:              # --leader-attack: the most one hit by that unit took
            pol.hit[la[2]] = max(pol.hit.get(la[2], 0), hp0 - hp1)
        if hp1 == hp0:
            pol.att_miss[keys] = pol.att_miss.get(keys, 0) + 1
            if pol.att_miss[keys] >= MISS_PHANTOM:
                pol.phantoms = phantoms = phantoms | set(keys)
        else:
            pol.att_miss.pop(keys, None)
    hc = getattr(pol, 'heal_check', None)
    if hc:
        # --heal: a cast that left the caster's HP no higher was not a heal (first spell not Heal, no
        # MP, a message): two of those and that unit retreats instead from then on
        pol.heal_check = None
        if unit_hp_of(rd, units['force'], hc[0]) <= hc[1]:
            who = hc[2] if len(hc) > 2 else hc[0]
            pol.heal_fail[who] = pol.heal_fail.get(who, 0) + 1
        else:
            pol.heals = getattr(pol, 'heals', 0) + 1
    tcx = getattr(pol, "tac_check", None)
    if tcx:
        # --casters/--ranged/--item-attack: a use that took no HP from the enemies in reach counts
        pol.tac_check = None
        if sum(hp_of.get(k, 0) for k in tcx[0]) >= tcx[1]:
            pol.tac_fail[tcx[2]] = pol.tac_fail.get(tcx[2], 0) + 1
    live = [(x, y) for k, x, y, f, hp in enemies if hp > 0 and k not in phantoms]
    if not live:
        return tap(('C',), gap=30) * 4
    if panel_share(side.frame()) > 0.02:          # a menu or message is up: back out (B), or C
        pol.idle += 1
        if pol.idle % 5 == 0:
            return tap(('C',), gap=30) * 6
        return tap(('C',), gap=30) if pol.idle % 3 == 0 else tap(('B',), gap=20)
    still = tactics.track_still(pol.still, enemies, pol.root_epos) - phantoms
    tac = pol.tactics or {}
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
            t = learn_turn(d, (now[moved[0]][0] - before[moved[0]][0], now[moved[0]][1] - before[moved[0]][1]))
            if t is not None:
                pol.turn = t
            if moved[0] not in getattr(pol, 'sigs', {}):
                sg = panel_sig(side.frame())
                if sg and not sg[1]:
                    pol.sigs[moved[0]] = sg[0]
            break
    turn = getattr(pol, 'turn', 0)
    if not moved and not hud_up(side.frame()) and getattr(pol, 'cursor_b', 0) < 2:
        # round 5 (Sc1 Battle 22 search): nothing moved and no unit panel: the free cursor (B on
        # the start tile enters it; C there opens the field menu or a member's status, which the
        # menu branch above backed out of by B into the cursor again), so the turn sat for 6k
        # VBlanks with the leader next to an enemy. B puts the cursor back on the unit
        pol.cursor_b = getattr(pol, 'cursor_b', 0) + 1
        pol.recentred = getattr(pol, 'recentred', 0) + 1
        return tap(('B',), gap=60)
    pol.cursor_b = 0
    if not moved and (getattr(pol, 'heal', ()) or getattr(pol, 'leader', None) is not None or getattr(pol, 'protect', None)):
        who = panel_unit(pol, panel_sig(side.frame()), list(before))
        if who is not None and heal_due(rd, units, pol, who):
            return heal_cast(rd, units, pol, who)
        lead0 = pol.leader if getattr(pol, 'leader', None) in before else min(before)
        if who is not None and (who == lead0 or who in (getattr(pol, 'protect', None) or ())):
            # round 27 (Sc3 Ch7 dock fight v71): Gracia boxed in at 20,26 by teammates was never
            # probed, so she never retreated and three enemies closed on her; every level-8 candidate
            # fell the same way. Her panel names her: take the cautious branch (its retreat path
            # crosses teammates)
            moved = [who]
            pol.named = getattr(pol, 'named', 0) + 1
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
    picked = goal is not live                      # a search candidate's random enemy
    if goal is live and getattr(pol, 'focus', ()):
        fx = [(x, y) for k, x, y, f, hp in enemies if hp > 0 and k in (getattr(pol, "focus", None) or ()) and k not in phantoms]
        if fx:
            goal = fx
    esc = getattr(pol, 'escort', None)
    esc = [e for e in ((esc,) if isinstance(esc, int) else (esc or ())) if e in before and e != me]
    if esc and not hold_back and not picked:
        # round 27 (Sc3 Ch7 dock fight, probes ap71b-f): Gracia (31) takes no player turns (the game
        # moves her), stays at 20,26 and the church follows when she falls; three enemies closed on
        # her while the force chased the far ones. --escort: enemies within ESCORT_R of an escorted
        # unit come first, and with none near the unit walks next to the escorted unit nearest the
        # enemies. v72 (one escort, Gracia): the force ringed her and Julian (protected, at 21,30)
        # fell alone, so the protected units are escorted too (--escort 31 7)
        near = [(x, y) for k, x, y, f, hp in enemies if hp > 0 and k not in phantoms
                and any(abs(x - before[e][0]) + abs(y - before[e][1]) <= ESCORT_R for e in esc)]
        # v73: from 287k the enemies sat back 8+ tiles from the ring and every candidate scored the
        # same for 4 levels (a stalemate), so the ring only holds while an enemy is within
        # ESCORT_GUARD of an escorted slot; farther off, units attack as usual
        gap = {e: min(abs(before[e][0] - x) + abs(before[e][1] - y) for x, y in live) for e in esc}
        if near:
            goal = near
            pol.escorting = getattr(pol, 'escorting', 0) + 1
        elif min(gap.values()) <= ESCORT_GUARD:
            goal = [before[min(esc, key=gap.get)]]
            pol.escorting = getattr(pol, 'escorting', 0) + 1

    hi = getattr(pol, 'heal_item', ())
    if me in hi and pol.heal_fail.get(me, 0) < 2:
        # round 27 (Sc3 Ch7 dock fight v74, probe ap74b): no force member has Heal (Edmund's one
        # spell is Antidote) and Gracia wore down to 8 HP by 325k in every candidate; Edmund carries
        # a Healing Drop and Items/Use with the default target put it on Gracia beside him (20 -> 35).
        # A --heal-item unit next to a hurt escorted/protected unit uses its first item, default target
        wards = [e for e in esc + list(getattr(pol, 'protect', None) or ()) if e in before and e != me]
        hurt = [e for e in wards if abs(before[e][0] - before[me][0]) + abs(before[e][1] - before[me][1]) == 1
                and is_hurt(rd, units['force'], e, pol.heal_at)]
        if hurt:
            press(('B',), 6)
            press((), 20)
            if not hud_up(side.frame()):
                # v76 (probe ap76a): this B put the unit back and left the free cursor up, so the
                # ring never opened and every turn went to status panels (25 levels at one score);
                # a second B puts the cursor back on the unit, as in the cautious branch
                press(('B',), 6)
                press((), 40)
            pol.item_heals = getattr(pol, 'item_heals', 0) + 1
            return heal_cast(rd, units, pol, me, ring='item', target=hurt[0])
        far = [e for e in wards if abs(before[e][0] - before[me][0]) + abs(before[e][1] - before[me][1]) <= HEAL_WALK
               and is_hurt(rd, units['force'], e, pol.heal_at)]
        if far:
            # v78: Gracia sat at 11/35 for 70 backtracks with the item carriers a few tiles off; a
            # hurt ward within HEAL_WALK draws the carrier next to it (the item goes on next turn)
            goal = [before[min(far, key=lambda e: unit_hp_of(rd, units['force'], e))]]
            pol.item_walks = getattr(pol, 'item_walks', 0) + 1

    goal_tiles = None                              # tactics: the tiles to end the move on (None: next to a goal)
    if (me in tac.get("healers", ()) and pol.heal_fail.get(me, 0) < 2
            and unit_mp_of(rd, units["force"], me) >= tactics.MP_MIN):
        # round 29 (--healers, Sc3 Ch7 dock: Gracia at 19/35 from ~279k and nobody healed her): a
        # healer casts its first spell, first level, on the most hurt ally next to it (itself
        # included) before it attacks; one farther off, within HEAL_WALK, draws it closer
        hurt = [k for k in before if tactics.md(before[k], before[me]) <= HEAL_WALK
                and is_hurt(rd, units["force"], k, pol.heal_at)]
        if hurt:
            k = min(hurt, key=lambda k: unit_hp_of(rd, units["force"], k))
            if tactics.md(before[k], before[me]) <= 1:
                press(("B",), 6)
                press((), 20)
                if not hud_up(side.frame()):
                    press(("B",), 6)
                    press((), 40)
                pol.ally_heals = getattr(pol, "ally_heals", 0) + 1
                aim = None if k == me else pad_for(tactics.aim_dir(before[me], before[k]), turn)
                return heal_cast(rd, units, pol, me, target=k, aim=aim)
            goal = [before[k]]
            pol.heal_walks = getattr(pol, "heal_walks", 0) + 1

    def dist(p):
        return min(abs(p[0] - e[0]) + abs(p[1] - e[1]) for e in live)

    # the leader (the force's first on-field slot) losing all HP loses the battle (round 3: Sc1
    # Battle 22 lost with Synbios at 18 HP walking up to the boss). Round 4 (fresh :25 run): the
    # leader walked to the front of the Battle 22 bridge at full HP, stood between two enemies and
    # fell 30k VBlanks later. So the leader never advances: B returns the probe step and it only
    # attacks what is already in reach; below LEADER_SAFE of max HP it walks away from the
    # enemies (through teammates, to a free tile)
    cautious = lead_attack = False
    lead = pol.leader if getattr(pol, 'leader', None) in before else min(before)
    # v115 (Sc2 Ch6 Garvin fight): the blast at 34-38,37-40 every ~8.6k VBlanks killed every unit
    # left in it, not only the leader. --avoid-all: any unit that starts its turn in the --avoid
    # zone plays the cautious turn (walks out, strikes only what is in reach)
    av0 = getattr(pol, "avoid", None) if tac.get("avoid_all") else None
    zone_all = bool(av0 and me in before and abs(before[me][0] - av0[0]) + abs(before[me][1] - av0[1]) <= av0[2])
    if me == lead or me in (getattr(pol, 'protect', None) or ()) or zone_all:
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
        if me in now and heal_due(rd, units, pol, me):
            # round 27 (Sc3 Ch7 dock fight v69): Gracia (31) went 35 -> 23 -> 11 HP over the first
            # levels and every later candidate fell under the --guard-hp floor; retreating alone never
            # brought her HP back. A --heal unit below heal_at casts its first spell, first level, on
            # the default target (the caster itself for Heal), before it would retreat
            return heal_cast(rd, units, pol, me)
        ka = getattr(pol, 'keep_away', 0)
        threats = [(x, y) for k, x, y, f, hp in enemies if hp > 1 and k not in phantoms]
        near_threat = bool(ka and me in now and threats and
                           min(abs(now[me][0] - e[0]) + abs(now[me][1] - e[1]) for e in threats) <= ka)
        av = getattr(pol, 'avoid', None)
        in_zone = bool(av and me in now and abs(now[me][0] - av[0]) + abs(now[me][1] - av[1]) <= av[2])
        las = getattr(pol, "leader_attack", None)
        if las and pol.pathing and me == lead and me in now and not in_zone:
            # v90 (Sc2 Ch6 Garvin fight, probe ap90 at 458k): Medion, cautious, stood among four Giga
            # Breakers (two at 37-60 of 170 HP), only struck what was in reach and fell at ~486k in
            # every candidate. --leader-attack S: the leader walks to and attacks an enemy it can
            # finish (HP at most its best hit so far) or one under S of max HP, within LEADER_REACH
            # steps, never onto or through the --avoid zone; otherwise it plays cautious as before
            fin = pol.hit.get(me, 0)
            weak = [(x, y) for k, x, y, f, hp in enemies if hp > 1 and k not in phantoms
                    and (hp <= fin or is_hurt(rd, units["enemies"], k, las))]
            tgt = weak and leader_target(now[me], weak, {v for k, v in now.items() if k != me} | set(live), av)
            if tgt:
                goal, hold_back, lead_attack = [tgt], False, True
                pol.leader_attacks = getattr(pol, "leader_attacks", 0) + 1
        if (me != lead and pol.pathing and me in now and not lead_attack and me not in tac.get("passive", ())
                and not (in_zone or near_threat or is_hurt(rd, units["force"], me, LEADER_SAFE))):
            # round 29 (Sc3 dock v99, Sc1 v102: protected units only retreated and the fights stalled):
            # --protect means avoid danger, not never attack. A protected unit walks to and attacks a
            # target (focus first) it can hit within HOLD_MOVE steps from a tile not next to a
            # stationary enemy (one that has not moved: the Sc1 boss pocket) nor in the --avoid zone.
            # --passive slots keep the old never-attack play (Sc3 v105: the guest Julian went in and fell
            # to 1/40 HP by level 4)
            fx = [(x, y) for k, x, y, f, hp in enemies if hp > 1 and k in (getattr(pol, "focus", None) or ()) and k not in phantoms]
            heavy = [(x, y) for k, x, y, f, hp in enemies if k in still]
            st = tactics.safe_target(now[me], fx or [(x, y) for k, x, y, f, hp in enemies if hp > 1 and k not in phantoms],
                                     {v for k, v in now.items() if k != me} | set(live), heavy, av)
            if st:
                goal, goal_tiles, hold_back, lead_attack = [st[0]], st[1], False, True
                pol.protect_attacks = getattr(pol, "protect_attacks", 0) + 1
        if me in now and not lead_attack and (in_zone or near_threat or is_hurt(rd, units['force'], me, LEADER_SAFE)):
            # round 27 (Sc2 V1.003 war machine): the leader gets one turn before the blast and the
            # first planned step hit an unseen wall, so the turn ended in the zone. A step that fails
            # in the first two marks the edge and plans again from where the unit stands (8 plans)
            walked = 0
            for _plan in range(8):
                here = pos().get(me)
                if here is None:
                    break
                path = retreat_path(here, [av[:2]] if in_zone else live,
                                    {v for k, v in pos().items() if k != me}, pol.blocked,
                                    reach=max(1, (8 if in_zone else 5) - walked), avoid=av if tac.get("avoid_all") and not in_zone else None)
                replan = False
                for i, d in enumerate(path):
                    q = pos().get(me)
                    if q is None:
                        break
                    press((pad_for(d, turn),), 8)
                    press((), 10)
                    if pos().get(me, q) == q:          # a wall early on; later it is the move range's end
                        if walked < 2:
                            pol.blocked[(q, step_of(q, d))] = 1
                            replan = True
                        break
                    walked += 1
                    pol.retreats = getattr(pol, 'retreats', 0) + 1
                if not replan:
                    break
    if lead_attack:
        cautious = False
    rng_by = {k for k in set(tac.get("ranged", ())) | set(tac.get("casters", ())) | set(tac.get("item_attack", ()))
              if pol.tac_fail.get(k, 0) < tactics.FAIL_MAX}
    reach = tactics.SPELL_RANGE if me in rng_by else 1
    tg = [g for g in goal if g in live] if goal_tiles is None else []
    if pol.pathing and not cautious and not hold_back and tg and me in pos():
        now = pos()
        occ = {v for k, v in now.items() if k != me} | set(live)
        t = min(tg, key=lambda e: tactics.md(now[me], e))
        threats = [(x, y) for k, x, y, f, hp in enemies if k in still]
        if tac.get("hold_until") and threats:
            # round 29 (--hold-until N, Sc1 Battle 22 end v91-v103: units walked up to the boss pocket
            # one at a time and fell to the wizards): a unit whose every tile to hit its target is in a
            # stationary enemy's range waits just outside until N units (all that are left, if fewer)
            # can reach that target this round, then they commit together
            skip = {lead} | set(getattr(pol, "protect", None) or ())
            hg = tactics.hold_goals(now[me], t, threats, occ, tac["hold_until"], now, rng_by, skip, reach)
            if hg is not None:
                goal_tiles = hg
                pol.hold_waits = getattr(pol, "hold_waits", 0) + 1
        if goal_tiles is None and reach > 1:
            # --ranged/--casters/--item-attack: end 2 tiles from the target (out of its melee)
            goal_tiles = tactics.strike_tiles([t], reach, occ) or None
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
            if goal_tiles is not None:
                if p in goal_tiles or fails >= 8:
                    break
            elif dist(p) <= 1 or fails >= 8 or (goal is not live and min(abs(p[0] - e[0]) + abs(p[1] - e[1]) for e in goal) <= 1):
                break
            allies = {v for k, v in now.items() if k != me}
            # allies are walked through (round 2: a force packed on the Battle 22 bridge or in the
            # Sc3 final room had no path with allies as walls, so every unit held for 120k VBlanks)
            shut = set()
            if lead_attack and getattr(pol, "avoid", None):  # --leader-attack: never path through the zone
                zx, zy, zr = pol.avoid
                shut = {(zx + i, zy + j) for i in range(-zr, zr + 1) for j in range(-zr, zr + 1) if abs(i) + abs(j) <= zr}
            d = plan_step(p, goal, allies | set(live) | shut, pol.blocked, passable=allies - shut, goals=goal_tiles)
            if d is None:
                break
            press((pad_for(d, turn),), 8)
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
            press((pad_for(d, turn),), 8)
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
    mq = pos().get(me)
    inr = [k for k, x, y, f, hp in enemies if hp > 0 and k not in getattr(pol, "phantoms", set()) and mq
           and tactics.md((x, y), mq) <= tactics.SPELL_RANGE]
    kind = None
    if me in rng_by and inr and not cautious:
        if me in tac.get("casters", ()) and unit_mp_of(rd, units["force"], me) >= tactics.MP_MIN:
            kind = "magic"
        elif me in tac.get("item_attack", ()):
            kind = "item"
        elif me in tac.get("ranged", ()):
            kind = "attack"
    near = me in pos() and dist(pos()[me]) <= 2                    # first-level spells reach 2 tiles (Blaze, Heal)
    cast_now = (near and pol.cast and pol.tried.get(me, 0) % 2 == 0) or (near and cast_pick)
    # round 19 (Sc3 Ch7 dock fight, search v55): the leader and protected units never cast. Julian's
    # first spell is Egress, and a random cast took the force out of the fight to the church, which
    # the battle-over check took for a win (the battle byte went to the field and a story bit was set)
    cast_now = cast_now and not cautious and not lead_attack
    if near and pol.cast:
        pol.tried[me] = pol.tried.get(me, 0) + 1
    if kind:
        # round 29 (--casters / --item-attack / --ranged): first spell at its first level, first item,
        # or a bow shot on the highlighted target in reach; two uses that take no HP turn it off
        pol.tac_check = (tuple(sorted(inr)), sum(hp_of.get(k, 0) for k in inr), me)
        press((RING[kind],), 6)
        press((), 14)
        for _ in range(2 if kind == "attack" else 4):
            press(("C",), 6)
            press((), 30)
        pol.attacks += 1
        pol.tac_uses = getattr(pol, "tac_uses", 0) + 1
    elif cast_now:
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
            pol.last_attack = (keys, sum(hp_of.get(k, 0) for k in keys), me)
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
