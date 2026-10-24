"""Per-profile SF3 game-state addresses (work RAM), found by matching a loaded save's payload in RAM.

The save payload is a straight copy of the live state block: payload offset o lives at
state_base + o. Field offsets were found by diffing community chapter saves with known locations.
Addresses only; no game bytes."""

# payload offsets (same in all three scenarios)
SIZE = 0x00        # u32 payload length - 8
CHECKSUM = 0x04    # u32 sum of payload[8:]
MAP_ID = 0x1D      # u8 current map/area id (towns, fields and battle maps)
BATTLE_ID = 0x25   # u8 battle number while a battle is set up, 0 in towns (Sc1 1.., Sc2 41.., Sc3 81..)
PREV_MAP = 0x21    # u8 map the party came from

PAYLOAD_SIZE = {1: 12904, 2: 16248, 3: 24344}

# Battle unit tables (Sc1 USA, round 9 RAM diffs on Battle 1, record 02): two arrays of 60 records,
# stride 0xB0, enemies first, then the force (record 0 is the leader; name at +0).
# Fields: u8 x at +0x7C, u8 y at +0x7E (pad RIGHT = x+1, UP = y+1; live while a unit moves),
# u8 flags at +0x80 (0x80 force, 0x40 on the field), u16 HP at +0x82, u16 max HP at +0x10 (force).
UNIT_STRIDE = 0xB0
UNIT_COUNT = 60
UNIT_X, UNIT_Y, UNIT_FLAGS, UNIT_HP = 0x7C, 0x7E, 0x80, 0x82
UNIT_ON_FIELD = 0x40
# Round 12 (sc1-usa b92d515b, black-box: Battle 1 records read against the status window and the
# party's known classes): u16 max HP at +0x10, max MP byte +0x12; in-battle (current) values:
# HP u16 +0x82, MP +0x84, attack +0x85, defence +0x86, agility +0x87, movement +0x89.
UNIT_MAX_HP, UNIT_MAX_MP = 0x10, 0x12
UNIT_MP, UNIT_ATK, UNIT_DEF, UNIT_AGI, UNIT_MOV = 0x84, 0x85, 0x86, 0x87, 0x89
BATTLE_UNITS = {'scenario1-usa-v25_1': dict(enemies=0x0602F6F0, force=0x06032030)}

# Map ids a map sweep must not edit into a save: checked on Beetle Saturn with a real BIOS (the game
# never draws again after the load), so a failure there says nothing about the port.
# Sc3 ids from 0xA5 up that fail in the sweep and show only black or 'CD READ ERROR' on Beetle
# with a real BIOS (round 6 probes, 600 frames after the load). 0xA1 (title over black, same
# as ours) and 0xA8 (plays on Beetle) are valid.
_SC3_HIGH_INVALID = (
    0xA5, 0xA9, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3,
    0xB4, 0xB5, 0xB6, 0xB7, 0xB8, 0xB9, 0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF,
    0xC0, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9, 0xCA, 0xCB,
    0xCC, 0xCD, 0xCE, 0xCF, 0xD0, 0xD2, 0xD3, 0xD4, 0xD5, 0xD7, 0xD8, 0xD9,
    0xDA, 0xDB, 0xDC, 0xDD, 0xDE, 0xDF, 0xE0, 0xE1, 0xE2, 0xE3, 0xE4, 0xE5,
    0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xEB, 0xEC, 0xEE, 0xEF, 0xF2, 0xF3, 0xF5,
    0xF6, 0xF7, 0xF8, 0xF9,
)

# Sc2 V2.000 ids from 0xCE up that fail in the sweep and show only black or 'CD READ ERROR' on Beetle
# with a real BIOS (round 7 probes, 600 frames after the load; 0xCF falls back to map 0x63).
_SC2_HIGH_INVALID = (
    0xCE, 0xCF, 0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9,
    0xDA, 0xDC, 0xDD, 0xDE, 0xDF, 0xE0, 0xE1, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6,
    0xE7, 0xE9, 0xEA, 0xEB, 0xEC, 0xED, 0xEE, 0xEF, 0xF0, 0xF1,
    0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF9, 0xFA, 0xFC, 0xFD, 0xFE
)

