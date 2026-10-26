"""DFR byte patches: the translation project's text patch format.

A DFR file is applied line by line to one disc file.  Each line, after anything from the
first ';' is dropped, is `offset,old,new`: hexadecimal offset, then the expected original
bytes and the replacement bytes as hex pairs.  The wizard's quirks are reproduced:

* `offset,` (two fields) truncates the file to `offset` bytes and stops reading the patch;
* an empty `old` appends `new` at the end of the file, first padding with zeros up to
  `offset` when the file is shorter (an offset inside the file still appends at the end);
* bytes past the end of the file are appended without being checked;
* every other byte must equal `old` or the whole patch fails, as in the wizard;
* odd trailing hex digits are ignored, and whitespace inside a pair is tolerated where
  byte.Parse tolerates it.
"""
from dataclasses import dataclass, field

from . import dotnet


class DFRError(ValueError):
    pass


@dataclass
class Op:
    line: int        # 1-based line number, counting every line like the wizard
    offset: int
    kind: str        # 'replace', 'append' or 'truncate'
    old: bytes = b""
    new: bytes = b""


@dataclass
class Patch:
    name: str
    ops: list = field(default_factory=list)

    def touched(self, size):
        """Byte ranges [start, end) this patch writes when applied to a file of `size` bytes,
        plus 'truncate'/'append' markers.  Used for conflict detection."""
        out = []
        for op in self.ops:
            if op.kind == "replace":
                out.append((op.offset, op.offset + len(op.new)))
            elif op.kind == "append":
                out.append(("append", op.offset))
            else:
                out.append(("truncate", op.offset))
        return out


def _decode(data):
    """StreamReader's default: UTF-8, honouring a UTF-8/UTF-16/UTF-32 byte order mark."""
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe\x00\x00", "utf-32-le"),
                     (b"\x00\x00\xfe\xff", "utf-32-be"), (b"\xff\xfe", "utf-16-le"),
                     (b"\xfe\xff", "utf-16-be")):
        if data.startswith(bom):
            return data[len(bom):].decode(enc, errors="replace")
    return dotnet.utf8_decode(data)


def _lines(text):
    """StreamReader.ReadLine: \\r, \\n and \\r\\n end a line; a final terminator adds no line."""
    out, i, n = [], 0, len(text)
    while i < n:
        j = i
        while j < n and text[j] not in "\r\n":
            j += 1
        out.append(text[i:j])
        if j < n and text[j] == "\r" and j + 1 < n and text[j + 1] == "\n":
            j += 1
        i = j + 1
    return out


def _pairs(chars, name, line):
    out = bytearray()
    for k in range(len(chars) // 2):
        try:
            out.append(dotnet.parse_hex_byte(chars[2 * k] + chars[2 * k + 1]))
        except ValueError as e:
            raise DFRError("%s line %d: %s" % (name, line, e)) from None
    return bytes(out)


def parse(data, name="patch"):
    """Parse DFR bytes into a Patch.  Raises DFRError where the wizard would throw."""
    patch = Patch(name)
    for num, raw in enumerate(_lines(_decode(data)), 1):
        text = (raw + ";")[: (raw + ";").index(";")]
        if not dotnet.trim(text):
            continue
        fields = text.split(",")
        try:
            offset = dotnet.parse_hex_int(fields[0])
        except ValueError as e:
            raise DFRError("%s line %d: bad offset: %s" % (name, num, e)) from None
        if len(fields) < 2:
            raise DFRError("%s line %d: missing old bytes (Index was outside the bounds of the array)" % (name, num))
        old = dotnet.trim(fields[1])
        if len(fields) <= 2:
            patch.ops.append(Op(num, offset, "truncate"))
            break  # the wizard stops reading here
        new = dotnet.trim(fields[2])
        if not old:
            patch.ops.append(Op(num, offset, "append", b"", _pairs(new, name, num)))
            continue
        if len(old) != len(new):
            raise DFRError("Error with patch file %s.\nLengths are different. (line %d)" % (name, num))
        patch.ops.append(Op(num, offset, "replace", _pairs(old, name, num), _pairs(new, name, num)))
    return patch


def apply(patch, data, target="file"):
    """Apply a parsed patch to bytes; returns the new bytes or raises DFRError."""
    buf = bytearray(data)
    for op in patch.ops:
        if op.offset < 0:
            raise DFRError("%s line %d: negative offset" % (patch.name, op.line))
        if op.kind == "truncate":
            if op.offset > len(buf):
                raise DFRError("%s line %d: cannot truncate %s (%d bytes) to %d bytes"
                               % (patch.name, op.line, target, len(buf), op.offset))
            del buf[op.offset:]
            break
        if op.kind == "append":
            if len(buf) <= op.offset:
                buf.extend(bytes(op.offset - len(buf)))
            buf.extend(op.new)
            continue
        for j, (b, b2) in enumerate(zip(op.old, op.new)):
            pos = op.offset + j
            if len(buf) <= pos:
                buf.append(b2)
                continue
            if buf[pos] != b:
                raise DFRError("Error with patch file %s.\nOld value %X is different than %X on line %d(%X)."
                               % (target, b, buf[pos], op.line, op.offset))
            buf[pos] = b2
    return bytes(buf)


def check(patch, data):
    """Every byte mismatch (offset, expected, found) without stopping at the first one."""
    bad = []
    size = len(data)
    for op in patch.ops:
        if op.kind != "replace":
            continue
        for j, b in enumerate(op.old):
            pos = op.offset + j
            if pos < size and data[pos] != b:
                bad.append((pos, b, data[pos], op.line))
    return bad
