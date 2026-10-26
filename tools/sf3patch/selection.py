"""Which patches the wizard lists for a disc, in which order, and which are ticked.

PreparePatches builds four lists (General, BugFixes, QoL, Mods) from every patch folder that
has files for the disc, sorts each with List.Sort and a comparer that orders by priority and
breaks ties by the culture-sensitive comparison of the patch's "text"; patches are then
applied in that list order.  List.Sort is an unstable introsort, so it is reproduced exactly
(dotnet.introsort) instead of using Python's stable sort.
"""
from . import dotnet
from .package import CATEGORIES, PackageError


def _compare(x, y):
    if x.priority == y.priority:
        return dotnet.culture_compare(x.text, y.text)
    return x.priority - y.priority


def listed(patches, serial, version):
    """(ordered list of every patch the wizard shows for this disc, errors)."""
    errors = []
    groups = {c: [] for c in CATEGORIES}
    for p in patches:
        if not p.applies_to(serial, version):
            continue
        if p.meta_error:
            errors.append(p.meta_error)
            continue
        if p.category in groups:
            groups[p.category].append(p)
    out = []
    for c in CATEGORIES:
        lst = groups[c]
        dotnet.introsort(lst, _compare)
        out.extend(lst)
    return out, errors


def _match(patches, name):
    key = name.strip().lower()
    hits = [p for p in patches if p.label.lower() == key]
    if not hits:
        hits = [p for p in patches if p.name.lower() == key]
    if not hits:
        hits = [p for p in patches if (p.title or "").lower() == key]
    if not hits:
        raise PackageError("no patch named %r for this disc (see `sf3patch list`)" % name)
    if len(hits) > 1:
        raise PackageError("%r matches several patches: %s; use the SOURCE/FOLDER form"
                           % (name, ", ".join(p.label for p in hits)))
    return hits[0]


def choose(ordered, enable=(), disable=(), only=None):
    """The ticked patches in wizard order.  Defaults come from metadata.json; --enable,
    --disable and --only change ticks without changing the order, as clicking does."""
    state = {id(p): p.enabled for p in ordered}
    if only is not None:
        state = {k: False for k in state}
        for n in only:
            state[id(_match(ordered, n))] = True
    for n in enable:
        state[id(_match(ordered, n))] = True
    for n in disable:
        state[id(_match(ordered, n))] = False
    return [p for p in ordered if state[id(p)]]


# Newer add-on releases on the project's V25+ page that replace a patch of the base package
# (same change, newer version).  Applying both would fail the second patch's byte checks, so
# `--latest` drops the old folders.  Keys are the new folder names, values the old ones.
SUPERSEDES = {
    "Blacksmith Interface Update v3.1": ["Blacksmith Interface Update v2.02"],
    "Blacksmith Results v2.1": ["Blacksmith Results v1.4"],
    "Critical and Counter Fix v1.11": ["Critical and Counter Fix"],
    "Irene Insane Buff 1.02": ["Irene Insane Buff"],
    "Rogan Sprite Fix v5": ["Rogan Sprite Fix"],
}


# Add-ons whose metadata ticks them but which are an alternative to other ticked add-ons.
# Magic Resistance Icons v2 rewrites the same X017.BIN bytes as Mod Essentials 0.5.1 and
# Elemental Icons 3.0 (which stack with each other), so with all three ticked the build fails.
ADDON_DEFAULT_OFF = {
    "Magic Resistance Icons v2": "alternative to Elemental Icons 3.0 + Mod Essentials 0.5.1 (same X017.BIN bytes)",
}


def _stem(name):
    import re
    return re.sub(r"\s+(v?\d+(\.\d+)*[a-z]?|rc\d+)$", "", name.strip(), flags=re.I).lower()


def layer(base, mods, supersede=True):
    """Base patches followed by add-on mods (as if dropped in Custom Mods).  Returns
    (patches, notes).  With `supersede`, folders replaced by a newer mod are dropped."""
    notes = []
    drop = set()
    mod_names = {m.name for m in mods}
    if supersede:
        for new, olds in SUPERSEDES.items():
            if new in mod_names:
                for o in olds:
                    drop.add(o.lower())
    for m in mods:
        why = ADDON_DEFAULT_OFF.get(m.name)
        if why and m.enabled:
            m.enabled = False
            notes.append("unticked %s by default: %s" % (m.label, why))
    out = []
    for p in base + mods:
        if p.name.lower() in drop:
            notes.append("dropped %s (superseded by a newer add-on)" % p.label)
            continue
        out.append(p)
    known = {n.lower() for olds in SUPERSEDES.values() for n in olds}
    for m in mods:
        for p in base:
            if p.name.lower() not in known and p.name != m.name and _stem(p.name) == _stem(m.name):
                notes.append("warning: %s looks like a newer version of %s; both are kept" % (m.label, p.label))
    return out, notes
