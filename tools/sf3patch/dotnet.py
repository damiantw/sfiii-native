"""Small, behaviour-level models of the .NET runtime facilities the wizard relies on.

Only what changes bytes or ordering is modelled: string trimming and UTF-8 round trips, the
culture-aware string comparison used to break priority ties, List<T>.Sort's introspective sort
(which is not stable, so equal elements end up wherever .NET would put them) and the order in
which NTFS lists directory entries.
"""
import unicodedata

# char.IsWhiteSpace, which string.Trim() uses (Unicode White_Space).  Python's str.strip()
# also strips U+001C..U+001F, which .NET keeps, so it must not be used for wizard semantics.
WHITESPACE = frozenset("\t\n\v\f\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
                       "\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000")
# Characters NumberStyles.AllowLeading/TrailingWhite skip when parsing numbers.
NUMBER_WHITESPACE = frozenset("\t\n\v\f\r ")


def trim(s, chars=WHITESPACE):
    """string.Trim()."""
    i, j = 0, len(s)
    while i < j and s[i] in chars:
        i += 1
    while j > i and s[j - 1] in chars:
        j -= 1
    return s[i:j]


def utf8_decode(data):
    """Encoding.UTF8.GetString: invalid sequences become U+FFFD (maximal-subpart rule)."""
    return data.decode("utf-8", errors="replace")


def utf16_len(s):
    """string.Length counts UTF-16 code units."""
    return sum(2 if ord(c) > 0xFFFF else 1 for c in s)


def utf16_sub(s, length):
    """s.Substring(0, length) by UTF-16 code units.  A split surrogate pair encodes as U+FFFD."""
    out, n = [], 0
    for c in s:
        w = 2 if ord(c) > 0xFFFF else 1
        if n + w > length:
            if n < length:  # half of a surrogate pair survives; UTF-8 encodes it as U+FFFD
                out.append("\ufffd")
            break
        out.append(c)
        n += w
    return "".join(out)


def pad_right(s, width, ch=" "):
    return s + ch * max(0, width - utf16_len(s))


def utf8_encode(s):
    return s.encode("utf-8", errors="replace")


def parse_hex_int(text):
    """int.Parse(text, NumberStyles.HexNumber) for a 32-bit int.  Raises ValueError."""
    t = trim(text, NUMBER_WHITESPACE)
    if not t or any(c not in "0123456789abcdefABCDEF" for c in t):
        raise ValueError("Input string was not in a correct format: %r" % text)
    v = int(t, 16)
    if v > 0xFFFFFFFF:
        raise ValueError("Value was either too large or too small for an Int32: %r" % text)
    return v - (1 << 32) if v & 0x80000000 else v


def parse_hex_byte(text):
    """byte.Parse(text, NumberStyles.HexNumber)."""
    t = trim(text, NUMBER_WHITESPACE)
    if not t or any(c not in "0123456789abcdefABCDEF" for c in t):
        raise ValueError("Input string was not in a correct format: %r" % text)
    v = int(t, 16)
    if v > 0xFF:
        raise ValueError("Value was either too large or too small for a byte: %r" % text)
    return v


# ---------------------------------------------------------------- culture string comparison
#
# string.CompareTo is culture sensitive.  .NET 5 on current Windows uses ICU, whose root
# collation (CLDR) puts whitespace, then punctuation, symbols, currency, digits and letters,
# compares letters case-insensitively first and only then prefers lowercase.  Patch names are
# ASCII; anything else falls back to code point order after the letters.

_VARIABLE = " _-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"
_PRIMARY = {c: i for i, c in enumerate(_VARIABLE)}
for _i, _c in enumerate("0123456789"):
    _PRIMARY[_c] = 100 + _i
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _PRIMARY[_c] = 200 + _i
    _PRIMARY[_c.upper()] = 200 + _i


def _keys(s):
    primary, tertiary = [], []
    for c in unicodedata.normalize("NFD", s):
        if unicodedata.combining(c):
            continue  # accents only matter at the secondary level; ignored here
        p = _PRIMARY.get(c)
        if p is None:
            p = 1000 + ord(c.lower())
        primary.append(p)
        tertiary.append(1 if c.isupper() else 0)
    return primary, tertiary


