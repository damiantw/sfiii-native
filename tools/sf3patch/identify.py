"""Recognising the source disc: Redump track hashes first, the IP.BIN header as a fallback."""
from dataclasses import dataclass

from . import ipbin

STD_AUDIO = ("021edf3c2293243d6b6f52028fed44f569946249", 1818096)
STD_AUDIO_SHA256 = "f5b6d03d99bb85f42066a4691df5b43cc4e64f792e434e38d68ebf15f10ea047"


@dataclass(frozen=True)
class Known:
    key: str
    title: str
    serial: str
    version: str
    redump: int
    track1: tuple            # (sha1, bytes)
    track2: tuple = STD_AUDIO
    track1_sha256: str = None    # checked against a real dump; None where not yet seen
    track2_sha256: str = None
    content_sha256: str = None   # sfiii-native disc identity of the unpatched original


# Redump.org dumps (data track and audio track as Redump splits them; the audio track
# includes its 150-sector pregap).
KNOWN = [
    Known("sc1-usa", "Scenario 1 (USA)", "MK-81383", "V1.001", 20315,
          ("9b1033304091b3dea7c2fd6d88914a1c7d0c6727", 245934528),
          ("b372a4c92930d2b93213460a443a2220e74a973a", 1820448),
          "089c77470dec14f1dbffaad1ab50d584f06df5e28b475fc712b8e67e5890f951",
          "6bed8e1f830b32833676b75bc3cec9c831b44e8f0789a37eb4c1a0efb9d25e1e",
          "54aa1d2178407d7273a7fb54a7aef4b36c8364cc3b203acb997613e95eea81a9"),
    Known("sc1-eu", "Scenario 1 (Europe)", "MK-81383", "V1.005", 3494,
          ("9d8f601c9938acb39c7a2a5181dbc77e70117a6f", 245017248)),
    Known("sc1-jp-1.006", "Scenario 1 (Japan) V1.006", "GS-9175", "V1.006", 17380,
          ("6ae4c9cc601ee02a432f871373e25cad3a65b8b8", 247987824)),
    Known("sc1-jp-2.005", "Scenario 1 (Japan) V2.005", "GS-9175", "V2.005", 3509,
          ("4169bfb491046eac26688054c314233656d08c6b", 247717344)),
    Known("sc2-1.003", "Scenario 2 (Japan) V1.003", "GS-9188", "V1.003", 20117,
          ("82c157dbad2f50bd8d1fd9b417233221ab9fd8c8", 307023024), STD_AUDIO,
          "81dfba75da4687d272f46ad4148a7de39b6a564a604dfa47e45ac0c0cef6ad1b", STD_AUDIO_SHA256,
          "a855681edd77c5dd816033dc73dfc891c7e09048ecb9e45c85375dfc1543cc22"),
    Known("sc2-2.000", "Scenario 2 (Japan) V2.000", "GS-9188", "V2.000", 3508,
          ("e21f7ad51af3ef57af9f9f7db58afb2dd642e3ad", 307093584), STD_AUDIO,
          "2b385904b6f177885d2c0264555a79f5cb1333c731666de5ac1687b6338921e7", STD_AUDIO_SHA256,
          "d5def91943d7212174583fd0ca0f5ac0d031915c610aa4a2e4fe447fd2b16e38"),
    Known("sc3", "Scenario 3 (Japan)", "GS-9203", "V1.001", 3507,
          ("6a2646030ff74a98b666726b78003e6505d24285", 508594128), STD_AUDIO,
          "ee31a9be6552a075266d95c92c881a5db3cb4958ceaa3cea793f43c9cd8b4a1f", STD_AUDIO_SHA256,
          "598c40eab6a453e2a1fb8f4306b7d4d87f7ff8effea7f5dea43877fc6c886356"),
    Known("pd", "Premium Disc (Japan)", "6106979", "V1.000", 28747,
          ("1b5de342984618965d25494f329cb317452b7a6e", 555869328), STD_AUDIO,
          "f024e086293812f0dfa0b46626a9235ef0d54397d1b4a42d2f56036833da358a", STD_AUDIO_SHA256,
          "9a422bc58ae0dd9b00faad42c731e099c7a39a668fc4ebc43f4d08f0369bd5bb"),
]

BY_TRACK1 = {k.track1[0]: k for k in KNOWN}
BY_CONTENT = {k.content_sha256: k for k in KNOWN if k.content_sha256}


@dataclass
class Result:
    serial: str
    version: str
    areas: str
    title: str
    known: Known = None
    track1: tuple = None         # (sha1, bytes)
    track2: tuple = None
    track1_sha256: str = None
    track2_sha256: str = None
    warnings: tuple = ()

    @property
    def verified(self):
        return self.known is not None and not self.warnings


def identify(disc, hash_tracks=True):
    h = ipbin.parse(disc.ip_raw)
    warnings = []
    t1 = t2 = None
    s1 = s2 = None
    known = None
    if hash_tracks:
        if disc.data.sector_size == 2352:
            sha1, s1, size = disc.data.hashes()
            t1 = (sha1, size)
        audio = disc.audio_tracks()
        if audio:
            sha1, s2, size = audio[0].hashes()
            t2 = (sha1, size)
        known = BY_TRACK1.get(t1[0]) if t1 else None
        if known is None:
            warnings.append("the data track does not match a Redump dump of a Shining Force III disc "
                            "(a different dump, a modified image, or a 2048-byte track)")
        else:
            if (known.serial, known.version) != (h.product, h.version):
                warnings.append("IP.BIN says %s %s but the hash is %s %s" % (h.product, h.version, known.serial, known.version))
            if t1[1] != known.track1[1]:
                warnings.append("data track size differs from Redump")
            if known.track1_sha256 and s1 != known.track1_sha256:
                warnings.append("data track SHA-1 matches Redump but SHA-256 does not (%s)" % s1)
            if t2 is None or t2[0] != known.track2[0]:
                warnings.append("the audio track differs from Redump (%s); the output's audio will differ "
                                "from a wizard run on the original disc" % ("missing" if t2 is None else t2[0]))
            elif known.track2_sha256 and s2 != known.track2_sha256:
                warnings.append("audio track SHA-1 matches Redump but SHA-256 does not (%s)" % s2)
    return Result(h.product, h.version, h.areas, h.title, known, t1, t2, s1, s2, tuple(warnings))


def original_for_content(content_id):
    """The known unpatched disc whose sfiii-native content_sha256 is `content_id`, if any."""
    return BY_CONTENT.get(content_id)
