"""Recognising the source disc: Redump track hashes first, the IP.BIN header as a fallback."""
from dataclasses import dataclass

from . import ipbin

STD_AUDIO = ("021edf3c2293243d6b6f52028fed44f569946249", 1818096)


@dataclass(frozen=True)
class Known:
    key: str
    title: str
    serial: str
    version: str
    redump: int
    track1: tuple            # (sha1, bytes)
    track2: tuple = STD_AUDIO


# Redump.org dumps (data track and audio track as Redump splits them; the audio track
# includes its 150-sector pregap).
KNOWN = [
    Known("sc1-usa", "Scenario 1 (USA)", "MK-81383", "V1.001", 20315,
          ("9b1033304091b3dea7c2fd6d88914a1c7d0c6727", 245934528),
          ("b372a4c92930d2b93213460a443a2220e74a973a", 1820448)),
    Known("sc1-eu", "Scenario 1 (Europe)", "MK-81383", "V1.005", 3494,
          ("9d8f601c9938acb39c7a2a5181dbc77e70117a6f", 245017248)),
    Known("sc1-jp-1.006", "Scenario 1 (Japan) V1.006", "GS-9175", "V1.006", 17380,
          ("6ae4c9cc601ee02a432f871373e25cad3a65b8b8", 247987824)),
    Known("sc1-jp-2.005", "Scenario 1 (Japan) V2.005", "GS-9175", "V2.005", 3509,
          ("4169bfb491046eac26688054c314233656d08c6b", 247717344)),
    Known("sc2-1.003", "Scenario 2 (Japan) V1.003", "GS-9188", "V1.003", 20117,
          ("82c157dbad2f50bd8d1fd9b417233221ab9fd8c8", 307023024)),
    Known("sc2-2.000", "Scenario 2 (Japan) V2.000", "GS-9188", "V2.000", 3508,
          ("e21f7ad51af3ef57af9f9f7db58afb2dd642e3ad", 307093584)),
    Known("sc3", "Scenario 3 (Japan)", "GS-9203", "V1.001", 3507,
          ("6a2646030ff74a98b666726b78003e6505d24285", 508594128)),
    Known("pd", "Premium Disc (Japan)", "6106979", "V1.000", 28747,
          ("1b5de342984618965d25494f329cb317452b7a6e", 555869328)),
]

BY_TRACK1 = {k.track1[0]: k for k in KNOWN}


@dataclass
class Result:
    serial: str
    version: str
    areas: str
    title: str
    known: Known = None
    track1: tuple = None
    track2: tuple = None
    warnings: tuple = ()

    @property
    def verified(self):
        return self.known is not None and not self.warnings


def identify(disc, hash_tracks=True):
    h = ipbin.parse(disc.ip_raw)
    warnings = []
    t1 = t2 = None
    known = None
    if hash_tracks:
        t1 = disc.data.hash_sha1() if disc.data.sector_size == 2352 else None
        audio = disc.audio_tracks()
        t2 = audio[0].hash_sha1() if audio else None
        known = BY_TRACK1.get(t1[0]) if t1 else None
        if known is None:
            warnings.append("the data track does not match a Redump dump of a Shining Force III disc "
                            "(a different dump, a modified image, or a 2048-byte track)")
        else:
            if (known.serial, known.version) != (h.product, h.version):
                warnings.append("IP.BIN says %s %s but the hash is %s %s" % (h.product, h.version, known.serial, known.version))
            if t1[1] != known.track1[1]:
                warnings.append("data track size differs from Redump")
            if t2 is None or t2[0] != known.track2[0]:
                warnings.append("the audio track differs from Redump (%s); the output's audio will differ "
                                "from a wizard run on the original disc" % ("missing" if t2 is None else t2[0]))
    return Result(h.product, h.version, h.areas, h.title, known, t1, t2, tuple(warnings))
