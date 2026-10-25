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
# Sc1 town scenes (round 15, sc1-usa b92d515b, read from our generated code for X002/X008 and
# checked live over the agent socket on save 1:30). The scene loader (X002 06 02AD00, reached through
# the X002 vector at 0602880C with r4 = mode) takes the scene index from the halfword at
# state+0x10 (the harness's map id), indexes a table of 16-byte records (pointer at TABLE_PTR) and
# loads record+2 (a file index = position in the disc's sorted root directory) to 0605F000 when it
# differs from the overlay loaded (FID_LOADED). The town engine X008 looks the player's tile up in a
# 64x64 byte map at 060B8000 (x and z 16.16 fixed >> 21, high nibble 1, 2 or 5 = an event kind,
# low nibble its id, written to the event block that 0602886C points to: kind 2 -> +0, 1 -> +4, 5 -> +28).
# Checked live (1:30, after the HQ talk): writing 1 to event+4 (the HQ exit tile's kind-1 id) takes the
# game out of the door to scene 86 (X1OBCHUR, Quonus outside), the same as walking onto the tile.
# Re-pointing state+0x10 to a scene on another map (41 Saraband, 56 shop) during that exit loads
# the new overlay file but stays black, polling BOOT 060125E0 (a test-made state, not a port result).
# The scene record's file id counts the ISO directory's '.' and '..' entries: the file is row fid-2 of
# stage/inventory.csv (checked against RAM: scene 51, fid 0x1EF, is X1SARA4, not row 0x1EF X1SARA6).
# Rounds 15-19 named scenes by row fid; those names were two rows off. The shop and bar files by fid:
SC1_SCENES = dict(table_ptr=0x0602DA74, fid_loaded=0x0602E8E4, tile_map=0x060B8000, event_ptr=0x0602886C, exit_event=4,
                  record=16, overlay_base=0x0605F000, fid_row_offset=2,
                  shop_fids={0x202: 'X1S_SHOP', 0x17B: 'X1BAR01', 0x1F7: 'X1SHOP_T'})


def fid_file(fid, inventory_paths, offset=2):
    """The file a scene record's file id names, from stage/inventory.csv's paths in order."""
    return inventory_paths[fid - offset].strip('/')


def overlay_file(ram, build):
    """The X*.BIN file of BUILD/stage/extract whose bytes are resident at the start of RAM (bytes read at
    the overlay base), or None: the ground truth for which overlay a coverage hit belongs to."""
    import glob, os
    best = None
    for p in glob.glob(os.path.join(build, 'stage', 'extract', 'X*.BIN')):
        data = open(p, 'rb').read()
        if len(data) <= len(ram) and ram[:len(data)] == data and (best is None or len(data) > best[0]):
            best = (len(data), os.path.basename(p))
    return best and best[1]


