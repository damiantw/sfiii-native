"""A reader for the JSON dialect Newtonsoft.Json (JsonConvert.DeserializeObject) accepts.

The wizard's metadata.json files are read by Newtonsoft, which is far more lenient than
RFC 8259: comments, single-quoted strings, unquoted property names, trailing commas, raw
control characters inside strings, and -- the one that matters for real packages -- numbers
with a leading zero are octal ("040" is 32, "009" is an error).  Python's json module rejects
several shipped metadata files, so this module reads them the way the wizard does.
"""
from . import dotnet


class JsonError(ValueError):
    pass


class Undefined:
    """JavaScript `undefined`, which Newtonsoft reads as a JValue of type Undefined."""

    def __repr__(self):
        return "undefined"


UNDEFINED = Undefined()

_NUMBER_CHARS = set("0123456789.eE+-xXabcdefABCDEF")
_IDENT_EXTRA = set("_$")


class _Reader:
    def __init__(self, text):
        self.s = text
        self.i = 0

    def error(self, msg):
        line = self.s.count("\n", 0, self.i) + 1
        raise JsonError("%s (line %d, position %d)" % (msg, line, self.i))

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def skip(self):
        s = self.s
        while self.i < len(s):
            c = s[self.i]
            if c in dotnet.WHITESPACE or c == "\ufeff":
                self.i += 1
            elif s.startswith("//", self.i):
                j = self.i
                while j < len(s) and s[j] not in "\r\n":
                    j += 1
                self.i = j
            elif s.startswith("/*", self.i):
                j = s.find("*/", self.i + 2)
                if j < 0:
                    self.error("Unexpected end while parsing comment")
                self.i = j + 2
            else:
                break

    def value(self):
        self.skip()
        c = self.peek()
        if c == "{":
            return self.obj()
        if c == "[":
            return self.arr()
        if c in "\"'":
            return self.string()
        if c and (c in "0123456789-" or c == "."):
            return self.number()
        for word, val in (("true", True), ("false", False), ("null", None),
                          ("undefined", UNDEFINED), ("NaN", float("nan")),
                          ("Infinity", float("inf"))):
            if self.s.startswith(word, self.i):
                self.i += len(word)
                return val
        if c == "":
            self.error("Unexpected end when reading JSON")
        self.error("Unexpected character encountered while parsing value: %s" % c)

    def obj(self):
        self.i += 1
        out = {}
        while True:
            self.skip()
            c = self.peek()
            if c == "}":
                self.i += 1
                return out
            if c in "\"'":
                key = self.string()
            else:
                j = self.i
                while self.i < len(self.s) and (self.s[self.i].isalnum() or self.s[self.i] in _IDENT_EXTRA):
                    self.i += 1
                if j == self.i:
                    self.error("Invalid property identifier character: %s" % (c or "EOF"))
                key = self.s[j:self.i]
            self.skip()
            if self.peek() != ":":
                self.error("Invalid character after parsing property name. Expected ':'")
            self.i += 1
            out[key] = self.value()  # duplicate names: the last one wins, like JObject
            self.skip()
            c = self.peek()
            if c == ",":
                self.i += 1
            elif c == "}":
                self.i += 1
                return out
            else:
                self.error("After parsing a value an unexpected character was encountered: %s" % (c or "EOF"))

    def arr(self):
        self.i += 1
        out = []
        while True:
            self.skip()
            if self.peek() == "]":
                self.i += 1
                return out
            out.append(self.value())
            self.skip()
            c = self.peek()
            if c == ",":
                self.i += 1
            elif c == "]":
                self.i += 1
                return out
            else:
                self.error("After parsing a value an unexpected character was encountered: %s" % (c or "EOF"))

    def string(self):
        quote = self.s[self.i]
        self.i += 1
        out = []
        s = self.s
        while True:
            if self.i >= len(s):
                self.error("Unterminated string. Expected delimiter: %s" % quote)
            c = s[self.i]
            self.i += 1
            if c == quote:
                return "".join(out)
            if c != "\\":
                out.append(c)
                continue
            if self.i >= len(s):
                self.error("Unterminated string")
            e = s[self.i]
            self.i += 1
            simple = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r",
                      "\\": "\\", "/": "/", '"': '"', "'": "'"}
            if e in simple:
                out.append(simple[e])
            elif e == "u":
                h = s[self.i:self.i + 4]
                if len(h) < 4 or any(x not in "0123456789abcdefABCDEF" for x in h):
                    self.error("Invalid Unicode escape sequence")
                out.append(chr(int(h, 16)))
                self.i += 4
            else:
                self.error("Bad JSON escape sequence: \\%s" % e)

    def number(self):
        j = self.i
        while self.i < len(self.s) and self.s[self.i] in _NUMBER_CHARS:
            self.i += 1
        text = self.s[j:self.i]
        if text == "-" and self.s.startswith("Infinity", self.i):
            self.i += len("Infinity")
            return float("-inf")
        first = text[0]
        if first == "0" and len(text) > 1 and text[1] not in ".eE":
            # Newtonsoft: a leading zero means hexadecimal ("0x1F") or octal ("040").
            try:
                if text[1] in "xX":
                    return int(text[2:], 16)
                return int(text, 8)
            except ValueError:
                self.error("Input string '%s' is not a valid number" % text)
        try:
            if any(c in text for c in ".eE"):
                return float(text)
            return int(text, 10)
        except ValueError:
            self.error("Input string '%s' is not a valid number" % text)