INVALID_MAPS = {1: {0x70: 'black after the load on Beetle with a real BIOS'},
                2: {m: 'black or CD READ ERROR after the load on Beetle with a real BIOS (V2.000)'
                    for m in _SC2_HIGH_INVALID},
                3: {0x4D: 'black after the load on Beetle with a real BIOS, then map id 0',
                    **{m: 'black or CD READ ERROR after the load on Beetle with a real BIOS'
                       for m in _SC3_HIGH_INVALID}}}

PROFILES = {
    # profile id: (scenario, state_base, tick)  tick: u32 the game adds one to each frame it runs
    'scenario1-usa-v25_1': (1, 0x06090FE0, 0x0601FC68),
    'scenario2-v25_1-v2_000': (2, 0x06090578, 0x0602143C),
    'scenario2-v25_1-v1_003': (2, 0x0609056C, 0x06021484),
    'scenario3-v25_1-redump': (3, 0x0609075C, 0x060214CC),
}


def lookup(profile):
    profile = profile[:-5] if profile.endswith('.json') else profile
    if profile not in PROFILES:
        raise KeyError(f'no SF3 memory map for profile {profile}')
    scenario, base, tick = PROFILES[profile]
    return dict(profile=profile, scenario=scenario, state_base=base, tick=tick,
                map_id=base + MAP_ID, battle_id=base + BATTLE_ID, prev_map=base + PREV_MAP,
                units=BATTLE_UNITS.get(profile))


def read_units(read, table):
    """[(slot, x, y, flags, hp)] for the on-field records of a unit table; `read(addr, n)`."""
    raw = read(table, UNIT_STRIDE * UNIT_COUNT)
    out = []
    for k in range(UNIT_COUNT):
        e = raw[k * UNIT_STRIDE:(k + 1) * UNIT_STRIDE]
        if e[UNIT_FLAGS] & UNIT_ON_FIELD:
            out.append((k, e[UNIT_X], e[UNIT_Y], e[UNIT_FLAGS], int.from_bytes(e[UNIT_HP:UNIT_HP + 2], 'big')))
    return out


def looks_like_force(rec):
    """A force record starts with its name (printable ASCII, NUL-padded) and has flag 0x80; other
    battles may put their tables elsewhere (round 12: Sc1 Battle 30 does), so check before a poke."""
    name = rec[:12].rstrip(b'\0 ')
    return bool(name) and all(32 <= c < 127 for c in name) and bool(rec[UNIT_FLAGS] & 0x80)


def assist_writes(read, units, enemy_hp=None, hp=999, stat=99, move=12):
    """Test-only assist (never on by default): [(addr, bytes)] that give every on-field force unit
    `hp` HP and max HP, full MP and `stat` attack/defence/agility, `move` movement, and, with
    `enemy_hp`, every on-field enemy with more HP than that `enemy_hp`. Nothing for an empty table."""
    out = []
    raw = read(units['force'], UNIT_STRIDE * UNIT_COUNT)
    for k in range(UNIT_COUNT):
        e = raw[k * UNIT_STRIDE:(k + 1) * UNIT_STRIDE]
        if not e[UNIT_FLAGS] & UNIT_ON_FIELD or not looks_like_force(e):
            continue
        a = units['force'] + k * UNIT_STRIDE
        out += [(a + UNIT_MAX_HP, hp.to_bytes(2, 'big')), (a + UNIT_HP, hp.to_bytes(2, 'big')),
                (a + UNIT_MAX_MP, bytes([stat])), (a + UNIT_MP, bytes([stat])),
                (a + UNIT_ATK, bytes([stat, stat, stat])), (a + UNIT_MOV, bytes([move]))]
    if enemy_hp is not None:
        for k, x, y, f, h in read_units(read, units['enemies']):
            if h > enemy_hp and not f & 0x80 and x < 128 and y < 128:
                out.append((units['enemies'] + k * UNIT_STRIDE + UNIT_HP, enemy_hp.to_bytes(2, 'big')))
    return out


def fix_checksum(payload):
    p = bytearray(payload)
    p[0:4] = (len(p) - 8).to_bytes(4, 'big')
    p[4:8] = (sum(p[8:]) & 0xFFFFFFFF).to_bytes(4, 'big')
    return bytes(p)


def with_map(payload, map_id, battle_id=None):
    p = bytearray(payload)
    p[MAP_ID] = map_id & 0xFF
    if battle_id is not None:
        p[BATTLE_ID] = battle_id & 0xFF
    return fix_checksum(p)
