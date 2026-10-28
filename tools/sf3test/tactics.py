"""Opt-in battle tactics for the search policy (round 29). Positions come from the unit tables and
every action is pad input, as in autoplay.

Sc1 Battle 22 end fight (v91-v103): the boss (16,29) and two High Wizards (15,30 17,30) never move,
and every unit that walked up to 16,26-16,28 alone fell to their Bolt one turn at a time. Sc3 Ch7 dock
(v99, v102): --protect units only ever retreated, so once the others had fallen nobody attacked and
the score sat flat for 25 levels."""

HOLD_RANGE = 3      # --hold-until: tiles a stationary enemy reaches (Sc1: the wizards hit 16,28 from 15,30)
HOLD_MOVE = 5       # steps a unit is taken to cover in one turn
STILL_TURNS = 3     # turns seen on one tile that make an enemy stationary
SPELL_RANGE = 2     # first-level Blaze/Freeze/Bolt/Heal and bows reach 2 tiles
MP_MIN = 2          # a first-level spell costs 2-3 MP; with less the unit attacks instead
FAIL_MAX = 2        # spells/shots/items that took no enemy HP before a unit goes back to plain attacks


def md(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def in_avoid(q, av):
    """--avoid zone membership: (x, y, r) is the tiles within r steps of x,y; (x0, y0, x1, y1) is that
    rectangle (v126, Sc2 Ch6: the force rides the war machine, its deck shifts 4 tiles down the map,
    and every unit on it at x33-40 dies at ~504.7k, so the zone is a column, not a circle)."""
    if not av:
        return False
    if len(av) == 4:
        return av[0] <= q[0] <= av[2] and av[1] <= q[1] <= av[3]
    return md(q, av[:2]) <= av[2]


def avoid_centre(av):
    return tuple(av[:2]) if len(av) == 3 else ((av[0] + av[2]) // 2, (av[1] + av[3]) // 2)


def track_still(still, enemies, root_pos=None):
    """Update `still` {slot: ((x, y), turns seen there)} from `enemies` [(slot, x, y, flags, hp)] and
    return the live (HP above 1) slots seen STILL_TURNS turns on one tile. An enemy first seen on its
    search-root tile (`root_pos` {slot: (x, y)}) has not moved since the root: stationary at once."""
    out = set()
    for k, x, y, f, hp in enemies:
        p, n = still.get(k, (None, 0))
        if p is None and root_pos and tuple(root_pos.get(k, ())) == (x, y):
            p, n = (x, y), STILL_TURNS - 1
        n = n + 1 if p == (x, y) else 1
        still[k] = ((x, y), n)
        if n >= STILL_TURNS and hp > 1:
            out.add(k)
    return out


def in_danger(q, threats, r=HOLD_RANGE):
    return any(md(q, t) <= r for t in threats)


def ring_tiles(target, reach, occupied=(), size=64):
    """Free tiles 1..reach steps from `target` (reach 1: the four next to it)."""
    tx, ty = target
    return {(tx + dx, ty + dy) for dx in range(-reach, reach + 1) for dy in range(-reach, reach + 1)
            if 0 < abs(dx) + abs(dy) <= reach and 0 <= tx + dx < size and 0 <= ty + dy < size} - set(occupied)


def can_reach(p, target, occupied, reach=1, move=HOLD_MOVE):
    """True when a unit at `p` can end its move on a free tile from which it hits `target`."""
    return any(md(p, q) <= move for q in ring_tiles(target, reach, set(occupied) - {p}))


def hold_count(force, target, occupied, ranged=(), skip=()):
    """How many force units {slot: (x, y)}, not in `skip`, could hit `target` this round."""
    return sum(1 for k, p in force.items() if k not in skip
               and can_reach(p, target, occupied, SPELL_RANGE if k in ranged else 1))


def hold_goals(p, target, threats, occupied, need, force, ranged=(), skip=(), reach=1):
    """--hold-until N for the mover at `p` going for `target`. None: go (a tile out of every
    stationary threat's range hits it, or N units, or all that are left, can reach it this round).
    Else the tiles to wait on: [p] when it already waits out of range, near the target, otherwise the
    free out-of-range tiles nearest the target."""
    occupied = set(occupied)
    if any(not in_danger(q, threats) for q in ring_tiles(target, reach, occupied - {p})):
        return None
    able = [k for k in force if k not in skip]
    if hold_count(force, target, occupied, ranged, skip) >= min(need, len(able)):
        return None
    r = HOLD_RANGE + 3
    wait = [q for q in ring_tiles(target, r, occupied - {p}) if not in_danger(q, threats)]
    if not wait:
        return None
    near = min(md(q, target) for q in wait)
    if not in_danger(p, threats) and md(p, target) <= near + 1:
        return {p}
    return {q for q in wait if md(q, target) == near}


def strike_tiles(targets, reach, occupied):
    """Ranged units and casters: free tiles exactly `reach` from a target (out of its melee), else any
    within reach."""
    out = set()
    for t in targets:
        out |= {q for q in ring_tiles(t, reach, occupied) if md(q, t) == reach}
    if not out:
        for t in targets:
            out |= ring_tiles(t, reach, occupied)
    return out


def safe_target(p, targets, occupied, heavy, avoid=None, reach=HOLD_MOVE):
    """--protect: of `targets` [(x, y)], the nearest with a free tile next to it within `reach` steps of
    `p` that is not next to a stationary heavy hitter (`heavy` [(x, y)]) nor in the avoid zone
    (x, y, r); (target, those tiles) or None."""
    best = None
    for t in targets:
        ok = {q for q in ring_tiles(t, 1, set(occupied) - {p}) if md(p, q) <= reach
              and not any(md(q, h) <= 1 for h in heavy)
              and not in_avoid(q, avoid)}
        if ok:
            d = min(md(p, q) for q in ok)
            if best is None or d < best[0]:
                best = (d, t, ok)
    return best and (best[1], best[2])


def aim_dir(a, b):
    """The STEP direction from tile `a` to the next tile `b`."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    return {(1, 0): "RIGHT", (-1, 0): "LEFT", (0, 1): "UP", (0, -1): "DOWN"}.get((dx, dy))