def loads(text):
    """Parse like JsonConvert.DeserializeObject(text): one value, then only whitespace/comments."""
    r = _Reader(text)
    v = r.value()
    r.skip()
    if r.i != len(r.s):
        r.error("Additional text encountered after finished reading JSON content: %s" % r.peek())
    return v


def read_text(data):
    """File.ReadAllText: UTF-8 unless a BOM says otherwise; the BOM is dropped."""
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe\x00\x00", "utf-32-le"),
                     (b"\x00\x00\xfe\xff", "utf-32-be"), (b"\xff\xfe", "utf-16-le"),
                     (b"\xfe\xff", "utf-16-be")):
        if data.startswith(bom):
            return data[len(bom):].decode(enc, errors="replace")
    return dotnet.utf8_decode(data)


# ---------------------------------------------------------------- dynamic conversions
# What `ListBoxModel { Text = val.text, Enabled = val.enabled, Priority = val.priority ?? 9999 }`
# does with each JSON value.  `MISSING` is a property that is not there (C# null).

MISSING = object()


def to_net_string(v):
    """(string)JToken, also what JValue.ToString() gives for scalars."""
    if v is MISSING or v is None or v is UNDEFINED:
        return None
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        return repr(v) if v != int(v) else str(int(v))
    if isinstance(v, (dict, list)):
        raise JsonError("Can not convert Object/Array to String")
    return str(v)


def to_net_bool(v):
    if v is MISSING:
        raise JsonError("Cannot convert null to 'bool' because it is a non-nullable value type")
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        t = dotnet.trim(v).lower()
        if t in ("true", "false"):
            return t == "true"
        raise JsonError("String '%s' was not recognized as a valid Boolean." % v)
    raise JsonError("Can not convert %r to Boolean." % (v,))


def to_net_int(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        if not -2**31 <= v < 2**31:
            raise JsonError("Value was either too large or too small for an Int32.")
        return v
    if isinstance(v, float):
        return to_net_int(round(v))  # Convert.ToInt32(double) rounds half to even
    if isinstance(v, str):
        t = dotnet.trim(v, dotnet.NUMBER_WHITESPACE)
        try:
            return to_net_int(int(t, 10))
        except ValueError:
            raise JsonError("Input string was not in a correct format.") from None
    raise JsonError("Can not convert %r to Int32." % (v,))


def category_string(v):
    """val.category.ToString(): a missing property throws (null.ToString())."""
    if v is MISSING:
        raise JsonError("Cannot perform runtime binding on a null reference")
    if isinstance(v, (dict, list)):
        import json
        return json.dumps(v, indent=2)
    return to_net_string(v) or ""
