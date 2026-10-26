# Translation patcher for Linux (`tools/sf3patch`)

`tools/sf3patch` applies the [Shining Force III Translation Project](https://sf3trans.shiningforcecentral.com/)
patches to a Saturn disc image on Linux, without the Windows PatchWizard or Wine. It is our own
implementation. We decompiled the V25.1 wizard (`SF3Patch.exe`) only to learn its behaviour, and
none of its code is copied here. The output is a patched BIN/CUE that sfiii-native and emulators
can load.

**No game or patch data lives in this repository.** The tool reads the patch package at run time.
Either `sf3patch fetch` downloads it from the project's server, or you point the tool at a copy you
already have. Discs, patch files and outputs stay outside the checkout: `patch` refuses to write
inside it, and `tools/check-source-package.py` rejects images and archives. Do not redistribute the
package or the patched images.

## Requirements

- Python 3.12 or newer. `numpy` is optional; it speeds up the EDC/ECC pass, and a pure-Python path is used without it.
- `7z` (p7zip) to unpack `SF3Patch.exe`, which is a self-extracting 7-Zip archive. Plain `.zip`
  add-ons are opened with Python's `zipfile`.
- `chdman` (Debian/Ubuntu `mame-tools`), only for `.chd` input. The CHD is first extracted to a
  BIN/CUE in the work folder.
- A Redump-style dump of the original disc: a `.cue` with BIN tracks (either one file per track or a
  single file), or a `.chd` of the same dump.

## Usage

Run the tool from the repository root:

```sh
# 1. Download SF3Patch.exe (V25.1) and the V25+ add-on zips. This goes to ~/.cache/sf3patch by default.
python3 -m tools.sf3patch fetch --dest ~/sf3trans

# 2. Identify the dump: Redump hashes, IP.BIN serial and version.
python3 -m tools.sf3patch identify "Shining Force III - Scenario 3 (Japan).cue" --content-id

# 3. Show what the wizard would list for this disc: [x] = ticked by default, in apply order.
python3 -m tools.sf3patch list "….cue" --package ~/sf3trans/SF3Patch.exe

# 4. Write the patched image. A .cue is written beside the .bin.
python3 -m tools.sf3patch patch "….cue" --package ~/sf3trans/SF3Patch.exe -o ~/sf3/sc3-v25_1.bin

# 5. Optional: compare two images file by file (e.g. ours against the wizard's).
python3 -m tools.sf3patch compare ours.cue wizard.cue [--times]
```

Package and selection options (`list` and `patch`):

| Option | Meaning |
| --- | --- |
| `--package P` | `SF3Patch.exe`, or the folder it unpacks to (the folder holding `Patches/`, `Custom Mods/`, `Data/`, `DriveOrder/`). |
| `--mod M` | One add-on: a zip or a folder holding `metadata.json` folders, used as if it had been dropped into *Custom Mods*. Repeatable. |
| `--addons DIR` | Every `*.zip` in DIR, e.g. the `V25+` folder from `fetch`. See [Latest release](#latest-release-v251--v25-add-ons). |
| `--no-supersede` | Keep the base patches that a newer add-on replaces. |
| `--enable NAME`, `--disable NAME` | Tick or untick a patch by folder name (case-insensitive; the title also works). Repeatable. |
| `--only NAME…` | Tick exactly these patches. |
| `--host-utc-offset ±HH:MM` | Time zone of the Windows machine being emulated. It only affects timestamps. |

`patch` options:

| Option | Meaning |
| --- | --- |
| `--allow-conflicts` | Build even when the static conflict check reports errors. The build still stops if a DFR's original bytes do not match. |
| `--any-disc` / `--no-hash` | Accept a dump that does not match Redump, or skip hashing altogether. |
| `--now T`, `--reproducible` | Timestamps (see [Faithfulness](#faithfulness)). `--reproducible` gives the same bytes on every run and machine. |
| `--release-date YYYYMMDD` | IP.BIN date. The default is `20240825`, the V25.1 wizard's value. |
| `--cdfs-time iso|local` | How the original files' ISO 9660 times are read. |
| `--work DIR`, `--keep-work` | Scratch folder. Peak use is about the patched files plus the output image. |

The exit status is 0 on success and 2 on a known error: bad disc, bad package, conflict, or a DFR
mismatch.

### Supported discs

The Redump dumps the V25.1 wizard has patches for (`tools/sf3patch/identify.py`):

| Disc | Serial | Version | Redump | Data track SHA-1 |
| --- | --- | --- | --- | --- |
| Scenario 1 (USA) | MK-81383 | V1.001 | 20315 | `9b103330…` |
| Scenario 1 (Europe) | MK-81383 | V1.005 | 3494 | `9d8f601c…` |
| Scenario 1 (Japan) | GS-9175 | V1.006 / V2.005 | 17380 / 3509 | `6ae4c9cc…` / `4169bfb4…` |
| Scenario 2 (Japan) | GS-9188 | V1.003 / V2.000 | 20117 / 3508 | `82c157db…` / `e21f7ad5…` |
| Scenario 3 (Japan) | GS-9203 | V1.001 | 3507 | `6a264603…` |
| Premium Disc (Japan) | 6106979 | V1.000 | 28747 | `1b5de342…` |

Scenario 1 (Japan) has a single base patch in V25.1. Its translation comes from the *Sc1 JP Patches*
add-on (see below).

## What the wizard does, and what we reproduce

**Package layout.**
- `Patches/<patch>/metadata.json` gives the title, text, desc, category, enabled and priority.
- `Patches/<patch>/<serial>/` holds files for every version of a disc, and
  `<serial>/<version>/` holds files for one version.
- In those folders, a `NAME.DFR` patches the disc file `NAME`, and any other file either replaces a
  disc file of the same name or is added as a new file.
- `Custom Mods/` works like `Patches/`. `DriveOrder/<serial>.txt` sets the file order on the disc.
  `Data/data.json` holds the release version (`25.1`).

**Which patches are listed.**
- A folder is listed for a disc when it has a `metadata.json` and files in `<serial>/` or
  `<serial>/<version>/`.
- The wizard reads the JSON loosely, Newtonsoft-style. It accepts comments, single quotes and
  trailing commas, and treats priorities with a leading zero as octal, so `"040"` is 32. A missing
  priority means 9999.
- A metadata error stops everything with "Error with patch file".
- The four categories are listed in the wizard's order. Within each category, patches are sorted by
  priority, then by text, using .NET's introsort and a culture compare. `tools/sf3patch/dotnet.py`
  re-implements both, so ties come out in the same order.
- The ticks shown come from `enabled`, and the apply order is the list order.

**Building the files.**
- Root files are placed in DriveOrder order, with unknown names last.
- For each disc file, every ticked patch is applied in order:
  1. a copy of `<serial>/NAME`,
  2. then a copy of `<serial>/<version>/NAME`,
  3. then one DFR, where the version folder's DFR wins over the serial folder's.
- DFR lines are `offset,old,new` in hex. The old bytes are verified ("Old value … is different
  than …") and a DFR can grow the file.
- New files are collected in this order: the version folders of all patches first, then their
  serial folders.
  - Files whose names end in `.DFR` are excluded; this check is case-sensitive.
  - A file is skipped if its name equals a disc file's name, also case-sensitively.
  - The first file found under a name wins, and added names are uppercased.
  - A name that differs from a disc file only in case makes the wizard fail with "File already
    exists". We report the same error.
- `CD*` files (the CDDA stubs) are written as empty files.

**Building the disc.**
- The ISO 9660 image is rebuilt from scratch.
- The system area keeps the original IP.BIN, with these wizard edits:
  - product `SF3TRANS`, version `V25.1`, date `20240825`;
  - areas `JTUBKAEL`, peripherals `AJE`;
  - the title becomes "<original 32> TRANSLATION VERSION 25.1 SF3TRANS.SHININGFORCECENTRAL.COM";
  - the area-code block at 0xE00 is rewritten.
- The PVD carries the wizard's identifiers: SEGA SEGASATURN, SEGA ENTERPRISES,LTD., CAMELOT,LTD.,
  COPYRIGH.TXT / ABSTRACT.TXT / BIBLIOGR.TXT, and the volume label from the original.
- Path tables and a single root directory follow. Directory records use the wizard's sort order and
  carry XA attributes.
- Files are laid out contiguously. The disc file IDs that sfiii-native profiles record (root
  directory index + 2) come out in the same order, which we checked against
  `profiles/scenario3-v25_1.json`: X025 = 0x1DA, X048 = 0x1E5, EFFECT = 0xBF.
- The data track gets 150 post-gap sectors.
- The CDDA file's extent points at the audio track. For a disc with a CD-DA track, the PVD volume
  size is 150 sectors larger than the image, as in the wizard. This is how the wizard's
  `FixExtents` counts the gap, and we keep it on purpose.
- Every data sector is written as Mode 1/2352 with sync, header, EDC and ECC.
- The audio track follows: 150 silent sectors, then the original audio from INDEX 01.
- The single-file CUE puts track 2's `INDEX 00` on the data post-gap and `INDEX 01` at the start of
  the silence, as the wizard does. Lines end in CRLF.

**Where we are stricter.**
- The wizard's own conflict check compares only each patch's first file. Ours checks every byte
  range:
  - Overlapping DFRs whose old bytes do not match the earlier patch's new bytes → error.
  - Intended stacking → warning.
  - A replacement after another patch changed the file → warning, because the later file wins.
  - A case-only name clash → error.
- We stop with an error where the wizard would crash or silently write a broken disc: a root
  directory over its size, subdirectories, MPEG/Mode 2 files, more than one audio track, invalid
  d-characters and DFR mismatches.

## Latest release (V25.1 + V25+ add-ons)

V25.1 is the last full package. The later fixes are separate zips in
<https://sf3transftp.shiningforcecentral.com/V25+/>. `fetch` downloads them all, except
`WinScalingFix.zip`, which is a fix for the Windows app and not a game patch.

`--addons <V25+ folder>` loads each zip as if it had been dropped into *Custom Mods*. There are two
deviations from what you would get by doing that by hand, and both are printed when the tool runs:

1. **Superseded patches are dropped.** Five add-ons are newer versions of base patches. Keeping both
   would apply the change twice or fail the DFR check, so the old version is removed
   (`selection.SUPERSEDES`):
   - Blacksmith Interface Update v3.1 replaces v2.02.
   - Blacksmith Results v2.1 replaces v1.4.
   - Critical and Counter Fix v1.11 replaces *Critical and Counter Fix*.
   - Irene Insane Buff 1.02 replaces *Irene Insane Buff*.
   - Rogan Sprite Fix v5 replaces *Rogan Sprite Fix*.

   For the last two pairs, the old version is dropped from both the base package and the JP bundle.
   Other add-ons whose names only look like newer versions trigger a warning and both copies are
   kept. `--no-supersede` turns the dropping off.
2. **Magic Resistance Icons v2 is unticked by default.** It rewrites the same `X017.BIN` bytes as
   *Mod Essentials 0.5.1* and *Elemental Icons 3.0*. Those two stack cleanly with each other, and
   Elemental Icons says it requires Mod Essentials. With all three ticked, the build would fail. To
   use Magic Resistance Icons instead, pass
   `--enable "Magic Resistance Icons v2" --disable "Elemental Icons 3.0" --disable "Mod Essentials 0.5.1"`.

Apart from these two, add-ons keep their own `enabled` ticks. *Sc1 JP Patches 2024-10-17* is a
bundle of several mod folders, each with its own `metadata.json`. We find them at any depth. The
wizard itself only looks one level down, so for a real wizard install you would move them up into
*Custom Mods* first.

Blacksmith Interface Update v3.1 replaces `X5STOIN.BIN` after the Sc2 translation has replaced it.
Its file is the translated file with 45 bytes changed, so this is intended, and it is reported only
as a warning.

With these rules, the static check passes with no errors for every disc and revision, for both
V25.1 and V25.1 + V25+. This was checked against the real package without a disc, using the
DriveOrder file names. All 552 DFRs in the base package and add-ons parse, and every
`metadata.json` loads.

| Disc | V25.1 listed / ticked | V25.1 + V25+ listed / ticked |
| --- | --- | --- |
| MK-81383 V1.001, V1.005 | 28 / 17 | 40 / 21 |
| GS-9175 V1.006 | 1 / 0 | 21 / 13 |
| GS-9175 V2.005 | 1 / 0 | 25 / 17 |
| GS-9188 V1.003 | 24 / 13 | 34 / 16 |
| GS-9188 V2.000 | 22 / 12 | 33 / 16 |
| GS-9203 V1.001 | 23 / 15 | 30 / 18 |
| 6106979 V1.000 | 13 / 10 | 22 / 14 |

## Faithfulness

**What should match the wizard byte for byte:**
- the list and tick defaults and the apply order;
- the contents of every file;
- IP.BIN, the PVD strings, the path tables, the directory order, and every file's LBA and size;
- the volume size, the EDC/ECC, the audio placement and the CUE text.

**What cannot match by nature:**
- The timestamps in directory records and the PVD, because the wizard uses its own clock and time
  zone:
  - DFR-patched files are stamped with the time the patch runs (`--now`).
  - Copied files carry their source file's mtime. For zips, we take it from the zip entry's DOS
    time read in the host zone.
  - The original files' times depend on how Windows CDFS reports them (`--cdfs-time`).
  - The root directory and the CD stubs depend on the host's UTC offset (`--host-utc-offset`).

  `compare` ignores times unless you pass `--times`, and masks the PVD's dates.
- `--reproducible` pins all of these: UTC host, and DFR files stamped with the disc's root time. Two
  runs then give identical output, but not the wizard's bytes.

**What sfiii-native cares about does not depend on timestamps.** A profile's `content_sha256`
covers IP.BIN, every file's size and SHA-1, and the audio from INDEX 01. It does not cover times or
LBAs. `patch` and `identify --content-id` print this value and name the checked-in profile it
matches, if any. `identify --content-id` on an unpatched Redump dump names the original disc and
tells you to run `patch` first.

Measured on the Redump dumps (2026-10, sf3patch and the official V25.1 wizard give the same value
for the default selection; see *Validation against the real wizard* below):

| Disc | State | `content_sha256` |
| --- | --- | --- |
| MK-81383 V1.001 (Sc1 USA) | unpatched | `54aa1d2178407d7273a7fb54a7aef4b36c8364cc3b203acb997613e95eea81a9` |
|  | V25.1 default | `0dee501e8ae60d10a288530d9f9161ae224786f08bb841a87a28e10efdccb1b5` |
|  | V25.1 + V25+ | `64d62cfbd5756944f5349d1e7f727ff51a74e4e364e786d1cfb6cde4a2f5ff71` |
| GS-9188 V1.003 (Sc2) | unpatched | `a855681edd77c5dd816033dc73dfc891c7e09048ecb9e45c85375dfc1543cc22` |
|  | V25.1 default | `b967f06797b5d14f3612af8468f77e059f60402728bb8159003a539514b75d27` |
|  | V25.1 + V25+ | `6e702ff5efa1646f094143c4f2684e98c12505e883c65473b19a9cad684e70a0` |
| GS-9188 V2.000 (Sc2 Rev A) | unpatched | `d5def91943d7212174583fd0ca0f5ac0d031915c610aa4a2e4fe447fd2b16e38` |
|  | V25.1 default | `1b835e56ea92ed8211ef603e4c82f923b26414fc881a177fa251be6a6a3e7dd9` |
|  | V25.1 + V25+ | `e2dd53f65e94146bff4cc86ef035fd8a26d6599cbdcba1678c88628ecd2ae1db` |
| GS-9203 V1.001 (Sc3) | unpatched | `598c40eab6a453e2a1fb8f4306b7d4d87f7ff8effea7f5dea43877fc6c886356` |
|  | V25.1 default | `3fe9ec348e5feada7b15a28291f765c76d3cfbb41bef41378f9867e189ba987c` |
|  | V25.1 + V25+ | `1b4d7442304cba8aad70e98d5d3188b0a404e4f81748689fc3df081e3b96bae8` |
| 6106979 V1.000 (Premium Disc) | unpatched | `9a422bc58ae0dd9b00faad42c731e099c7a39a668fc4ebc43f4d08f0369bd5bb` |
|  | V25.1 default | `a5976aa84d438c6d0dd3365e1108e19f0816a628780ecc8f42adb1df13450ac2` |
|  | V25.1 + V25+ | `59d93cf9cb42648e77cb7960751d96398c558c987cddebfa5bf64eeb9b4596f3` |

The full values are in `tools/sf3patch/identify.py` (unpatched) and in the `profiles/*-v25_1*.json`
files (patched). **Correction:** this page used to say the default Sc3 selection should give
`5a50848f…`, the value of the upstream `scenario3-translation-v25_1` profile. It does not: both
sf3patch and the official wizard give `3fe9ec34…` from the Redump dump. We cannot tell how the
upstream image was made (another wizard build, other ticks, or another dump). That profile is kept
unchanged, and `scenario3-translation-v25_1-redump` was added for the Redump result.

**Still unverified:**
- the wizard's timestamps on real Windows CDFS (under Wine they cannot be reproduced, see below);
- the `--addons` selection against the wizard (only the default selection was compared);
- whether ties in the culture compare could ever differ. None occur in V25.1: no two patches in a
  category share both priority and text. With the add-ons, the JP bundle repeats some base patches'
  text and priority, but for GS-9175 only, where the base copies are not listed.

The tests cover all formats with synthetic data only. EDC/ECC is checked against an independent
bit-level CRC and GF(2⁸) syndrome check.

## New disc profiles from `content_sha256`

1. Patch the disc and note the printed `content_sha256`, e.g. with the latest add-ons.
2. If no profile matches, copy the closest profile in `profiles/` (same scenario), give it a new
   `id`, `title` and `version`, and set `content_sha256`.
3. Re-check every address and file ID in its `evidence` with the patched image:
   - File IDs are the root directory index + 2 (count the root directory records in order; `compare` reports whether two images' order differs).
   - Moved code must be re-audited (`tools/audit-modules.py`, `tools/validate-modules.py`) before
     the profile can be trusted. Add-ons such as Mod Essentials change code in `X014`/`X017`.
4. Never commit anything taken from the disc other than what the existing profiles already contain:
   addresses, IDs and hashes.

## Validation against the real wizard

Done in October 2026 for the default selection on all five Redump dumps: MK-81383 V1.001,
GS-9188 V1.003 and V2.000, GS-9203 V1.001 and 6106979 V1.000. The official V25.1 wizard
(`SF3Translation.exe`, .NET 5) ran headless under Wine 10 and Xvfb. Each output was compared with
ours:

```sh
python3 -m tools.sf3patch compare ours.cue wizard.cue
```

Result: **identical (timestamps not compared) for all five discs**. All file contents, IP.BIN, the
directory order, LBAs, the volume size, EDC/ECC, the audio and the CUE text (CRLF line ends) are the
same. For Sc3, a raw `cmp` of the data tracks differs in 2668 bytes, all in sectors 16-46. Every one
of them is a timestamp: the file times in the directory records and the root record time in the
PVD. Every patched image also passes an independent EDC/ECC check of all Mode 1 sectors and extracts
with `7z` like the original.

Why timestamps cannot match under Wine: the wizard takes original-file times from
`File.GetCreationTimeUtc` on the CD, and the root time from `Directory.GetCreationTime`. Wine
reports the Linux birth time of the files it serves, so these are the time the disc was copied to
the fake drive, not the ISO record times. On real Windows CDFS they would be the ISO times
(`--cdfs-time`). Nothing in sfiii-native depends on them.

### How the headless run was done

The wizard has no batch mode. It reads the disc from a CD-ROM drive letter, checks the volume label
and the TOC, and asks for the output path in a save dialog. We used a throw-away harness outside
the repo (not committed, because it is specific to one machine):

1. A Wine prefix with the .NET 5 desktop runtime. Drive `D:` is set to type `cdrom` in
   `HKLM\Software\Wine\Drives` (`/reg:64`), with `d:` pointing at a directory holding the
   extracted data track (`7z x`) and `d::` pointing at the data track as a 2048-byte ISO.
2. A small `LD_PRELOAD` shim answers the Linux CD-ROM ioctls (TOC, Q subchannel) for that device,
   with the real track layout (data track, 150-frame pregap, audio track).
3. The volume label: Wine looks up the label through the DOS device that holds the ISO file. We put
   the ISO on its own tmpfs, mapped it as `e:`, and wrote the PVD volume id into a `.windows-label`
   file there. Without this the wizard sees an empty label and does not offer the disc.
4. `xdotool` drives the dialogs: Return on the welcome page, then Right and Return to accept the
   default ticks. The save dialog has no title, so it is found by its size. The output path is typed
   in and Return is pressed.

Still to do: the same comparison with a few `--enable`/`--disable` changes and with `--addons`,
and a run on real Windows to check the timestamp rules.
