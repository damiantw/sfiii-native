"""sf3patch: apply the Shining Force III Translation Project's patches on Linux.

    python -m tools.sf3patch fetch  --dest ~/sf3trans
    python -m tools.sf3patch identify "Scenario 2.cue"
    python -m tools.sf3patch list   "Scenario 2.cue" --package ~/sf3trans/SF3Patch.exe
    python -m tools.sf3patch patch  "Scenario 2.cue" --package ~/sf3trans/SF3Patch.exe -o out/GS-9188_V1.003.bin
    python -m tools.sf3patch compare mine.cue theirs.cue
"""
import argparse
import datetime
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from . import __version__, conflicts, identify, package, patcher, selection
from .cdimage import Disc, DiscError
from .dfr import DFRError
from .isobuild import BuildError
from .netjson import JsonError

REPO = Path(__file__).resolve().parents[2]


def _offset(text):
    m = re.fullmatch(r"([+-])?(\d{1,2})(?::?(\d{2}))?", text.strip())
    if not m:
        raise argparse.ArgumentTypeError("use +HH:MM or -HH:MM")
    sign = -1 if m.group(1) == "-" else 1
    return sign * datetime.timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0))


def _utc_time(text):
    t = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if t.tzinfo is not None:
        t = t.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return t.replace(microsecond=0)


def _local_offset():
    return datetime.datetime.now().astimezone().utcoffset()


def _work(args, near):
    if args.work:
        w = Path(args.work)
        w.mkdir(parents=True, exist_ok=True)
        return w, False
    return Path(tempfile.mkdtemp(prefix=".sf3patch-", dir=near)), True


def _open_disc(path, work):
    return Disc(path, work=Path(work) / "chd")


def _inside_repo(p):
    try:
        Path(p).resolve().relative_to(REPO)
    except ValueError:
        return False
    return (REPO / ".git").exists()


def content_sha256(cue):
    """The sfiii-native disc identity of an image, when saturn-recomp is importable."""
    src = REPO / ".local" / "saturn-recomp" / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    sys.path.insert(0, str(REPO / "tools"))
    try:
        from saturnrecomp import disc as srd
        import disc_profile
    except ImportError:
        return None
    finally:
        sys.path.remove(str(REPO / "tools"))
    return disc_profile.content_id(srd.manifest(srd.Disc(str(cue))))


def matching_profiles(content_id):
    """ids of the checked-in profiles/*.json whose content_sha256 is `content_id`."""
    import json
    out = []
    for f in sorted((REPO / "profiles").glob("*.json")):
        try:
            prof = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(prof, dict) and prof.get("content_sha256") == content_id:
            out.append(prof.get("id", f.stem))
    return out


def _print_content_id(c):
    print("content_sha256 %s" % c)
    hits = matching_profiles(c)
    print("matches sfiii-native profile %s" % ", ".join(hits) if hits
          else "no sfiii-native profile has this content_sha256 yet (see docs/translation-patcher.md)")


# ---------------------------------------------------------------- packages

def _load_patches(args, work, serial=None, version=None, log=print):
    if not args.package:
        raise package.PackageError("give --package (the SF3Patch.exe from `fetch`, or the folder it unpacks to)")
    off = args.host_utc_offset if args.host_utc_offset is not None else None
    pkg = package.load(args.package, work, off)
    mods = []
    for m in args.mod or []:
        mods += package.load_mod(m, work, off)
    if args.addons:
        d = Path(args.addons)
        zips = sorted((p for p in d.iterdir() if p.suffix.lower() in (".zip", ".7z")
                       and p.name not in _skip_addons()), key=lambda p: p.name.lower())
        for z in zips:
            mods += package.load_mod(z, work, off)
    patches, notes = selection.layer(pkg.patches, mods, supersede=not args.no_supersede)
    for n in notes:
        log(n)
    return pkg, patches


def _skip_addons():
    from .fetch import SKIP
    return SKIP


def _listed(patches, serial, version):
    ordered, errors = selection.listed(patches, serial, version)
    if errors:
        raise package.PackageError("Failed. An error has occured preparing patches:\n" + "\n".join(errors))
    return ordered


# ---------------------------------------------------------------- commands

def cmd_fetch(args):
    from . import fetch
    got = fetch.fetch(args.dest, wizard=not args.addons_only, addons=not args.wizard_only)
    print("saved under %s; do not redistribute these files" % Path(args.dest).resolve())
    return 0