def scene_records(raw, record=16):
    """[(index, map, fid)] from the bytes of the scene table."""
    out = []
    for i in range(len(raw) // record):
        e = raw[i * record:(i + 1) * record]
        out.append((i, int.from_bytes(e[0:2], 'big'), int.from_bytes(e[2:4], 'big')))
    return out


def tile_events(tiles):
    """{(x, z): (kind, id)} for the event tiles of a 64x64 tile map."""
    return {(i % 64, i // 64): (b >> 4, b & 15) for i, b in enumerate(tiles) if b >> 4 in (1, 2, 5)}


# Sc1 town player (found with SF3_CALL_TRACE=06056DF0: the tile-event lookup's only caller, 06056C1C,
# passes obj+12 / obj+20 of the object at @(r15+60)). Checked live at 1:30 outside HQ (scene 86):
# the pad moves these (DOWN +x, UP -x, LEFT -z, RIGHT +z, about 4 units a frame) and a poke sticks.
# 16.16 fixed point; the lookup's tile is value >> 21 (32 units a tile). In HQ (scene 89) the slot is 0.
SC1_PLAYER = dict(obj=0x06044844, x=12, z=20, tile_shift=21)

# Kind-2 tile ids (event slot +0) in scene 51 (fid 0x1EF, X1SARA4 Saraband) are door triggers that
# fire on a walked tile change (poking the slot or warping onto the tile does not fire them).
# Found by walking (sf3-town-bfs) and assist warps next to each door, save record :03; files are
# the resident overlay (fid - 2 rows), not the round-18 names. None: shut at that point of the story.
# Under later story flags the town is scene 41 and door 6 opens into X1BAR01 (scene 45, fid 0x17B),
# door 12 (26,37) into X1S_SHOP (scene 47, fid 0x202).
SC1_SCENE51_DOORS = {
    2: 44,     # (36,38) church, X1CHUR01 (fid 0x1B0)
    7: 43,     # north edge near (45-47,19): X1SARA3 (fid 0x1EE), then 52 X1SARA5 (fid 0x1F0)
    6: None,   # (44,31) the bar; its keeper blocks the door this early
    12: None,  # (26,37) the shop
    5: None, 9: None, 13: None,
}
SC1_SCENE51_EXITS = {10: 7}  # kind-1 slot +4 id 10: leave town to scene 7 (fid 0x184, X1BTL102)
# Saraband story gate (round 20 bisection, binary d3887ed2): record byte 0x3E2 bit 0
# (RAM SC1 save mirror + 0x3E2).  Set (live value 0x07) while the opening Saraband
# sequence runs, and the town loads as scene 51 (X1SARA4: bar keeper blocks door 6,
# shop door 12 shut).  Clear it inside the church (scene 44) and walk out: the town
# reloads as scene 41 (X1SARA2) and tile (26,37) UP enters scene 47 (X1S_SHOP).
# Copying record bytes 0x3C0-0x3D0 from a later save instead sends the story back to
# scene 6 (X1BTL101).  Labelled assist only; never a route for the regular playtests.
SC1_SARABAND_INTRO_FLAG = (0x3E2, 0x01)


def player_tile(x_raw, z_raw, shift=21):
    """The tile (x, z) the town lookup 06056DF0 indexes for the player's 16.16 position."""
    def t(v):
        v -= (1 << 32) if v & 0x80000000 else 0
        return (v >> shift) & 63
    return t(x_raw), t(z_raw)


BATTLE_UNITS = {'scenario1-usa-v25_1': dict(enemies=0x0602F6F0, force=0x06032030)}
# Round 13 (sc2-2.000 58271484, sc3 0e80231f; black-box, same method: scan work RAM for named
# records at stride 0xB0 in a Ch1 battle, then read them against the status window: Sc2 Ch1 :01
# Campbell 12/13, Sc3 Ch1 :01 Julian 52/52). Same layout, enemies again 60 records before the
# force table, but the force table is the whole roster (every scenario's characters) and the 0x80/0x40
# flag byte is stale there (Sc3 Julian on the field reads 0x00, benched Medion 0xE0). The on-field
# test that holds in both: u8 at +0x98 (2 in Sc2, 3 in Sc3, 0 when benched) and u8 at +0x99 (1 while
# alive) both non-zero ('live'). Sc3 names past the Sc3 cast are still Japanese (bytes >= 0xA0).
BATTLE_UNITS.update({
    'scenario2-v25_1-v2_000': dict(enemies=0x06030970, force=0x060332B0, live=0x98),
    'scenario3-v25_1-redump': dict(enemies=0x060312A0, force=0x06033BE0, live=0x98),
})

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


def on_field(rec, live=None):
    """Sc1: flag 0x40. With `live` (Sc2/Sc3): the bytes at live and live+1 both non-zero."""
    # Sc2: the enemy table also holds max-HP-1, MOV-0 placeholder records (map objects?) that stay
    # 'live' all battle; they are not units
    if live:
        return bool(rec[live] and rec[live + 1]) and int.from_bytes(rec[UNIT_MAX_HP:UNIT_MAX_HP + 2], 'big') > 1
    return bool(rec[UNIT_FLAGS] & UNIT_ON_FIELD)


def read_units(read, table, live=None):
    """[(slot, x, y, flags, hp)] for the on-field records of a unit table; `read(addr, n)`."""
    raw = read(table, UNIT_STRIDE * UNIT_COUNT)
    out = []
    for k in range(UNIT_COUNT):
        e = raw[k * UNIT_STRIDE:(k + 1) * UNIT_STRIDE]
        if on_field(e, live):
            out.append((k, e[UNIT_X], e[UNIT_Y], e[UNIT_FLAGS], int.from_bytes(e[UNIT_HP:UNIT_HP + 2], 'big')))
    return out


def looks_like_force(rec, live=None):
    """A force record starts with its name (printable ASCII, NUL-padded) and has flag 0x80; other
    battles may put their tables elsewhere (round 12: Sc1 Battle 30 does), so check before a poke."""
    name = rec[:12].rstrip(b'\0 ')
    if live:  # roster tables: ASCII or Japanese (>= 0xA0) names, flags unused
        return bool(name) and all(32 <= c < 127 or c >= 0xA0 for c in name) and \
            rec[UNIT_X] < 128 and rec[UNIT_Y] < 128
    return bool(name) and all(32 <= c < 127 for c in name) and bool(rec[UNIT_FLAGS] & 0x80)


def assist_writes(read, units, enemy_hp=None, hp=999, stat=99, move=12):
    """Test-only assist (never on by default): [(addr, bytes)] that give every on-field force unit
    `hp` HP and max HP, full MP and `stat` attack/defence/agility, `move` movement, and, with
    `enemy_hp`, every on-field enemy with more HP than that `enemy_hp`. Nothing for an empty table."""
    out = []
    raw = read(units['force'], UNIT_STRIDE * UNIT_COUNT)
    for k in range(UNIT_COUNT):
        e = raw[k * UNIT_STRIDE:(k + 1) * UNIT_STRIDE]
        if not on_field(e, units.get('live')) or not looks_like_force(e, units.get('live')):
            continue
        a = units['force'] + k * UNIT_STRIDE
        out += [(a + UNIT_MAX_HP, hp.to_bytes(2, 'big')), (a + UNIT_HP, hp.to_bytes(2, 'big')),
                (a + UNIT_MAX_MP, bytes([stat])), (a + UNIT_MP, bytes([stat])),
                (a + UNIT_ATK, bytes([stat, stat, stat])), (a + UNIT_MOV, bytes([move]))]
    if enemy_hp is not None:
        for k, x, y, f, h in read_units(read, units['enemies'], units.get('live')):
            if h > enemy_hp and (units.get('live') or not f & 0x80) and x < 128 and y < 128:
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
