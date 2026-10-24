"""Patch packages: the wizard's folder (Patches, Custom Mods, Data, DriveOrder) and add-on mods.

Nothing here ships patch data.  A package is either the folder the official self-extracting
SF3Patch.exe unpacks to, that .exe itself (unpacked with 7-Zip), or a zip/folder of one or
more add-on mods.  The wizard runs on Windows, where every path lookup ignores case; this
module gives each patch folder a case-insensitive index so lookups behave the same on Linux.
"""
import datetime
import os
from dataclasses import dataclass, field
from pathlib import Path
import shutil
import subprocess
import zipfile

from . import dotnet, netjson

CATEGORIES = ("general", "bugfixes", "qol", "mods")


class PackageError(ValueError):
    pass


class CaseDir:
    """A directory with Windows-style (case-insensitive) child lookup."""

    def __init__(self, path):
        self.path = Path(path)
        self._kids = None

    def kids(self):
        if self._kids is None:
            self._kids = {}
            if self.path.is_dir():
                for p in sorted(self.path.iterdir(), key=lambda p: dotnet.ntfs_key(p.name)):
                    self._kids.setdefault(p.name.upper(), p)
        return self._kids

    def get(self, *parts):
        """The real path for `parts` looked up case-insensitively, or None."""
        cur = self
        for i, part in enumerate(parts):
            p = cur.kids().get(part.upper())
            if p is None:
                return None
            if i == len(parts) - 1:
                return p
            if not p.is_dir():
                return None
            cur = CaseDir(p)
        return self.path

    def files(self, *parts):
        """Top-level files of a subdirectory, in NTFS order; None when it does not exist."""
        d = self.get(*parts) if parts else self.path
        if d is None or not d.is_dir():
            return None
        return [p for p in sorted(d.iterdir(), key=lambda p: dotnet.ntfs_key(p.name)) if p.is_file()]


@dataclass
class PatchDir:
    path: Path
    source: str                # "Patches", "Custom Mods", or "mod:<archive name>"
    meta_error: str = None
    category: str = None
    text: str = None
    enabled: bool = False
    priority: int = 9999
    title: str = None
    desc: str = None
    index: CaseDir = field(default=None, repr=False)

    @property
    def name(self):
        return self.path.name

    @property
    def label(self):
        return "%s/%s" % (self.source, self.name)

    def applies_to(self, serial, version):
        """The wizard lists a patch for a disc when <serial> or <serial>/<version> has files."""
        top = self.index.files(serial)
        if top:
            return True
        sub = self.index.files(serial, version)
        return bool(sub)


def read_metadata(p):
    """Fill in a PatchDir the way PreparePatches does; a failure becomes meta_error."""
    meta = p.index.get("metadata.json")
    try:
        doc = netjson.loads(netjson.read_text(meta.read_bytes()))
        if not isinstance(doc, dict):
            raise netjson.JsonError("metadata.json is not an object")
        g = lambda k: doc.get(k, netjson.MISSING)
        p.category = netjson.category_string(g("category")).lower()
        p.text = netjson.to_net_string(g("text"))
        p.enabled = netjson.to_net_bool(g("enabled"))
        pr = g("priority")
        if pr is None:
            raise netjson.JsonError("Cannot convert null to 'int'")
        p.priority = 9999 if pr is netjson.MISSING else netjson.to_net_int(pr)
        p.title = netjson.to_net_string(g("title"))
        p.desc = netjson.to_net_string(g("desc"))
    except (netjson.JsonError, OSError, UnicodeError) as e:
        p.meta_error = "Error with patch file:%s (%s)" % (p.name, e)
    return p


def _patch_dirs(parent, source):
    """Top-level folders of Patches/ or Custom Mods/ that have a metadata.json (NTFS order)."""
    out = []
    if parent is None or not parent.is_dir():
        return out
    for d in sorted((d for d in parent.iterdir() if d.is_dir()), key=lambda d: dotnet.ntfs_key(d.name)):
        idx = CaseDir(d)
        if idx.get("metadata.json") is not None:
            out.append(PatchDir(d, source, index=idx))
    return out


