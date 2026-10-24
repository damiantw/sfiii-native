"""Static conflict check between ticked patches (stricter than the wizard's ErrorCheck).

Severity 'error': the build would fail:
  * two patches' DFRs write overlapping bytes and the later one does not expect the earlier
    one's result there (its byte check would fail);
  * a new file differs only in case from a disc file (the wizard stops with "File already exists").
Severity 'warning': legal but worth knowing:
  * a whole-file replacement lands after another patch already changed that file (add-ons such
    as Blacksmith Interface Update v3.1 ship a file built from the translated one, so this is
    normally intended; the earlier changes are overwritten);
  * DFRs that stack on each other on purpose (the later one expects the earlier's bytes);
  * a DFR applied on top of another patch's replacement file;
  * the same new file shipped by several patches (the first one wins).
"""
from . import dfr


def _ranges(patch):
    out = []
    for op in patch.ops:
        if op.kind == "replace":
            out.append((op.offset, op.offset + len(op.new), op))
    return out


def check(patches, disc_names, serial, version):
    issues = []
    touched = {}       # disc file -> list of (patch label, kind, data)
    new_files = {}
    upper = {n.upper(): n for n in disc_names}
    for p in patches:
        for name in disc_names:
            rep = [f for f in (p.index.get(serial, name), p.index.get(serial, version, name)) if f is not None and f.is_file()]
            d = p.index.get(serial, version, name + ".DFR")
            if d is None or not d.is_file():
                d = p.index.get(serial, name + ".DFR")
            if d is not None and not d.is_file():
                d = None
            if not rep and d is None:
                continue
            hist = touched.setdefault(name, [])
            if rep:
                if hist:
                    issues.append(("warning", "%s replaces %s after %s changed it; its file wins"
                                   % (p.label, name, ", ".join(sorted({h[0] for h in hist})))))
                hist[:] = [(p.label, "replace", None)]
            if d is not None:
                parsed = dfr.parse(d.read_bytes(), d.name)
                for label, kind, other in hist:
                    if kind == "replace" and label != p.label:
                        issues.append(("warning", "%s patches %s on top of %s's replacement file" % (p.label, name, label)))
                    if kind != "dfr":
                        continue
                    for a0, a1, aop in _ranges(other):
                        for b0, b1, bop in _ranges(parsed):
                            lo, hi = max(a0, b0), min(a1, b1)
                            if lo >= hi:
                                continue
                            expect = bop.old[lo - b0:hi - b0]
                            result = aop.new[lo - a0:hi - a0]
                            if expect == result:
                                issues.append(("warning", "%s and %s both patch %s at 0x%X-0x%X (stacked on purpose)"
                                               % (label, p.label, name, lo, hi - 1)))
                            else:
                                issues.append(("error", "%s and %s both patch %s at 0x%X-0x%X; they conflict"
                                               % (label, p.label, name, lo, hi - 1)))
                hist.append((p.label, "dfr", parsed))
        for sub in ((serial, version), (serial,)):
            for f in p.index.files(*sub) or []:
                if f.name.endswith(".DFR") or f.name in disc_names:
                    continue
                if f.name.upper() in upper:
                    issues.append(("error", "%s ships %s, which differs only in case from the disc's %s; the wizard "
                                   "fails with 'File already exists'" % (p.label, f.name, upper[f.name.upper()])))
                    continue
                prev = new_files.get(f.name.upper())
                if prev and prev[0] != p.label:
                    issues.append(("warning", "%s and %s both add %s; only the first one found is used" % (prev[0], p.label, f.name.upper())))
                elif not prev:
                    new_files[f.name.upper()] = (p.label, f)
    return issues
