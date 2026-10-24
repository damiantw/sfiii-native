"""Saturn IP.BIN (the system area's first sectors): reading the header, and the wizard's rewrite.

The wizard decodes every header field as UTF-8, trims it with string.Trim(), changes a few
fields and writes them all back one after another as UTF-8.  Binary fields (IP size, stacks,
first-read address and size) therefore survive only while they contain no bytes that UTF-8
would replace and no whitespace at their ends; the rewrite reproduces that exactly, including
fields that would shift if a re-encoded field came out longer than its slot.
"""
from dataclasses import dataclass

from . import dotnet

# (name, width) in order; None names are skipped bytes.
FIELDS = [("hardware", 16), ("maker", 16), ("product", 10), ("version", 6), ("date", 8),
          ("device", 8), ("areas", 10), (None, 6), ("peripherals", 16), ("title", 112),
          (None, 16), ("ip_size", 4), (None, 4), ("stack_m", 4), ("stack_s", 4),
          ("read_addr", 4), ("read_size", 4), (None, 4), (None, 4)]

SECURITY = [("J", "For JAPAN.                  "), ("T", "For TAIWAN and PHILIPINES.  "),
            ("U", "For USA and CANADA.         "), ("B", "For BRAZIL.                 "),
            ("A", "For ASIA PAL area.          "), ("K", "For KOREA.                  "),
            ("E", "For EUROPE.                 "), ("L", "For LATIN AMERICA.          ")]

# The wizard's fixed values (CDTools.GenerateISO).  The release date is the wizard build's
# date (its assembly "+build" stamp); V25.1's SF3Translation.exe says 2024-08-25.
WIZARD_RELEASE_DATE = "20240825"


@dataclass
class Header:
    hardware: str
    maker: str
    product: str
    version: str
    date: str
    device: str
    areas: str
    peripherals: str
    title: str
    ip_size: str
    stack_m: str
    stack_s: str
    read_addr: str
    read_size: str


def parse(raw):
    """IPBin.Init(): each field UTF-8 decoded and Trim()med."""
    vals, pos = {}, 0
    for name, width in FIELDS:
        if name:
            vals[name] = dotnet.trim(dotnet.utf8_decode(raw[pos:pos + width]))
        pos += width
    return Header(**vals)


def ip_size(raw):
    return int.from_bytes(raw[0xE0:0xE4], "big")


def _field(value, width, maxlen, pad):
    return dotnet.utf8_encode(dotnet.pad_right(dotnet.utf16_sub(value, min(dotnet.utf16_len(value), maxlen)), width, pad))


def serialize(raw, h):
    """IPBin.ToArray(): the header fields written back over a copy of the raw sectors."""
    buf = bytearray(raw)
    out = bytearray()
    out += _field(h.hardware, 16, 16, " ")
    out += _field(h.maker, 16, 16, " ")
    out += _field(h.product, 10, 10, " ")
    out += _field(h.version, 6, 6, " ")
    out += _field(h.date, 8, 9, " ")       # the wizard keeps up to 9 characters here
    out += _field(h.device, 8, 8, " ")
    out += _field(h.areas, 10, 10, " ")
    out += b" " * 6
    out += _field(h.peripherals, 16, 16, " ")
    out += _field(h.title, 112, 112, " ")
    out += b"\0" * 16
    out += _field(h.ip_size, 4, 4, "\0")
    out += b"\0" * 4
    out += _field(h.stack_m, 4, 4, "\0")
    out += _field(h.stack_s, 4, 4, "\0")
    out += _field(h.read_addr, 4, 4, "\0")
    out += _field(h.read_size, 4, 4, "\0")
    out += b"\0" * 8
    if len(out) > len(buf):
        buf.extend(bytes(len(out) - len(buf)))
    buf[0:len(out)] = out
    area = bytearray()
    for code, text in SECURITY:
        if code in h.areas:
            area += (150998688).to_bytes(4, "little") + text.encode("latin-1")
    area += (725615056).to_bytes(4, "little") + (150997248).to_bytes(4, "little") + (4194310).to_bytes(4, "little")
    end = 0xE00 + len(area)
    if end > len(buf):
        buf.extend(bytes(end - len(buf)))
    buf[0xE00:end] = area
    return bytes(buf)


def wizard_header(h, version, release_date=WIZARD_RELEASE_DATE):
    """The header fields after the wizard's edits; `version` is data.json's "version"."""
    title = (dotnet.utf16_sub(dotnet.pad_right(h.title, 32), 32) + dotnet.pad_right("TRANSLATION", 16)
             + dotnet.pad_right("VERSION %s" % version, 16) + "SF3TRANS.SHININGFORCECENTRAL.COM")
    return Header(hardware=h.hardware, maker=h.maker, product="SF3TRANS", version="V%s" % version,
                  date=release_date, device=h.device, areas="JTUBKAEL", peripherals="AJE",
                  title=title, ip_size=h.ip_size, stack_m=h.stack_m, stack_s=h.stack_s,
                  read_addr=h.read_addr, read_size=h.read_size)


def wizard_rewrite(raw, version, release_date=WIZARD_RELEASE_DATE):
    return serialize(raw, wizard_header(parse(raw), version, release_date))
