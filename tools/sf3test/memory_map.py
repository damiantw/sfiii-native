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

PROFILES = {
    # profile id: (scenario, state_base, tick)  tick: u32 the game adds one to each frame it runs
    'scenario1-usa-v25_1': (1, 0x06090FE0, 0x0601FC68),
    'scenario2-v25_1-v2_000': (2, 0x06090578, None),
    'scenario2-v25_1-v1_003': (2, 0x0609056C, None),
    'scenario3-v25_1-redump': (3, 0x0609075C, None),
}


def lookup(profile):
    profile = profile[:-5] if profile.endswith('.json') else profile
    if profile not in PROFILES:
        raise KeyError(f'no SF3 memory map for profile {profile}')
    scenario, base, tick = PROFILES[profile]
    return dict(profile=profile, scenario=scenario, state_base=base, tick=tick,
                map_id=base + MAP_ID, battle_id=base + BATTLE_ID, prev_map=base + PREV_MAP)


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
