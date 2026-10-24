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
matches, if any. For example, the default V25.1 selection on Redump Scenario 3 V1.001 should print
`5a50848f…` (`scenario3-translation-v25_1`). That profile was made from a real wizard output, so a
match is the acceptance test for a disc. **This has not been run yet:** there is no disc image on the
build machine.

**Unverified, needs a real disc:**
- the exact `content_sha256` for each disc and revision;
- the root time source: we use the root directory record's time;
- whether Windows CDFS applies the ISO GMT offset;
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

## Validating against the real wizard (follow-up)

Not done yet. To validate, run the official V25.1 wizard on the same dump, with the same ticks, and
compare its output with ours:

```sh
python3 -m tools.sf3patch compare ours.cue wizard.cue
```

Expected result: identical apart from times. With `--times`, only the timestamps listed above should
differ.

The wizard is a .NET desktop GUI. It has no command line or batch mode. It
reads the disc from a mounted CD-ROM drive letter, not from an image file, and asks for the output
through dialogs. It is therefore **not headless** under Wine. Running it needs `wine` with a recent
.NET desktop runtime, the image mounted as a Wine CD drive (e.g. via `winecfg` and a loop-mounted
ISO), and a virtual display such as `xvfb-run` with someone or a script (`xdotool`) clicking through
the dialogs. This is planned as a one-off manual check per disc, not as CI.