def find_mod_dirs(root, source):
    """Every folder under `root` with a metadata.json (one zip may bundle several patches)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort(key=dotnet.ntfs_key)
        if any(f.lower() == "metadata.json" for f in filenames):
            out.append(PatchDir(Path(dirpath), source, index=CaseDir(dirpath)))
            dirnames[:] = []
    return out


@dataclass
class Package:
    root: Path
    version: str
    patches: list
    index: CaseDir

    def drive_order(self, serial):
        p = self.index.get("DriveOrder", serial + ".txt")
        if p is None:
            raise PackageError("the package has no DriveOrder/%s.txt, so the wizard cannot patch this disc" % serial)
        text = netjson.read_text(p.read_bytes()).replace("\r\n", "\n")
        return [dotnet.trim(line.split(",")[0]) for line in text.split("\n")]


def _find_wizard_root(path):
    for dirpath, dirnames, filenames in os.walk(path):
        names = {n.upper() for n in dirnames}
        if "PATCHES" in names and "DRIVEORDER" in names:
            return Path(dirpath)
        dirnames.sort()
    return None


def extract(archive, dest, host_utc_offset=None):
    """Unpack a .zip (Python) or a 7-Zip SFX/.7z (7z) into dest; returns dest."""
    archive, dest = Path(archive), Path(dest)
    stamp = dest / ".sf3patch-extracted"
    if stamp.exists() and stamp.read_text() == "%s %d" % (archive.name, archive.stat().st_size):
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if zipfile.is_zipfile(archive) and archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in Path(name).parts:
                    raise PackageError("%s: unsafe path %r in archive" % (archive.name, info.filename))
                target = dest / name
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                # zip times are local wall-clock times of whoever made the zip; Explorer
                # stamps them back as the extracting machine's local time.
                local = datetime.datetime(*info.date_time)
                if host_utc_offset is None:
                    ts = local.timestamp()  # this machine's time zone
                else:
                    ts = (local - host_utc_offset).replace(tzinfo=datetime.timezone.utc).timestamp()
                os.utime(target, (ts, ts))
    else:
        exe = shutil.which("7z") or shutil.which("7za") or shutil.which("7zz")
        if not exe:
            raise PackageError("unpacking %s needs 7-Zip (install p7zip-full or 7zip)" % archive.name)
        r = subprocess.run([exe, "x", "-y", "-o%s" % dest, str(archive)], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True)
        if r.returncode != 0:
            raise PackageError("7z failed on %s:\n%s" % (archive.name, r.stdout[-2000:]))
    stamp.write_text("%s %d" % (archive.name, archive.stat().st_size))
    return dest


def load(path, work, host_utc_offset=None):
    """The wizard package at `path` (its folder, or SF3Patch.exe)."""
    path = Path(path)
    if path.is_file():
        path = extract(path, Path(work) / "package" / path.stem, host_utc_offset)
    root = _find_wizard_root(path)
    if root is None:
        raise PackageError("%s does not look like the patch wizard folder (no Patches/ and DriveOrder/)" % path)
    index = CaseDir(root)
    data = index.get("Data", "data.json")
    if data is None:
        raise PackageError("%s has no Data/data.json" % root)
    doc = netjson.loads(netjson.read_text(data.read_bytes()))
    version = netjson.to_net_string(doc.get("version", netjson.MISSING)) if isinstance(doc, dict) else None
    if not version:
        raise PackageError("Data/data.json has no version")
    patches = _patch_dirs(index.get("Patches"), "Patches") + _patch_dirs(index.get("Custom Mods"), "Custom Mods")
    for p in patches:
        read_metadata(p)
    return Package(root, version, patches, index)


def load_mod(path, work, host_utc_offset=None):
    """Patch folders from a mod zip or folder, to be added the way Custom Mods are."""
    path = Path(path)
    if path.is_file():
        if path.suffix.lower() not in (".zip", ".7z"):
            raise PackageError("%s: mods must be a .zip, .7z or folder" % path.name)
        path = extract(path, Path(work) / "mods" / path.stem, host_utc_offset)
        source = "mod:" + path.name
    else:
        source = "mod:" + path.name
    dirs = find_mod_dirs(path, source)
    for p in dirs:
        read_metadata(p)
    return dirs