def culture_compare(a, b):
    """Sign of a.CompareTo(b) under an ICU-like en-US collation (-1, 0 or 1)."""
    if a is None or b is None:
        if a is None:
            raise TypeError("NullReferenceException: string.CompareTo on a null patch name")
        return 1  # "x".CompareTo(null) == 1
    pa, ta = _keys(a)
    pb, tb = _keys(b)
    if pa != pb:
        return -1 if pa < pb else 1
    if ta != tb:
        return -1 if ta < tb else 1
    return 0


# ---------------------------------------------------------------- List<T>.Sort(Comparison<T>)

def introsort(items, cmp):
    """Sort `items` in place exactly as .NET 5's ArraySortHelper<T>.IntrospectiveSort does."""
    n = len(items)
    if n > 1:
        _intro(items, 0, n, 2 * (n.bit_length() - 1 + 1), cmp)
    return items


def _swap_if_greater(a, cmp, i, j):
    if cmp(a[i], a[j]) > 0:
        a[i], a[j] = a[j], a[i]


def _intro(a, lo, size, depth, cmp):
    while size > 1:
        if size <= 16:
            if size == 2:
                _swap_if_greater(a, cmp, lo, lo + 1)
                return
            if size == 3:
                _swap_if_greater(a, cmp, lo, lo + 1)
                _swap_if_greater(a, cmp, lo, lo + 2)
                _swap_if_greater(a, cmp, lo + 1, lo + 2)
                return
            _insertion(a, lo, size, cmp)
            return
        if depth == 0:
            _heapsort(a, lo, size, cmp)
            return
        depth -= 1
        p = _partition(a, lo, size, cmp)
        _intro(a, lo + p + 1, size - (p + 1), depth, cmp)
        size = p


def _partition(a, lo, size, cmp):
    hi = size - 1
    mid = hi >> 1
    _swap_if_greater(a, cmp, lo, lo + mid)
    _swap_if_greater(a, cmp, lo, lo + hi)
    _swap_if_greater(a, cmp, lo + mid, lo + hi)
    pivot = a[lo + mid]
    a[lo + mid], a[lo + hi - 1] = a[lo + hi - 1], a[lo + mid]
    left, right = 0, hi - 1
    while left < right:
        left += 1
        while cmp(a[lo + left], pivot) < 0:
            left += 1
        right -= 1
        while cmp(pivot, a[lo + right]) < 0:
            right -= 1
        if left >= right:
            break
        a[lo + left], a[lo + right] = a[lo + right], a[lo + left]
    if left != hi - 1:
        a[lo + left], a[lo + hi - 1] = a[lo + hi - 1], a[lo + left]
    return left


def _insertion(a, lo, size, cmp):
    for i in range(size - 1):
        t = a[lo + i + 1]
        j = i
        while j >= 0 and cmp(t, a[lo + j]) < 0:
            a[lo + j + 1] = a[lo + j]
            j -= 1
        a[lo + j + 1] = t


def _heapsort(a, lo, n, cmp):
    for i in range(n >> 1, 0, -1):
        _down_heap(a, lo, i, n, cmp)
    for i in range(n, 1, -1):
        a[lo], a[lo + i - 1] = a[lo + i - 1], a[lo]
        _down_heap(a, lo, 1, i - 1, cmp)


def _down_heap(a, lo, i, n, cmp):
    d = a[lo + i - 1]
    while i <= n >> 1:
        child = 2 * i
        if child < n and cmp(a[lo + child - 1], a[lo + child]) < 0:
            child += 1
        if not cmp(d, a[lo + child - 1]) < 0:
            break
        a[lo + i - 1] = a[lo + child - 1]
        i = child
    a[lo + i - 1] = d


def ntfs_key(name):
    """Directory.GetDirectories/GetFiles order on NTFS: ordinal over the volume's upcase table."""
    out = []
    for c in name:
        u = c.upper()
        c = u if len(u) == 1 else c
        o = ord(c)
        if o > 0xFFFF:  # compared as a surrogate pair
            o -= 0x10000
            out += [0xD800 + (o >> 10), 0xDC00 + (o & 0x3FF)]
        else:
            out.append(o)
    return out
