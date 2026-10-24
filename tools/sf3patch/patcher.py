"""What CDTools.GenerateISO does with a mounted disc, done on a disc image.

For every file on the disc, in DriveOrder order: files whose name starts with "CD" (the CD-DA
placeholder) become empty; every other file is copied, then for each ticked patch in list
order a replacement `<patch>/<serial>/<name>` is copied over it, then
`<patch>/<serial>/<version>/<name>`, then one DFR is applied (`<version>/<name>.DFR` if it
exists, otherwise `<serial>/<name>.DFR`).  After that, every non-DFR file a ticked patch
carries that is not on the disc is added (version folders first, first one of a name wins).
"""
import datetime
from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil

from . import dfr, ipbin, isobuild
from .cdimage import iso_time_to_utc


class PatchError(ValueError):
    pass


@dataclass
class Options:
    now: datetime.datetime = None              # time stamped on DFR-patched files (UTC)
    host_utc_offset: datetime.timedelta = datetime.timedelta(0)  # the wizard machine's zone
    cdfs_time: str = "iso"                     # how Windows reads ISO 9660 record times
    release_date: str = ipbin.WIZARD_RELEASE_DATE
    root_time: datetime.datetime = None        # override the root/CD-DA creation time (UTC)


@dataclass
class FileStep:
    patch: str
    action: str        # 'replace', 'dfr', 'new'
    path: Path


@dataclass
class FilePlan:
    name: str
    steps: list = field(default_factory=list)
    size: int = 0
    original_size: int = 0


def _utc(rec_time, mode):
    t = iso_time_to_utc(rec_time, mode)
    return t


def _mtime_utc(path):
    st = os.stat(path)
    return datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc).replace(tzinfo=None, microsecond=0)


def drive_ordered(files, order):
    """Root files sorted by (uint)driveOrder.IndexOf(name): unknown names last, stable."""
    pos = {}
    for i, n in enumerate(order):
        pos.setdefault(n, i)
    big = 2 ** 32
    return sorted(files, key=lambda r: pos.get(r.name, big))


class Build:
    """The patched disc's file list, ready for isobuild.Layout."""

    def __init__(self, disc, package, patches, work, opts=None, serial=None, version=None):
        self.opts = opts or Options()
        self.disc = disc
        self.package = package
        self.patches = patches
        self.work = Path(work) / "files"
        if self.work.exists():
            shutil.rmtree(self.work)
        self.work.mkdir(parents=True)
        header = ipbin.parse(disc.ip_raw)
        self.serial = serial or header.product
        self.version = version or header.version
        self.plans = []
        self.files = []
        self.notes = []
        self._build()

    def _root_time_utc(self):
        if self.opts.root_time is not None:
            return self.opts.root_time
        t = _utc(self.disc.root.time, self.opts.cdfs_time)
        return t

    def _build(self):
        o = self.opts
        now = o.now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)
        order = self.package.drive_order(self.serial)
        recs = drive_ordered(self.disc.files, order)
        root_utc = self._root_time_utc()
        self.root_time_local = root_utc + o.host_utc_offset if root_utc else None
        names_upper = set()

        def add(bf):
            key = isobuild.normalize_file_name(bf.name)
            if key in names_upper:
                raise PatchError("File already exists: %s (two files whose names differ only in case "
                                 "end up as one; the wizard fails the same way)" % bf.name)
            names_upper.add(key)
            self.files.append(bf)

        for rec in recs:
            plan = FilePlan(rec.name, original_size=rec.size)
            self.plans.append(plan)
            if rec.name.startswith("CD"):
                add(isobuild.BuildFile(rec.name, 0, root_utc, lambda: b""))
                continue
            data = None
            time = _utc(rec.time, o.cdfs_time)
            changed = False
            for p in self.patches:
                serial_file = p.index.get(self.serial, rec.name)
                ver_file = p.index.get(self.serial, self.version, rec.name)
                for f in (serial_file, ver_file):
                    if f is not None and f.is_file():
                        data = f.read_bytes()
                        time = _mtime_utc(f)
                        changed = True
                        plan.steps.append(FileStep(p.label, "replace", f))
                d = p.index.get(self.serial, self.version, rec.name + ".DFR")
                if d is None or not d.is_file():
                    d = p.index.get(self.serial, rec.name + ".DFR")
                if d is not None and d.is_file():
                    if data is None:
                        data = self.disc.read_file(rec)
                    patch = dfr.parse(d.read_bytes(), "%s:%s" % (p.label, d.name))
                    try:
                        data = dfr.apply(patch, data, Path(rec.name).stem)
                    except dfr.DFRError as e:
                        raise PatchError("%s\n(patch %s, file %s; the original bytes do not match, so this "
                                         "patch does not fit this disc or an earlier patch changed the same "
                                         "bytes)" % (e, p.label, d.relative_to(p.path))) from None
                    time = now
                    changed = True
                    plan.steps.append(FileStep(p.label, "dfr", d))
            if changed:
                tmp = self.work / rec.name
                tmp.write_bytes(data)
                plan.size = len(data)
                add(isobuild.BuildFile(rec.name, len(data), time, lambda tmp=tmp: tmp.read_bytes()))
            else:
                plan.size = rec.size
                add(isobuild.BuildFile(rec.name, rec.size, time, lambda rec=rec: self.disc.read_file(rec)))

        disc_names = {r.name for r in recs}
        candidates = []
        for p in self.patches:
            for f in p.index.files(self.serial, self.version) or []:
                if not f.name.endswith(".DFR"):
                    candidates.append((p, f))
        for p in self.patches:
            listing = p.index.files(self.serial)
            if listing is None:
                raise PatchError("Could not find a part of the path '%s/%s'" % (p.path, self.serial))
            for f in listing:
                if not f.name.endswith(".DFR"):
                    candidates.append((p, f))
        seen = set()
        for p, f in candidates:
            if f.name in disc_names or f.name in seen:
                continue
            seen.add(f.name)
            name = f.name.upper()
            plan = FilePlan(name, [FileStep(p.label, "new", f)], f.stat().st_size, 0)
            self.plans.append(plan)
            tmp = self.work / ("new." + name)
            shutil.copyfile(f, tmp)
            add(isobuild.BuildFile(name, plan.size, _mtime_utc(f), lambda tmp=tmp: tmp.read_bytes()))

    def ip(self):
        return ipbin.wizard_rewrite(self.disc.ip_raw, self.package.version, self.opts.release_date)

    def volume_label(self):
        return self.disc.volume_id.rstrip(" \0").split(" ")[0]

    def layout(self):
        label = self.volume_label()
        audio = self.disc.audio_tracks()
        if len(audio) > 1:
            raise PatchError("discs with more than one audio track are not supported "
                             "(the wizard writes only the first one)")
        sizes = [150 * 2352 + (t.end - t.index1) for t in audio]
        ids = isobuild.Identifiers(volume=label, volume_set=label)
        return isobuild.Layout(self.ip(), self.files, self.root_time_local, sizes, ids)

    def audio_data(self):
        """Each audio track as the wizard writes it: 150 silent sectors, then INDEX 01 on."""
        for t in self.disc.audio_tracks():
            yield bytes(150 * 2352) + t.audio_from_index1()
