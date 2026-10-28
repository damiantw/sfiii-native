# Shining Force III Recomp: Scenarios 1, 2 & 3 (native port)

**sfiii-native** is an unofficial, experimental native PC port of Sega Saturn's **Shining Force III**, built by
*static recompilation*: the game's SH-2 code is translated to C++ on your machine, from your own disc, and
compiled for the host. A runtime ([saturn-recomp](https://github.com/callumjenkins/saturn-recomp)) provides the
Saturn hardware (VDP1/VDP2 graphics, SCSP sound, CD block, backup memory, input), so static recompilation does
not remove the need to model those systems.

This repository is a fork of [mattkuhnQAAI/sfiii-native](https://github.com/mattkuhnQAAI/sfiii-native), which
is Windows-first. The fork adds a Linux build (also packaged for macOS), a Linux translation patcher
(`sf3patch`), profiles for the Translation Project V25.1 discs, an optional accurate CD-drive timing mode, and a
large automated test harness. Upstream's Windows releases, artwork tools and documentation are kept below.

> **Status: work in progress.** All three scenarios boot, play and save, and save transfer between scenarios works.
> End-to-end playthroughs of every scenario are still being tested. The Premium Disc is **not supported** yet.
> See [Status and known issues](#status-and-known-issues).

## Contents

- [Supported discs](#supported-discs)
- [Requirements](#requirements)
- [Downloads (upstream releases)](#downloads-upstream-releases)
- [Building on Linux and macOS](#building-on-linux-and-macos)
- [Patching discs with sf3patch](#patching-discs-with-sf3patch)
- [Running](#running)
- [Saves and transfer between scenarios](#saves-and-transfer-between-scenarios)
- [Status and known issues](#status-and-known-issues)
- [Testing](#testing)
- [License and clean-room policy](#license-and-clean-room-policy)
- [Credits](#credits)

## Supported discs

A disc is identified by its **contents** (a SHA-256 of its file manifest, the profile's `content_sha256`), not
by its file name or patch label. Each supported disc has a profile in [`profiles/`](profiles):

| Scenario | Base disc | Translation | Profile |
| --- | --- | --- | --- |
| Scenario 1 | USA MK-81383 V1.001 | Translation Project **V25.1 + V25+ add-ons** (`--addons`, default add-on selection) | `scenario1-v25_1-addons.json` |
| Scenario 1 | USA MK-81383 V1.001 | none (official English release) | `usa-v1.001.json` |
| Scenario 1 | USA MK-81383 V1.001 | Translation Project **V25.1** (default selection) | `scenario1-v25_1.json` |
| Scenario 2 | JP GS-9188 V2.000 (Rev A) | Translation Project **V25.1 + V25+ add-ons** (`--addons`, default add-on selection) | `scenario2-v25_1-addons-v2_000.json` |
| Scenario 2 | JP GS-9188 V1.003 | Translation Project **V25.1 + V25+ add-ons** (`--addons`, default add-on selection) | `scenario2-v25_1-addons-v1_003.json` |
| Scenario 2 | JP GS-9188 | Translation Project **v24** (upstream's registered disc) | `scenario2-v24.json` |
| Scenario 2 | JP GS-9188 V1.003 | Translation Project **V25.1** | `scenario2-v25_1-v1_003.json` |
| Scenario 2 | JP GS-9188 V2.000 (Rev A) | Translation Project **V25.1** | `scenario2-v25_1-v2_000.json` |
| Scenario 2 | the v24 disc, migrated to V25.1 (translation only; experimental, not a clean-disc patch) | Translation Project **V25.1** | `scenario2-v25_1-upgrade.json` |
| Scenario 2 | a supplied V1.003 image whose header reports V24 (experimental; exact translation version unverified) | Translation Project V25 (supplied; unverified) | `scenario2-supplied-v1003.json` |
| Scenario 3 | JP GS-9203 V1.001 (Redump dump) | Translation Project **V25.1 + V25+ add-ons** (`--addons`, default add-on selection) | `scenario3-v25_1-addons-redump.json` |
| Scenario 3 | JP GS-9203 V1.001 | Translation Project **V25.1** (upstream's registered disc) | `scenario3-v25_1.json` |
| Scenario 3 | JP GS-9203 V1.001 (Redump dump) | Translation Project **V25.1** | `scenario3-v25_1-redump.json` |

The launcher has **three game entries, one per scenario**. Each entry accepts every registered revision of its
scenario, and the first one listed above for it is the recommended disc. The Scenario 1 V25.1 profile is upstream's
(`scenario1-translation-v25_1`). This fork first registered the same disc as `scenario1-usa-translation-v25_1`
(`scenario1-usa-v25_1.json`). Data folders prepared under that id keep working. The next **Prepare game** records
the new id. The two newer Scenario 2 profiles come from upstream, and the fork has not soak-tested them yet.

The **V25.1 + V25+ add-ons** discs are the recommended discs. They are the output of `tools/sf3patch patch --addons`
with the whole V25+ folder from `fetch` and nothing else changed: every add-on, the five base patches that newer
add-ons replace dropped, and *Magic Resistance Icons v2* left off (see
[docs/translation-patcher.md](docs/translation-patcher.md#latest-release-v251--v25-add-ons)). Their validation is in
[docs/linux-bringup.md](docs/linux-bringup.md#add-on-profiles-v251--v25).

An unknown disc is refused with its content id, and the launcher writes a local `unregistered-disc.json`
identification report to the data folder. Existing saves and builds are not replaced. A different revision of the
same scenario needs its own data folder.

**Not supported yet:**

- The **Premium Disc**. `sf3patch` can patch it, but there is no native profile.
- Other **add-on selections**: `--addons` combined with `--mod`, `--enable`, `--disable` or `--no-supersede`, or
  only some of the V25+ zips. Each selection gives different disc contents, so identity checks reject them.
- Other revisions and regions (for example the European Scenario 1), other patch versions or selections,
  parent/delta CHDs and ISO input.

The Scenario 1 USA data-track SHA-256 is `089c77470dec14f1dbffaad1ab50d584f06df5e28b475fc712b8e67e5890f951`.
To check a dump, `python3 -m tools.sf3patch identify DISC.cue --content-id` prints its Redump match and content id.

## Requirements

- **Your own discs.** Use a Redump-style BIN/CUE or a standalone CHD that you dumped yourself. **No game data,
  disc images, BIOS, saves, translation patches or generated game code are included or distributed**. None of
  these may be committed or attached to issues or pull requests; `tools/check-source-package.py` enforces this.
- **No BIOS is needed to play.** The runtime provides the Saturn BIOS services at a high level. A real BIOS is only
  needed for optional comparison tests against Beetle Saturn. Use your own dump, passed by path.
- **Linux:** an x86-64 desktop (Ubuntu 22.04 or newer is the target) with Vulkan drivers.
- **macOS:** macOS 13 or newer on Apple Silicon (Intel Macs are also built in CI).
- **Windows:** Windows 10 (1903 or newer) or 11, x64, with .NET Framework 4.8 and a Vulkan or Direct3D 12 GPU. This is
  upstream's release; see [desktop setup](docs/DESKTOP.md).
- Several GB of free disk space. Preparation compiles the game locally, which takes about 8–11 minutes on two cores.

## Downloads (upstream releases)

The fork has no releases of its own yet. Upstream's published packages are:

- **Windows x64:** [v0.6.0-preview1](https://github.com/mattkuhnQAAI/sfiii-native/releases/tag/v0.6.0-preview1).
  1. Extract the whole ZIP and open **SFIII Native.exe**.
  2. Choose the scenario, your CUE or CHD, and a data folder.
  3. Click **Prepare game**, then **Play**.

  There is also an optional
  [offline AI graphics builder](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.6.0-preview1/SFIII-Offline-Graphics-Builder-0.6.0-preview1-Windows-x64.zip).
  See [docs/DESKTOP.md](docs/DESKTOP.md).
- **Linux x64, Apple Silicon and Intel Mac:**
  [v0.5.0-alpha](https://github.com/mattkuhnQAAI/sfiii-native/releases/tag/v0.5.0-alpha). See
  [docs/POSIX.md](docs/POSIX.md).

Upstream releases accept only upstream's registered discs (Sc1 USA, Sc2 v24 and Sc3 V25.1), and they do not include
the fork's changes. To use the V25.1 profiles and the fork's fixes, build from source.

Windows source builds follow [docs/BUILDING.md](docs/BUILDING.md): run `tools\setup-dependencies.ps1`, then
`tools\prepare-game.ps1 -Cue ... -Work ...`.

## Building on Linux and macOS

The build produces the same self-contained package as CI. It contains a launcher with its own Python, compiler
(Zig), CMake, Ninja, SDL3 and chdman, all pinned in
[`desktop/posix-dependencies.json`](desktop/posix-dependencies.json). The game itself is generated and compiled
later, from your disc, when you **prepare** it.

**1. Host packages (Linux, Debian/Ubuntu).** You need Python 3.12 or newer.

```sh
sudo apt-get install -y git python3 cmake ninja-build clang g++ patchelf xvfb xauth mesa-vulkan-drivers \
  libvulkan-dev libgl1-mesa-dev libegl1-mesa-dev libdrm-dev libgbm-dev libdecor-0-dev libibus-1.0-dev \
  libsndio-dev libxinerama-dev libxv-dev libxxf86vm-dev libx11-dev libxcursor-dev libxext-dev libxi-dev \
  libxrandr-dev libxss-dev libxtst-dev libxkbcommon-dev libwayland-dev wayland-protocols libasound2-dev \
  libpulse-dev libdbus-1-dev libudev-dev
```

On macOS (Apple Silicon), install Python 3.12+ and the Xcode command line tools.

**2. Shaders.** The package needs two SPIR-V shaders, compiled with the pinned Microsoft DXC. This is the same step
as in [`portable.yml`](.github/workflows/portable.yml). The pinned DXC build is for Linux. On a Mac, either compile
the shaders on a Linux machine and copy the folder over, or download the `project-shaders` artifact of the
`Linux and macOS candidates` workflow. Run this from the repository root:

```sh
export SHADERS=$HOME/sfiii-shaders
python3 -B - <<'PY'
import hashlib, json, os, subprocess, tarfile, urllib.request
from pathlib import Path
root = Path(os.environ['SHADERS']); (root/'dxc').mkdir(parents=True, exist_ok=True)
spec = json.loads(Path('desktop/posix-dependencies.json').read_text())['dxc']
archive = root/'dxc.tar.gz'
urllib.request.urlretrieve(spec['url'], archive)
assert hashlib.sha256(archive.read_bytes()).hexdigest() == spec['sha256']
with tarfile.open(archive) as t: t.extractall(root/'dxc', filter='data')
for name in ['geometry', 'hd-assets']:
    subprocess.run([str(root/'dxc/bin/dxc'), '-T', 'ps_6_0', '-E', 'main', '-O3', '-spirv', '-fspv-target-env=vulkan1.0',
                    f'native/{name}.hlsl', '-Fo', str(root/(name + '.spv'))],
                   check=True, env={**os.environ, 'LD_LIBRARY_PATH': str(root/'dxc/lib')})
PY
```

**3. Package.** Run this from the repository root, on Linux or macOS. Keep the output outside the checkout:

```sh
python3 -B tools/package-posix.py --out ../build/sfiii-package --cache ../build/sfiii-cache --shaders "$SHADERS"
```

On Linux this writes `../build/sfiii-package/SFIII Native/`, and on macOS it writes `SFIII Native.app`. The
package build also fetches the pinned saturn-recomp runtime and applies the fork's
[`tools/runtime-diagnostics.patch`](tools/runtime-diagnostics.patch).

Each run of the `Linux and macOS candidates` workflow on `main` attaches prebuilt packages as artifacts, for
`linux-x86_64`, `darwin-aarch64` and `darwin-x86_64`. Mac packages are ad-hoc signed, not notarized.

For developers, [docs/linux-bringup.md](docs/linux-bringup.md) has the exact checks: the source audit, the unit
tests and the runtime regression targets. It also explains how to fetch the pinned runtime by hand. Before
pushing, run `python3 -B tools/check-source-package.py --tracked` (see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)).

## Patching discs with sf3patch

[`tools/sf3patch`](tools/sf3patch) applies the
[Shining Force III Translation Project](https://sf3trans.shiningforcecentral.com/) patches on Linux, without the
Windows PatchWizard or Wine. It needs Python 3.12+ and `7z`, plus `chdman` for CHD input. With the default
selection, its output is identical, file for file, to the official V25.1 wizard's on all five supported dumps:

- Sc1 USA
- Sc2 V1.003
- Sc2 V2.000
- Sc3
- the Premium Disc

```sh
python3 -m tools.sf3patch fetch --dest ~/sf3trans                  # wizard (V25.1) and the V25+ add-ons
python3 -m tools.sf3patch identify DISC.cue --content-id            # Redump match, serial, version, content id
python3 -m tools.sf3patch list DISC.cue --package ~/sf3trans/SF3Patch.exe     # what the wizard would tick
python3 -m tools.sf3patch patch DISC.cue --package ~/sf3trans/SF3Patch.exe -o ~/sf3/sc3-v25_1.bin
python3 -m tools.sf3patch compare a.cue b.cue                       # file-by-file comparison of two images
```

To get a disc the native port accepts, use `--addons` with the whole V25+ folder from `fetch` (recommended), or the
**default V25.1 selection** (no options), and no `--mod`, `--enable`, `--disable` or `--no-supersede`:

```sh
python3 -m tools.sf3patch patch DISC.cue --package ~/sf3trans/SF3Patch.exe --addons ~/sf3trans/V25+ -o ~/sf3/sc3-v25_1-addons.bin
```

The other options (`--mod`, `--only`, `--no-supersede`, `--reproducible`, `--any-disc`, ...) are
described in [docs/translation-patcher.md](docs/translation-patcher.md). Patch packages and patched images stay
outside the repository, and `patch` refuses to write inside it. Do not redistribute them.

## Running

**Launcher.** Open `SFIII Native` (Linux) or `SFIII Native.app` (macOS) and choose the scenario. **Browse** to your
CUE or CHD, and pick a separate, writable data folder for each scenario. Click **Prepare game**, then **Play**.
Each scenario entry accepts any of its [supported discs](#supported-discs). **Save manager** imports or exports
ordinary saves (see [Saves](#saves-and-transfer-between-scenarios)).

**Command line (Linux).** You can run the launcher's two steps directly:

```sh
PKG="../build/sfiii-package/SFIII Native/payload"
WORK="$HOME/.local/share/SFIII Native/Scenario1-USA"
"$PKG/python/bin/python3" -B "$PKG/app/desktop/prepare_posix.py" --cue ~/sf3/sc1/disc.cue --work "$WORK" --scenario 1
"$PKG/python/bin/python3" -B "$PKG/app/desktop/run_posix.py" --work "$WORK"
```

`--scenario` is `1`, `2` or `3`. `run_posix.py` also takes:

- `--state FILE` to start from a native save state
- `--separate-saves` to turn off the shared backup memory
- `--shared-saves DIR` to choose its folder

See [Saves](#saves-and-transfer-between-scenarios).

**Fast loading vs. accurate drive.** By default, CD reads complete quickly, so loading is faster than on a
Saturn. **`--accurate-drive`** makes the drive seek before each read and read at the real 2× speed, and makes the
SH-2 bus and CD block timing follow the hardware more closely. Loads then take as long as on a real console. When the
flag is off, the default mode is unchanged. The launcher does not expose the option yet. To use it, run the
prepared binary directly with the same save and settings files the launcher uses. A direct run does not merge or
lock the shared memory, so close other games first:

```sh
"$WORK/$(cat "$WORK/native-build.txt")/saturn" --cue ~/sf3/sc1/disc.cue \
  --save "$HOME/.local/share/SFIII Native/Shared Backup Memory/backup.bin" \
  --settings "$WORK/settings.ini" --accurate-drive
```

That `--save` path is the Linux default. With separate saves, use `"$WORK/experimental-backup.bin"` instead.

Other `saturn` options include:

- `--fullscreen` and `--scale N`
- `--headless --vblanks N`
- `--state-in FILE` and `--state-out FILE`
- `--record-input FILE` and `--input FILE`
- `--clock`
- `--coverage FILE`

`saturn --help` (or any unknown option) prints the full usage.

**In game.**

| Action | Keys |
| --- | --- |
| Move | Arrow keys |
| Start | Enter |
| A / B / C | Z / X / C |
| X / Y / Z | A / S / D |
| L / R | Q / W |
| Menu | Escape |
| Fullscreen | F11 |
| Game speed (1×/2×/3×) | F6 |
| Save / load a native state | F5 / F9 |

Bind gamepads in **Controller Setup**. See [docs/USAGE.md](docs/USAGE.md).

## Saves and transfer between scenarios

Like one Saturn, **all scenarios share one backup memory by default**, so a finished scenario carries over to the next
with no manual step. Full details are in
[docs/USAGE.md](docs/USAGE.md#shared-backup-memory-campaign-carryover).

- **Shared files.** The shared memory is `backup.bin` (internal, 32 KiB) and `backup.bin.cartridge` (cartridge,
  512 KiB), kept in:
  - Linux: `$XDG_DATA_HOME/SFIII Native/Shared Backup Memory` (default `~/.local/share/SFIII Native/Shared Backup Memory`)
  - macOS: `~/Library/Application Support/SFIII Native/Shared Backup Memory`
  - Windows: `%LOCALAPPDATA%\SFIII Native\Shared Backup Memory`

  To use another folder, pass `run_posix.py --shared-saves DIR` (or `-SharedSaveDir` on Windows). The folder must
  be outside every game-data folder. Each game-data folder gets a `shared-backup-memory.txt` that names the file in
  use. Saves are written to disk the moment the game saves.
- **Scenario transfer.**
  1. Finish a scenario and write its **COMPLETE** save.
  2. Start a new game in the next scenario. Its own import ("continue your previous adventure?") offers the record.

  In Scenario 2, the start menu defaults to *Continue* when Scenario 2 already has its own save. Press **Up** to
  choose *Begin* for a new game with the import. Scenario 3 offers only a COMPLETE record. The Sc1 → Sc2 and
  Sc2 → Sc3 transfers were checked byte for byte against Beetle Saturn.
- **One-time migration.** At launch, existing per-scenario `experimental-backup.bin(.cartridge)` files are merged
  into the shared memory, save by save:
  - Original files are never changed or deleted.
  - Before any write, the shared files are copied to `migration-backups/<UTC time>/`.
  - `shared-saves.json` reports what happened to every save.
  - Identical saves are stored once. A different save with the same name gets the next free slot name.
  - A save that fits nowhere is **not dropped**. It stays in its original file, is reported with a warning, and is
    retried at every launch.
- **Capacity warning.** At each launch the launcher warns when internal memory cannot fit a new save of the scenario
  you start, and when both devices are full. The warning appears in the status line and as `SF3 saves:` in the log.
  - Internal memory has 510 usable blocks. It holds one Sc3 save (382 blocks), or one Sc1 save (204) and one Sc2
    save (256).
  - The cartridge has 1022 usable blocks and holds many saves. If your Sc1 and Sc2 saves are on internal memory,
    save Sc3 to the cartridge.
  - On a full device, the game's own save fails with its normal message. Existing records are never overwritten.
- **One game at a time.** A game session or import locks the shared memory (`backup.lock`). A second game or import
  is refused until the first one closes.
- **Separate saves.** To go back to each data folder's own `experimental-backup.bin`, tick **Separate saves per
  scenario** in the launcher, or pass `--separate-saves` (`-SeparateSaves` on Windows). Transfer then needs
  the **Save manager** import, and the shared memory is left as it is.
- **Native save states** (F5/F9) are tied to one build and one disc, and each holds the whole backup memory of its
  moment. After you load one, the other scenarios' records are put back as they were, so loading an Sc3 state does
  not roll back your Sc2 saves. To keep progress across builds, use an in-game save.
- **Import saves** from emulators or real hardware with the launcher's **Save manager** button (choose *No* /
  import). It writes into the shared memory, or into the folder's own file when separate saves are on. The command-line importer
  `tools/import-saturn-save.py --backup BACKUP.bin [--device internal|cartridge] FILES...` takes no lock, so run it
  only while no game is running.
  - It accepts raw `SFORCE31_XX.BIN`, `SFORCE32_XX.BIN` and `SFORCE33_XX.BIN` saves, and version-1 JSON `.ysbak` exports.
  - Whole backup-RAM images and emulator save states are not supported.
- **Export saves** with **Save manager** (choose *Yes* / export). Pick internal or cartridge memory and a folder. Each
  ordinary save is written there as a raw `.BIN` in a new timestamped folder, for emulator or Saroo save tools. It
  reads the shared memory (after the usual merge of the per-scenario files), or the folder's own file when separate
  saves are on. The game's saves are not changed. Native save states are not Saturn saves and are not exported. From
  the command line: `tools/import-saturn-save.py --backup BACKUP.bin --device internal|cartridge --export DIR`.

## Status and known issues

**What works.** The V25.1 profiles prepare, boot and play on Linux. Upstream tests its own three registered
profiles (Sc1 USA, Sc2 v24 and Sc3 V25.1) on Windows. The fork's automated runs on Linux have been clean:

- autoplay soak runs (a bot drives towns and battles)
- input fuzzing
- save-state round trips
- in-game save and load
- scenario transfers

The story-flag tests and the Beetle comparisons match at their checkpoints. An Apple Silicon package builds and
passes the synthetic tests in CI.

**Still in progress and known issues:**

- **Full playthroughs.** Playthroughs of each scenario, from start to ending, are still running. The automated
  Scenario 2 V2.000 playthrough is currently blocked; this is under investigation.
- **Coverage.** Measured coverage of real game code blocks is about 44–49% for Sc1, about 44% for Sc3 and 40–42%
  for Sc2. Code that has not run yet is not known to work.
- **Premium Disc:** not supported (no profile). Its features cannot be reached from Scenario 3.
- **V25+ add-on discs** are supported with the default add-on selection only. Other selections and revisions are
  not supported (see [Supported discs](#supported-discs)).
- **Platforms.** The V25.1 profiles and the fork's changes have been tested on **Linux only**, mostly headless.
  The macOS package is built and tested in CI. Little or no testing has been done of:
  - real-disc play on a Mac
  - physical GPUs other than the test machines'
  - gamepads other than the Saturn USB pad
- **Rendering and audio** are close to the reference emulator but not certified hardware-exact. The remaining VDP2
  gaps include line colour from rotation coefficients and vertical cell scroll. Upstream's experimental widescreen
  still shows edge gaps where the game culls objects.
- `--accurate-drive` is command-line only.
- **Optional artwork.** Upstream's builder now also decodes supported close-up battle-model textures. One Scenario 3
  battle-model format is still unsupported, and full artwork coverage is not established.

Bug reports are welcome. Never attach disc images, extracted files, saves or BIOS files.

## Testing

All test tooling is data-free. Discs, BIOS files, saves and captures are passed by path and stay outside the
repository. [docs/testing-plan.md](docs/testing-plan.md) has the full plan and results.

- **Unit and regression tests:** `python3 -m unittest discover -s tools/tests`, plus the runtime regression targets
  (DSP, CPU core, backup memory, machine, VDP2 backgrounds, GPU parity). Hosted CI runs them with invented data.
- **Soak:** long autoplay runs, input fuzzing and save-state round trips catch crashes, hangs and lost state.
- **Coverage:** `saturn --coverage` and `tools/sf3-block-coverage.py` measure which game code ran. Map sweeps
  (`tools/sf3-sweep.py`) drive every save record and map.
- **Story replays:** `tools/sf3-story.py` plays forward from saves. It records deterministic, pad-only segments
  (`tools/story-replays/`), which replay frame-exactly with a fixed clock. `sf3-story.py search` finds battle
  inputs by branching and backtracking. Its battle-policy options (all pad inputs only, no RAM pokes) include:
  - `--leader` and `--protect`: units whose fall loses the battle. Protected units avoid danger (they retreat when hurt, in the `--avoid` zone or within `--keep-away`) but still attack a target they can hit without ending next to a stationary enemy; `--passive` slots never attack
  - `--guard-hp`: the HP floor for those units
  - `--escort`: keep units next to a guest
  - `--avoid X,Y,R` or `--avoid X0,Y0,X1,Y1`: leave a trap zone (the tiles within R of X,Y, or that rectangle)
  - `--avoid-all`: every unit, not only the leader and protected units, walks out of the `--avoid` zone, and a hurt unit backing away from enemies never ends its retreat inside it
  - `--zone-fatal [V]`: from VBlank V on (default 0), a window that ends with the leader or a protected unit in the `--avoid` zone loses instead of costing 3
  - `--keep-away`: stay clear of enemies
  - `--focus`: preferred targets
  - `--heal` and `--heal-item`: heal with a spell, or with an item on a hurt neighbour
  - `--leader-attack S`: let the leader walk to and attack an enemy it can finish or one under S of max HP (never through the `--avoid` zone)
  - `--max-deaths` and `--max-levels`: search limits
  - `--slim`: keep only the saves on the search path; a backtrack replays an alternative from its parent
  - `--hold-until N`: units stay out of range of stationary enemies until N units can reach the same target this round, then commit together
  - `--ranged`, `--casters` and `--item-attack`: units that shoot, cast their first attack spell, or use their first item on an enemy within 2 tiles (focus targets first)
  - `--healers`: units that cast Heal on a hurt ally next to them (or walk to one) before attacking
- **Differential testing against Beetle Saturn:** `tools/sf3-diff.py` and `tools/sf3test` run the same inputs on
  the native port and on a libretro core that you build separately and run with your own BIOS. They compare RAM,
  story flags, VDP1/VDP2 output and saves.
- **Determinism and dispatch audit:** repeated runs must match exactly. `SF3_DISPATCH_AUDIT=1` reports indirect
  calls that fall outside recompiled code. Scene (X1) modules also get entries for callbacks that only their own
  data tables point to, when the target decodes as plausible SH-2 code; the build logs every accepted and rejected
  candidate to `scene-data-entries.tsv` in the generated-code directory.

<details>
<summary>Upstream's Windows validation notes (v0.6.0-preview1)</summary>

The v0.6.0-preview1 Windows candidate passed **six runtime regression targets and nine focused Scenario 2 transition routes**: 16 checks including emission. Twelve captured scene/style GPU rendering cases and four live style/state continuations also passed with unchanged native frames. These checks cover the available fixtures, rather than every spell, character animation, transition or campaign. Five older route fixtures are unavailable and were not counted as passing or rerun for this candidate.

The local Windows Python suite ran **113 tests: 112 passed and one POSIX-only file-lock test was skipped**. The release source also [passed hosted source/synthetic checks](https://github.com/mattkuhnQAAI/sfiii-native/actions/runs/40089746216), and [Linux, Apple Silicon and Intel Mac candidates passed their build and synthetic-validation jobs](https://github.com/mattkuhnQAAI/sfiii-native/actions/runs/40089746225). Hosted jobs use invented data and do not validate real-disc gameplay, physical controllers or audio devices. The standalone builder's first-run setup, CHD conversion and limited GPU samples were tested separately on Windows.

With the local three-style artwork set, measured warm artwork-pack initialization dropped from **16.9 seconds to 1.16 seconds** after indexing/caching. This measures artwork initialization on one PC, not complete game launch time or a performance guarantee for other hardware.

The Scenario 1 development audit compiles 252 configured/candidate modules, including 169 X1 scene modules. Its nine-route regression suite exercises 12 X1 scenes; it does not validate all 169 scenes. Three mapping/entry reviews, nine discovery findings and 935 unresolved indirect sites remain review items. X046 now has revision-specific loader evidence for compilation; its gameplay path remains untested. Compilation, emitted entry coverage, executed gameplay and hardware fidelity are separate claims.

The Scenario 2 development audit compiles 285 configured/candidate modules, including 195 X1 scene programs and 59 X3 effects. Historical local routes exercised 14 X1 scenes, including imported-save church/town and battle transitions, Healing Drop use through X3ITEM, the magic menu's no-target path, and an Egress return to the church; this historical coverage is separate from the current candidate's nine-route suite above. There are three mapping/entry reviews, 25 discovery findings and 1159 unresolved indirect sites; the larger indirect-site count includes newly compiled effect code. Repeated native snapshots before and during the item animation matched video, audio and backup contents. Repeated native snapshots during the Egress transition also matched video, audio and backup contents. Other effects, unvisited gameplay and other snapshot times remain unvalidated.

The spell/special dispatch tables have also been reviewed: all 81 Scenario 1, 93 Scenario 2 and 111 Scenario 3 entries resolve to mapped modules or container sections. This is static dispatch coverage, not validation of every spell animation. Additional direct loader/call evidence maps X049 in all three scenarios and X025/X048 in Scenarios 2/3. Seven mapping/entry reviews remain across the revisions: X004 in each scenario, and X019/X3ELEM5 in Scenarios 1/2. X019 in Scenarios 1/2 is modeled as monster-table data; its executable classification remains under review. X3ELEM5 does not appear in the reviewed effect dispatch tables and is not assigned a speculative load address.

The v0.3.0 candidate passed the six required runtime regression targets, the four Scenario 2 routes and 64 GPU shader cases, including 5×, plus native-state and toolbar checks. Synthetic tests cover arithmetic/DSP, storage, DMA, background composition, controller input, checkpoint integrity and GPU rendering. Captured gameplay diagnostics and historical route fixtures stay local. See [development and publication rules](docs/DEVELOPMENT.md).

Scenario 3 v25.1 development compiles 273 configured/candidate modules, including 169 X1 scene programs and 69 separately loaded sections of EFFECT.BIN. Eight Windows routes reach the title, fresh-game setup, ship dialogue, a first-battle screen and a priest interior, exercising five X1 scenes. One module mapping/entry, 17 discovery findings and 1299 indirect sites remain review items; individual container effects have not received gameplay validation. The runtime also reports unimplemented VDP2 scroll/extended-color paths in this route; rendering is not certified hardware-faithful. Downloaded completed saves are isolated test fixtures, never installed as player progress. Broader battles, ordinary in-game saving/loading, full campaign transfers and Linux/macOS Scenario 3 gameplay remain unvalidated.

</details>

## License and clean-room policy

Project source is under the [MIT license](LICENSE). Third-party code keeps its own notices; see
[THIRD_PARTY.md](THIRD_PARTY.md).

- **No GPL code** is copied into this repository. GPL emulators (Beetle Saturn/Mednafen, Yabause) are used only as
  **black boxes**. They are built separately and run by path, and only their outputs (RAM, frames, saves) are
  compared. Fixes are written from hardware documentation, measurements and permissively licensed references.
- Packages bundle MAME's `chdman`, unmodified, as a separate program to read CHDs. It is GPL-2.0; see THIRD_PARTY.md.
- `sf3patch` is our own implementation. The Translation Project's wizard was studied only for its behaviour, and
  none of its code or data is included.
- No game data, disc-derived bytes, BIOS, saves or patch files are committed. Generated game code is built only
  on your machine.

Shining Force III and Sega Saturn belong to their respective rights holders. This is an unofficial project and
grants no permission to redistribute game content.

## Credits

- **[mattkuhnQAAI/sfiii-native](https://github.com/mattkuhnQAAI/sfiii-native)** is the original project. It
  provides the Windows application, the profiles for Sc1 USA, Sc2 v24 and Sc3 V25.1, the optional AI artwork and
  the release screenshots. To support upstream development and testing, you can
  [leave a tip via PayPal](https://paypal.me/mattkuhn14).
- The **[Shining Force III Translation Project](https://sf3trans.shiningforcecentral.com/)** (sf3trans) team made
  the translation and the patches that `sf3patch` applies.
- [saturn-recomp](https://github.com/callumjenkins/saturn-recomp) is derived from
  [saturnkit](https://github.com/vs-sr-dev/saturnkit).
- SFIII module mappings were informed by [SF3Tools](https://github.com/Synival/sf3tools).
- The optional artwork builder's battle-model texture decoder uses format information from the MIT-licensed
  [SF3Unity](https://github.com/AndreasScholl/SF3Unity) parser; its notice is in
  [`LICENSES/SF3Unity.txt`](LICENSES/SF3Unity.txt).
- Controller mappings use [SDL_GameControllerDB](https://github.com/mdqinc/SDL_GameControllerDB).
- Rendering and input use [SDL3](https://github.com/libsdl-org/SDL).

<details>
<summary>Upstream screenshots (Windows, v0.4.0/v0.6.0 previews)</summary>

Windows examples illustrate development progress; they do not establish Linux/macOS gameplay compatibility. Images are release documentation, not downloadable game-asset packs.

**Optional AI artwork:** the same Scenario 2 translated-v24 gameplay frames rendered through the native GPU paths at 5×, with original artwork followed by the three local AI styles. Characters and world textures use the selected style; HUD and menus retain original artwork. These are native renderer compositions of actual captured gameplay states, with identical camera and framing, rather than image-generation mockups. Contact sheets scale the complete images for comparison.

[![Airo village: Original, AnimeVideo v3, x4plus anime and x4plus general](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.6.0-preview1/airo-ai-options.png)](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.6.0-preview1/airo-ai-options.png)

Full-size Airo village: [Original](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.6.0-preview1/scenario2-airo-original.png) · [AnimeVideo v3](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.6.0-preview1/scenario2-airo-video.png) · [x4plus anime](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.6.0-preview1/scenario2-airo-anime.png) · [x4plus general](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.6.0-preview1/scenario2-airo-general.png).

[![Battle formation: Original, AnimeVideo v3, x4plus anime and x4plus general](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.6.0-preview1/battle-ai-options.png)](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.6.0-preview1/battle-ai-options.png)

Full-size battle: [Original](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.6.0-preview1/scenario2-battle-original.png) · [AnimeVideo v3](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.6.0-preview1/scenario2-battle-video.png) · [x4plus anime](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.6.0-preview1/scenario2-battle-anime.png) · [x4plus general](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.6.0-preview1/scenario2-battle-general.png).

The styles can smooth away texture detail or introduce seams. Background-plane replacements and full-campaign artwork validation remain unfinished. **Off** restores original artwork with your selected native rendering resolution.

Earlier screenshots below use original artwork. Click an image to open its full resolution.

| Scenario 1 USA title | Scenario 2 translated v24 title |
| --- | --- |
| [![Scenario 1 USA title screen](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.4.0-preview1/screenshot-scenario1-title.png)](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.4.0-preview1/screenshot-scenario1-title.png) | [![Scenario 2 Translation Project v24 title screen](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.4.0-preview1/screenshot-scenario2-v24-title.png)](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.4.0-preview1/screenshot-scenario2-v24-title.png) |

**Internal resolution comparison:** the same captured Scenario 2 video state rendered through the native GPU renderer at each enhanced scale. Supported geometry is rendered at higher resolution; the original textures and sprites retain their original detail. Open the originals to compare edges, since the previews below share the available page width.

| 2× — 640 × 480 | 4× — 1280 × 960 | 5× — 1600 × 1200 |
| --- | --- | --- |
| [![Scenario 2 town at 2x internal resolution](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.4.0-preview1/screenshot-scenario2-2x.png)](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.4.0-preview1/screenshot-scenario2-2x.png) | [![The same Scenario 2 town frame at 4x internal resolution](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.4.0-preview1/screenshot-scenario2-4x.png)](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.4.0-preview1/screenshot-scenario2-4x.png) | [![The same Scenario 2 town frame at 5x internal resolution](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.4.0-preview1/screenshot-scenario2-5x.png)](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.4.0-preview1/screenshot-scenario2-5x.png) |

**Experimental widescreen at 5× (2135 × 1200):** the same scene with an expanded viewport. Edge gaps and missing scenery remain visible where game-side culling needs more work.

[![Scenario 2 town with experimental widescreen and 5x GPU rendering](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.4.0-preview1/screenshot-scenario2-widescreen-5x.png)](https://github.com/mattkuhnQAAI/sfiii-native/releases/download/v0.4.0-preview1/screenshot-scenario2-widescreen-5x.png)

Selected PNG screenshots are hosted as release documentation, outside the source tree and application packages. Local disc data, video dumps, saves and diagnostic captures remain outside the repository.

</details>

<details>
<summary>Upstream roadmap</summary>

Planned directions, with no release dates or compatibility guarantees. Faithful gameplay, graphics, audio and reliable saves take priority over enhancements.

- **Broader gameplay validation:** exercise more towns, battles, menus and transitions, fixing crashes and rendering/audio defects as coverage grows.
- **More complete widescreen:** improve game-side object and terrain culling so additional scenery remains visible as the camera moves and rotates.
- **More supported editions:** register additional disc revisions while keeping each installation’s progress separate.
- **Scenario 2/3 coverage, Premium Disc and more translations:** expand gameplay validation and add revision-specific compilation profiles, identifying supported patch versions explicitly.
- **Save portability and campaign transfers:** expand verified emulator/Saroo import and export formats, and validate backed-up progress transfers between compatible scenarios and editions.
- **Broader optional artwork coverage:** improve unsupported formats, large images, background planes, texture seams and animation consistency, while retaining original artwork and expanding gameplay validation.
- **Broader native save-state validation:** extend snapshot tests across battles, transitions and additional scenarios, beyond the limited Scenario 2/3 routes tested so far.

These are roadmap items; the supported profiles and tested coverage are listed above.

</details>