def cmd_identify(args):
    work, temp = _work(args, None)
    try:
        d = _open_disc(args.disc, work)
        r = identify.identify(d, hash_tracks=not args.no_hash)
        print("serial   %s" % r.serial)
        print("version  %s" % r.version)
        print("areas    %s" % r.areas)
        print("title    %s" % r.title)
        print("volume   %s" % d.volume_id.rstrip())
        if r.track1:
            print("track 1  %s (%d bytes)" % r.track1)
        if r.track2:
            print("track 2  %s (%d bytes)" % r.track2)
        if r.known:
            print("redump   %s, http://redump.org/disc/%d/" % (r.known.key, r.known.redump))
        for w in r.warnings:
            print("warning: " + w)
        if args.content_id:
            c = content_sha256(d.cue)
            if c:
                _print_content_id(c)
            else:
                print("content_sha256 (saturn-recomp not importable)")
        return 0 if (r.known or args.no_hash) else 1
    finally:
        if temp:
            shutil.rmtree(work, ignore_errors=True)


def _disc_ids(args, work):
    if args.disc:
        d = _open_disc(args.disc, work)
        r = identify.identify(d, hash_tracks=False)
        return d, r.serial, r.version
    if not (args.serial and args.disc_version):
        raise package.PackageError("give a disc, or --serial and --disc-version")
    return None, args.serial, args.disc_version


def cmd_list(args):
    work, temp = _work(args, None)
    try:
        d, serial, version = _disc_ids(args, work)
        pkg, patches = _load_patches(args, work)
        ordered = _listed(patches, serial, version)
        chosen = {id(p) for p in selection.choose(ordered, args.enable or [], args.disable or [], args.only)}
        print("%s %s, package V%s: %d patches listed, %d ticked (in apply order)"
              % (serial, version, pkg.version, len(ordered), len(chosen)))
        for p in ordered:
            print("  [%s] %-9s %5d  %-45s %s" % ("x" if id(p) in chosen else " ", p.category, p.priority,
                                                p.name, p.source))
        if d is not None:
            names = [r.name for r in d.files]
            for sev, msg in conflicts.check([p for p in ordered if id(p) in chosen], names, serial, version):
                print("%s: %s" % (sev, msg))
        return 0
    finally:
        if temp:
            shutil.rmtree(work, ignore_errors=True)


def cmd_patch(args):
    out = Path(args.output)
    if not out.name.endswith(".bin"):
        raise package.PackageError("the output must be a .bin (its .cue is written next to it)")
    if _inside_repo(out) and not args.allow_repo_output:
        raise package.PackageError("refusing to write a disc image inside the sfiii-native checkout (%s); "
                                   "game data must never be committed" % REPO)
    out.parent.mkdir(parents=True, exist_ok=True)
    work, temp = _work(args, out.parent)
    try:
        d = _open_disc(args.disc, work)
        r = identify.identify(d, hash_tracks=not args.no_hash)
        if r.known:
            print("source: %s %s (Redump %d)" % (r.serial, r.version, r.known.redump))
        else:
            print("source: %s %s (IP.BIN)" % (r.serial, r.version))
        for w in r.warnings:
            print("warning: " + w)
        if not args.no_hash and not r.known and not args.any_disc:
            raise package.PackageError("unknown dump; pass --any-disc to patch it anyway")
        pkg, patches = _load_patches(args, work)
        ordered = _listed(patches, r.serial, r.version)
        chosen = selection.choose(ordered, args.enable or [], args.disable or [], args.only)
        print("package V%s: applying %d of %d listed patches:" % (pkg.version, len(chosen), len(ordered)))
        for p in chosen:
            print("  %s" % p.label)
        issues = conflicts.check(chosen, [x.name for x in d.files], r.serial, r.version)
        for sev, msg in issues:
            print("%s: %s" % (sev, msg))
        if any(s == "error" for s, _ in issues) and not args.allow_conflicts:
            raise package.PackageError("conflicting patches (use --allow-conflicts to build anyway)")
        opts = patcher.Options(cdfs_time=args.cdfs_time,
                               host_utc_offset=args.host_utc_offset if args.host_utc_offset is not None else _local_offset())
        if args.now:
            opts.now = args.now
        if args.release_date:
            opts.release_date = args.release_date
        if args.reproducible:
            opts.host_utc_offset = datetime.timedelta(0)
            opts.now = opts.now or patcher._utc(d.root.time, args.cdfs_time) or datetime.datetime(2000, 1, 1)
        b = patcher.Build(d, pkg, chosen, work, opts)
        changed = [pl for pl in b.plans if pl.steps]
        grown = [pl for pl in changed if pl.size != pl.original_size and pl.original_size]
        added = [pl for pl in changed if not pl.original_size and pl.steps[0].action == "new"]
        print("%d files changed (%d changed size), %d added" % (len(changed), len(grown), len(added)))
        layout = b.layout()
        from . import output
        def progress(done, total):
            if sys.stderr.isatty():
                sys.stderr.write("\r  writing %d/%d sectors" % (done, total))
        cue, sectors, t1, whole = output.write_image(out, layout, b.audio_data(), progress)
        if sys.stderr.isatty():
            sys.stderr.write("\n")
        print("wrote %s and %s (%d data sectors)" % (out, cue.name, sectors))
        print("track 1 sha1 %s" % t1)
        if not args.no_content_id:
            c = content_sha256(cue)
            if c:
                _print_content_id(c)
        return 0
    finally:
        if temp and not args.keep_work:
            shutil.rmtree(work, ignore_errors=True)


