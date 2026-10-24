"""Writing the patched image: one BIN (Mode 1/2352 data with EDC/ECC, then the audio) and
the CUE sheet the wizard writes next to it."""
import hashlib
from pathlib import Path

from . import edcecc

RAW = 2352


def cue_address(sectors):
    """SectorToAddress: mm:ss:ff of a sector count, no 150-sector offset."""
    return "%02d:%02d:%02d" % (sectors // 4500, sectors // 75 % 60, sectors % 75)


def cue_text(bin_name, data_sectors, audio_tracks=1):
    lines = ['FILE "%s" BINARY' % bin_name, "  TRACK 01 MODE1/2352", "    INDEX 01 00:00:00"]
    if audio_tracks:
        lines += ["  TRACK 02 AUDIO",
                  "    INDEX 00 %s" % cue_address(data_sectors - 150),
                  "    INDEX 01 %s" % cue_address(data_sectors)]
    return "\r\n".join(lines) + "\r\n"


def write_bin(path, layout, audio, progress=None):
    """Write data track + audio to `path`; returns (data_sectors, sha1 of the data track,
    sha1 of the whole bin)."""
    lba = 0
    whole = hashlib.sha1()
    track1 = hashlib.sha1()
    with open(path, "wb") as out:
        for chunk in layout.user_data():
            n = len(chunk) // 2048
            raw = edcecc.mode1_many(chunk, lba)
            out.write(raw)
            whole.update(raw)
            track1.update(raw)
            lba += n
            if progress:
                progress(lba, layout.data_sectors)
        if lba != layout.data_sectors:
            raise AssertionError("wrote %d data sectors, layout says %d" % (lba, layout.data_sectors))
        for track in audio:
            out.write(track)
            whole.update(track)
    return lba, track1.hexdigest(), whole.hexdigest()


def write_image(bin_path, layout, audio, progress=None):
    bin_path = Path(bin_path)
    audio = list(audio)
    sectors, t1, whole = write_bin(bin_path, layout, audio, progress)
    cue = bin_path.with_suffix(".cue")
    cue.write_bytes(cue_text(bin_path.name, sectors, len(audio)).encode("utf-8"))
    return cue, sectors, t1, whole
