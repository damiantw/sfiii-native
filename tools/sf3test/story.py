"""Story driver support (round 26): story-flag progress, save-record order and the replay segment
format of the acceptance-test replay suite. Pure: no game data, no disc bytes; the runner
(tools/sf3-story.py) needs a built `saturn`, a disc and saves, all outside the repository.

Story flags: save-record bytes 0x240-0x400 (round 19/20: copying them from a later record changes
which doors open; byte 0x3E2 bit 0 is the Saraband intro gate). In work RAM that part of the
record lives at its own base per profile (round 26: found by matching every non-zero word of
0x240-0x400 of a loaded record; the sections before and after it live elsewhere):
  Sc1 USA 0x0602F244, Sc2 V2.000 0x060304C4, Sc2 V1.003 0x06030474, Sc3 0x06030DF4.
A record N+1 is 'reached' from N when every flag bit set in N+1 is set live (a few bits are
cleared again by the story, e.g. the Saraband intro gate; those are reported, not required).

Segment file (text, one per proven or attempted segment; inputs only):
  # comments
  key value                      header: profile, save (file name), record, seed, assist, ...
  input                          then one action per line, in VBlank order:
  V pad BUTTONS                  hold BUTTONS ('' = release) from VBlank V on
  V poke ADDR HEX                write bytes at ADDR before stepping VBlank V (test-only assist)
The run starts at VBlank 1 of `saturn --headless` with the record as the only save (slot 01);
replaying the actions frame for frame reproduces the run (agent-stepped runs are deterministic)."""
import hashlib

FLAG_LO, FLAG_HI = 0x240, 0x400
FLAG_BASE = {
    'scenario1-usa-v25_1': 0x0602F244,
    'scenario2-v25_1-v2_000': 0x060304C4,
    'scenario2-v25_1-v1_003': 0x06030474,
    'scenario3-v25_1-redump': 0x06030DF4,
}
PLAYTIME = 0x10        # u32 play time in frames (60 per second), record payload


def flag_addr(profile):
    return FLAG_BASE[profile] + FLAG_LO


def flags_of(record_data):
    return bytes(record_data[FLAG_LO:FLAG_HI])


def playtime(record_data):
    return int.from_bytes(record_data[PLAYTIME:PLAYTIME + 4], 'big')


def hms(frames):
    s = frames // 60
    return f'{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}'


def bits(b):
    return sum(bin(x).count('1') for x in b)


def compare(live, target):
    """(missing, extra): flag bits set in target but not live, and set live but not in target."""
    missing = sum(bin(t & ~l & 0xFF).count('1') for l, t in zip(live, target))
    extra = sum(bin(l & ~t & 0xFF).count('1') for l, t in zip(live, target))
    return missing, extra


def reached(live, target, allow=0):
    return compare(live, target)[0] <= allow


def story_order(targets):
    """Save targets in story order (record play time), with their play time."""
    return sorted(targets, key=lambda t: playtime(t['record']['data']))


def segment_text(header, actions):
    out = [f'# sf3 story segment v1'] + [f'{k} {v}' for k, v in header.items()] + ['input']
    for a in actions:
        out.append(' '.join(str(x) for x in a))
    return '\n'.join(out) + '\n'


def parse_segment(text):
    header, actions, body = {}, [], False
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        if body:
            p = line.split(' ')
            if p[1] == 'pad':
                actions.append((int(p[0]), 'pad', p[2] if len(p) > 2 else ''))
            elif p[1] == 'poke':
                actions.append((int(p[0]), 'poke', p[2], p[3]))
            else:
                raise ValueError(f'bad action {line!r}')
        elif line == 'input':
            body = True
        else:
            k, _, v = line.partition(' ')
            header[k] = v
    return header, actions


def actions_sha1(actions):
    return hashlib.sha1(segment_text({}, actions).encode()).hexdigest()[:12]


# Committed acceptance segments (tools/story-replays/<key>/*.seg) are pad presses only: no pokes,
# nothing taken from the disc, only these header keys (hash ids, names of the user's own saves,
# seeds and frame counts).
SEGMENT_KEYS = {'profile', 'save', 'record', 'record_sha1', 'seed', 'assist', 'clock', 'load', 'binary',
                'end_vblank', 'end_ram_sha1', 'end_flags_sha1', 'reached', 'title'}
BUTTONS = {'UP', 'DOWN', 'LEFT', 'RIGHT', 'A', 'B', 'C', 'X', 'Y', 'Z', 'L', 'R', 'START'}


def check_committed(text):
    """Problems that keep a segment out of the repository (empty list: fine)."""
    out = []
    try:
        header, actions = parse_segment(text)
    except (ValueError, IndexError) as e:
        return [f'unparsable: {e}']
    for k in header:
        if k not in SEGMENT_KEYS:
            out.append(f'header key {k!r} not allowed')
    if header.get('assist', 'none') != 'none':
        out.append('assisted run (test-only pokes)')
    if not header.get('clock'):
        out.append('no clock (not deterministic)')
    if not header.get('end_ram_sha1') or header.get('end_ram_sha1') == 'None':
        out.append('no end hash')
    last = 0
    for a in actions:
        if a[1] != 'pad':
            out.append(f'VBlank {a[0]}: {a[1]} (pads only)')
            break
        if a[0] < last:
            out.append(f'VBlank {a[0]}: out of order')
            break
        last = a[0]
        bad = [b for b in a[2].split('+') if b and b not in BUTTONS]
        if bad:
            out.append(f'VBlank {a[0]}: unknown buttons {bad}')
            break
    return out