def cmd_compare(args):
    from . import compare
    return compare.main(args.a, args.b, args.times)


# ---------------------------------------------------------------- parser

def build_parser():
    ap = argparse.ArgumentParser(prog="sf3patch", description=__doc__.split("\n")[0])
    ap.add_argument("--version", action="version", version="sf3patch " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def pkg_args(p):
        p.add_argument("--package", help="SF3Patch.exe (V25.1) or the folder it unpacks to")
        p.add_argument("--mod", action="append", help="an add-on mod zip or folder (like Custom Mods); repeatable")
        p.add_argument("--addons", help="a folder of add-on zips, e.g. the V25+ folder from `fetch`")
        p.add_argument("--no-supersede", action="store_true",
                       help="keep base patches that a newer add-on replaces")
        p.add_argument("--enable", action="append", metavar="NAME", help="tick a patch (folder name)")
        p.add_argument("--disable", action="append", metavar="NAME", help="untick a patch")
        p.add_argument("--only", nargs="+", metavar="NAME", help="tick exactly these patches")
        p.add_argument("--host-utc-offset", type=_offset, default=None,
                       help="time zone of the emulated Windows machine (default: this machine's)")

    p = sub.add_parser("fetch", help="download the wizard and the V25+ add-ons from the project's server")
    p.add_argument("--dest", default=os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "sf3patch"))
    p.add_argument("--wizard-only", action="store_true")
    p.add_argument("--addons-only", action="store_true")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("identify", help="identify a disc image (Redump hashes and IP.BIN)")
    p.add_argument("disc", help=".cue or .chd")
    p.add_argument("--no-hash", action="store_true", help="skip hashing the tracks")
    p.add_argument("--content-id", action="store_true", help="also print the sfiii-native content_sha256")
    p.add_argument("--work")
    p.set_defaults(func=cmd_identify)

    p = sub.add_parser("list", help="the patches the wizard would list for a disc, in apply order")
    p.add_argument("disc", nargs="?")
    p.add_argument("--serial")
    p.add_argument("--disc-version", help="e.g. V1.003")
    p.add_argument("--work")
    pkg_args(p)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("patch", help="write a patched BIN/CUE")
    p.add_argument("disc", help=".cue or .chd of the original disc")
    p.add_argument("-o", "--output", required=True, help="output .bin (a .cue is written beside it)")
    pkg_args(p)
    p.add_argument("--allow-conflicts", action="store_true")
    p.add_argument("--any-disc", action="store_true", help="patch a dump that is not a known Redump dump")
    p.add_argument("--no-hash", action="store_true", help="skip the Redump check")
    p.add_argument("--cdfs-time", choices=("iso", "local"), default="iso",
                   help="how the original files' ISO 9660 times are read (see docs)")
    p.add_argument("--now", type=_utc_time, help="timestamp for DFR-patched files (ISO 8601, UTC if no zone)")
    p.add_argument("--release-date", help="IP.BIN release date (default: the V25.1 wizard's 20240825)")
    p.add_argument("--reproducible", action="store_true",
                   help="fixed timestamps: UTC host zone and DFR files stamped with the disc's root time")
    p.add_argument("--no-content-id", action="store_true")
    p.add_argument("--work", help="scratch folder (default: a temporary folder beside the output)")
    p.add_argument("--keep-work", action="store_true")
    p.add_argument("--allow-repo-output", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_patch)

    p = sub.add_parser("compare", help="compare two images file by file (e.g. ours vs the wizard's)")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--times", action="store_true", help="also compare directory record times")
    p.set_defaults(func=cmd_compare)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (package.PackageError, patcher.PatchError, DiscError, DFRError, BuildError, JsonError) as e:
        print("sf3patch: %s" % e, file=sys.stderr)
        return 2
