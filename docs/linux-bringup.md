# Linux bring-up (native x86-64)

Status as of 2026-10-24 on branch `linux-bringup`. This note covers building and testing on Linux, the Linux fixes so far, the known gaps, and what to do once real discs are available. Upscaling and widescreen are out of scope. The testing strategy for whole-game playability is in [testing-plan.md](testing-plan.md).

Scope of the claims: everything below was verified **without game data**. Synthetic tests, shader tests on software Vulkan, and package validation say nothing about real-disc gameplay on Linux. That stays *unvalidated* until it is run locally with supplied discs.

## Environment used

- Debian 13 (trixie), x86-64, 8 CPUs, no GPU (Mesa lavapipe for Vulkan), Xvfb for windowed tests.
- System clang 19.1.7 and GCC 14 for the developer checks. The package build uses its own pinned Zig 0.15.2, CMake 3.31.10, Ninja, SDL3 and python-build-standalone from `desktop/posix-dependencies.json`.

```sh
sudo apt-get install -y git python3 cmake ninja-build clang g++ patchelf xvfb xauth mesa-vulkan-drivers \
  libvulkan-dev libgl1-mesa-dev libegl1-mesa-dev libdrm-dev libgbm-dev libdecor-0-dev libibus-1.0-dev \
  libsndio-dev libxinerama-dev libxv-dev libxxf86vm-dev libx11-dev libxcursor-dev libxext-dev libxi-dev \
  libxrandr-dev libxss-dev libxtst-dev libxkbcommon-dev libwayland-dev wayland-protocols libasound2-dev \
  libpulse-dev libdbus-1-dev libudev-dev
```

## Exact build steps

All build output stays outside the checkout. The `.gitignore` is a whitelist and `tools/check-source-package.py` audits the tracked source, so never point outputs into the repository.

### 1. Pinned runtime

```sh
git clone https://github.com/damiantw/sfiii-native && cd sfiii-native
python3 -B - <<'PY'
import json, subprocess
from pathlib import Path
spec = json.loads(Path('dependencies.json').read_text())['runtime']
t = Path('.local') / spec['directory']; t.mkdir(parents=True)
g = lambda *a: subprocess.run(['git', '-C', str(t), *a], check=True)
g('init'); g('fetch', '--depth', '1', spec['url'], spec['commit']); g('checkout', '--detach', 'FETCH_HEAD')
g('apply', str(Path('tools/runtime-diagnostics.patch').resolve()))
PY
```

### 2. Disc-free source and runtime checks (same as `synthetic.yml`)

```sh
python3 -B tools/check-source-package.py --tracked --out /tmp/source-check.json
python3 -X utf8 -B -m unittest discover -s tools/tests -p 'test_*.py'
cmake -S tools/tests -B ../build/checks-clang -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ "-DSATURN_RUNTIME=$PWD/.local/saturn-recomp/runtime"
cmake --build ../build/checks-clang --parallel
for t in dsp_regression core_regression bup_regression machine_regression background_regression \
         audio_buffer game_speed hd_presentation; do ../build/checks-clang/$t; done
../build/checks-clang/hd_assets /tmp/hd-assets-out   # needs an output directory argument; exits 2 without one
```

The same set also builds and passes with GCC 14 (`-DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++`). The upstream saturn-recomp `runtime_tests` (77 tests) also pass with system clang.

### 3. Lightweight native host (system toolchain, no package)

This is what `.github/workflows/linux-native.yml` runs on every push and PR:
1. Build the pinned SDL commit from source.
2. Compile the shaders with the pinned DXC.
3. Have the real SH-2 emitter generate its synthetic instruction fixture project (`saturnrecomp.recomp.__main__.generate([], OUT, optest=True, native_states=True)`).
4. Build `saturn`, `selftest`, `controller_setup`, `controller_selftest`, `replay_checkpoint`, `gpu_renderer_selftest`, `gpu_parity`, `replay_ui_selftest` and `native_state_ui_selftest` with clang, using `tools/windows.cmake` as `SATURN_EXTRA` (despite its name it is the platform-neutral project host layer).
5. Run them, with the GPU cases under `xvfb-run` on lavapipe (`SF3_GPU_ALLOW_SOFTWARE=1`).

Read the workflow file for the exact commands. Configure plus build takes about 15 s on 8 cores.

### 4. Self-contained player package (same as `portable.yml`)

```sh
# shaders: pinned DXC (see portable.yml 'shaders' job) -> $SHADERS/{geometry,hd-assets}.spv
python3 -B tools/package-posix.py --out ../build/rt/sfiii-package --cache ../build/rt/sfiii-cache --shaders "$SHADERS"
xvfb-run -a python3 -B tools/validate-posix-package.py --package "../build/rt/sfiii-package/SFIII Native" \
  --out ../build/rt/sfiii-validation
```

The first package build compiles SDL3 and MAME's `chdman` from pinned source, which takes a while (tens of minutes on 8 cores). Later builds reuse `--cache`.

### 5. Preparing and running a disc from a shell (once you have your discs)

The Tk launcher wraps these. They can also be called directly with the bundled Python:

```sh
PKG="../build/rt/sfiii-package/SFIII Native/payload"
"$PKG/python/bin/python3" -B "$PKG/app/desktop/prepare_posix.py" --cue ~/sf3/sc1/disc.cue \
   --work "$HOME/.local/share/SFIII Native/Scenario1-USA" --scenario 1
"$PKG/python/bin/python3" -B "$PKG/app/desktop/run_posix.py" --work "$HOME/.local/share/SFIII Native/Scenario1-USA"
# headless smoke run: add --headless-fields N
```

## Results (this branch, no game data)

| Check | Result |
|---|---|
| `check-source-package.py --tracked` | pass (all tracked files) |
| Python unit tests (`tools/tests`) | 70 OK, 1 skipped (Windows file locking). Was 10 failing before the fix below. |
| dsp / core / bup (15) / machine (4) / background (17) / audio_buffer / game_speed / hd_presentation / hd_assets | pass with clang 19 and GCC 14 |
| saturn-recomp `runtime_tests` | 77 / 77 pass |
| Synthetic AOT selftest | 9300 vectors, 0 failures |
| controller_selftest | 145 checks pass |
| replay_ui / native_state_ui selftests (SDL, dummy video) | pass |
| GPU renderer, Vulkan on lavapipe under Xvfb | 109 shader cases pass. This is software Vulkan, **not** hardware GPU validation. |
| Full package plus `validate-posix-package.py` | all checks pass: CHD round trip, Zig regressions, synthetic AOT (775 functions), controller input, replay/native-state/launcher UI, GPU cases, relocation checks. Report: `synthetic_passed: true`, `gameplay_validated: false`. |

### What I fixed

1. **Launcher tests depended on checkout depth** (`bf3c2b6`). `desktop/prepare.py`'s `external_work(path, package=PACKAGE)` bound the package root at import time. In a checkout one directory below `/`, the root was `/`, so every work directory counted as "inside the application" and the tests' `PACKAGE` patch had no effect. The fix binds it late and patches the package root explicitly in the tests.
2. **Bundled POSIX builds broke when the system has `ld.lld`** (`02b8d8b`). CMake ≥3.29 detects a system LLD and adds `--dependency-file` to link lines, which Zig's linker rejects with "unsupported linker arg". Any Linux player with `lld` installed (common: it comes with clang/LLVM) would have failed at **Prepare game**. The fix passes `-DCMAKE_LINK_DEPENDS_USE_LINKER=OFF` in `prepare_posix.py` and in the package validator's regression configure.
3. **Linux PR CI** (`linux-native.yml`). `portable.yml` only runs on pushes to `main`/`codex/linux-macos`, so a pull request never compiled or ran the native host on Linux. The new job does this on every push and PR in a few minutes, with no game data and no MAME build.

## Linux support review

| Area | State on Linux | Notes / gaps |
|---|---|---|
| Windowing | SDL3: X11 and Wayland (libdecor) both built in. | Real compositors untested (only Xvfb). The Tk launcher from python-build-standalone is X11-only, so it needs XWayland on pure-Wayland sessions. |
| Vulkan renderer | SDL_GPU Vulkan, SPIR-V shaders from pinned DXC. Software Vulkan is refused unless `SF3_GPU_ALLOW_SOFTWARE=1`, falling back to the SDL renderer plus CPU geometry. | No hardware GPU (Mesa radv/anv, NVIDIA) tested yet. |
| Input | SDL gamepad plus SDL_GameControllerDB mappings found next to the executable or in `SF3_CONTROLLER_DIR`. 145 synthetic checks pass. | **Controller setup is console-interactive** (`std::getline` on stdin). The POSIX launcher starts it with stdout piped and no terminal, so from a desktop launch there is nowhere to type. Skip/cancel mid-binding (`S`/`Esc`) exists only under `_WIN32` (conio). Messages mention "Windows Bluetooth settings". Physical pads untested. Steam Input / Steam Deck unverified. |
| Audio | SDL3 audio stream, S16 stereo 44.1 kHz. PulseAudio and ALSA backends in the package (PipeWire via its Pulse server). | The package's SDL is built without PipeWire dev headers, so there is no native PipeWire backend. That works on PipeWire distros through pipewire-pulse, but it is untested on hardware. |
| Paths | Runtime data dir follows `$XDG_DATA_HOME` (else `~/.local/share`). Launcher data root is `$XDG_DATA_HOME/SFIII Native/<scenario folder>`. | No `.desktop` file or icon install. That's fine for a portable folder, but there's no AppImage/Flatpak. |
| Saves | Backup RAM in the work dir: `experimental-backup.bin` (+ `.cartridge`). BIN/YSBAK import via `import-saturn-save.py`. Atomic renames. | Cross-platform save portability is believed byte-identical but untested on Linux. |
| Packaging | `package-posix.py` builds a self-contained folder: Python, Zig cc, CMake, Ninja, SDL3, chdman. Preparation compiles the game locally with Zig. | No release artifact for Linux on this fork yet. glibc floor follows the Ubuntu 22.04 build host in `portable.yml`. |
| Developer workflow | The Python tools are cross-platform. | Source-tree helper scripts (`prepare-game.ps1`, `build-scenario1.ps1`, `setup-dependencies.ps1`, `run-native.ps1`) are PowerShell-only. On Linux use the package CLI (above) or call the Python tools directly. |
| Real-disc play | Never run on Linux. | Needs supplied discs: see "When the ISOs arrive". |

## Disc revision profiles: how they work and what a new one needs

This is the most important part for the top roadmap item. The aim is to support the **latest Shining Force III Translation Project release** (V25.1 plus the post-release updates published under `https://sf3transftp.shiningforcecentral.com/V25+/`) for every scenario. Upstream registers Sc1 *unpatched* USA V1.001, Sc2 translation **v24**, and Sc3 V25.1. Branch `latest-translation-profiles` adds the V25.1 default selection for Sc1 USA, Sc2 on both bases and the Redump Sc3 dump; see *Latest-translation profiles* below.

### Identity

`tools/disc_profile.py identify()` computes `content_sha256` = sha256 of the JSON of `saturnrecomp.disc.manifest(disc)`. That covers:
- product code and version
- area codes
- IP.BIN sha1
- size and sha1 of **every** non-CDDA file
- frame count and sha1 of every audio track

It then picks the first `profiles/*.json` whose `content_sha256` matches. Consequences:
- **Any** byte change to any file (any optional patch, a different PatchWizard selection, a different base disc) gives a new identity, which is rejected as "Unsupported disc contents".
- The identity is independent of the image container (CUE/BIN, CHD) and of track 1 padding, because it hashes extracted files.
- Sc1 also carries `track1_sha256` (`089c7747…f951`), used only by `verify_inventory` when a profile lacks `content_sha256`.

### Fields and how revision-specific they are

| Field | Meaning | Revision-specific? |
|---|---|---|
| `id`, `title`, `scenario`, `product`, `version` | Labels. `id` keys the build cache and `desktop-ready.json`. | New per profile. |
| `content_sha256` | See above. | Always new. |
| `scene_base` | Load address of X1 scene programs (Sc1 `0605F000`; Sc2/3 `0605E000`). X1BTL99 is hard-wired at `06060000` in `audit-modules.py`. | Per scenario. Translation patches are not expected to move it, but this must be verified. |
| `effect_base` | X3 effect programs (Sc2 `06049000`; Sc1/3 none, Sc3 uses a container). | Per scenario. |
| `module_containers` | Sc3 `EFFECT.BIN`: 69 × 0x8000 chunks loaded at `06048D00`, entries at offsets 0/12/24. | Per scenario. |
| `model_bases` | Per-file load addresses for non-X1 programs (Sc2/3). Sc1 uses `MODEL_BASES` hard-coded in `audit-modules.py`. | Per scenario. Mods that relocate data inside a file do not change load bases. |
| `modules[]` | name, file, base, `seeds` (absolute entry addresses), `overlay`, `evidence`, optional `bytes` (image length), `stack_return_calls` / `stack_return_evidence`. Sc1 has 25, Sc2 15, Sc3 21. | **This is where patches bite.** Seeds are absolute addresses inside a file's image. If a patch inserts or moves code (e.g. Mod Essentials' X014 "moves dynamic eof data by +0xe000"), seeds may point mid-function or at data. `bytes` limits may also be wrong. |
| `stack_return_calls` (BOOT only) | Call sites wrapped in PR-save/call/restore. Sc1: `06004040, 06004108, 06004204`. Sc2 v24 **and** Sc3 v25.1: `06005548, 06005610, 0600570C`, which suggests the translation's `1ST.BIN` code is shared. | `module_images.image_bytes` checks the wrapper bytes (`4f22 400b … 4f26`) at each site. A shifted BOOT fails fast rather than miscompiling. |
| `boot_check_vblanks` | Headless smoke-run length during Prepare (Sc2 1800, Sc3 3000, default 120). | Per scenario. |
| `support` | Free-text status. | Per profile. |

### Pipeline that derives a usable profile from a disc

1. `probe.py` takes the inventory and extracts files.
2. `audit-modules.py --profile <base profile>`:
   - verifies the inventory hash
   - discovers veneers (`d001402b00090009`), X1 bases from `scene_base`, X3 bases from `effect_base`, and `model_bases`
   - follows cross-module calls
   - optionally corroborates bases against crash RAM with `--session`
   - writes `module-audit/candidate-profile.json` and flags rows `needs-load-address-review` / `needs-executable-entry-review`
3. `generate.py` → `check-module-build.py` → CMake/Ninja → headless boot check for `boot_check_vblanks`.
4. `tools/validate-modules.py --manifest … --require-complete` runs this across several local revisions and fails on any unmapped candidate.

Because steps 2-4 are mostly *derivation*, a new translation revision generally needs only:
- a copied base profile with the new `content_sha256`, `id`, `title` and `version`
- seeds revalidated for any code file the patch changed
- `stack_return_calls` rechecked if `1ST.BIN` changed (the Sc3+PD "Music Resume Fix RC2" touches `1ST.BIN`)

### Code paths that hard-code the registered revisions

A new profile is not picked up automatically. These must be updated together:
- `tools/check-source-package.py`: profile allowlist
- `tools/disc_profile.py`: error message
- `desktop/launcher_posix.py`: `PROFILES` (a tuple of accepted profile ids per launcher slot) and the combobox labels
- `desktop/Launcher.cs`: `Profiles` (a `string[][]`, one array per slot) and the labels

Each launcher slot accepts a **set** of profile ids. `ready()` checks that `desktop-ready.json`'s `profile_id` is one of the slot's ids. The data folders (`DATA_FOLDERS`, `DataSuffixes`) are still one per slot and keep their old names, so existing game-data folders keep working. `tools/tests/test_posix.py` checks that every `profiles/*.json` id is in exactly one slot, in both launchers.

### What the V25+ patch set means

The V25+ folder holds the release plus optional per-file `.DFR` diffs, each with `metadata.json` (title, desc, category, enabled, priority). They are organized by product code:
- `MK-81383`: Sc1 USA
- `GS-9175`: Sc1 JP, bases V1.006/V2.005
- `GS-9188`: Sc2, bases V1.003/V2.000
- `GS-9203`: Sc3
- `6106979`: Premium Disc

Several touch code files: X002, X013, X014, X017, X1 scenes, and `1ST.BIN`. Some are base-version specific, e.g. "Remove Black Border" has separate Sc2 V1.003 and V2.000 X002/X009 diffs, and there is "Sc2 v2.000 Battle 20 Model Fixes". The applying tool is the Windows .NET PatchWizard (`SF3Translation_PatchWizard_*.zip`) or `SF3Patch.exe`. On Linux that means Wine/mono, or patching on Windows. Because mods are user-selectable, the number of possible disc identities is combinatorial. Proposed policy:

1. Register **one canonical profile per scenario/base**: the PatchWizard's default selection, with the exact patch list and versions recorded in the profile's `support`/evidence text. Sc2 gets two (V1.003-based and V2.000-based).
2. Later, consider a "base profile + allowed variants" mechanism: identify by the manifest *minus* files whose diffs are known not to touch code, or keep a per-mod table of file hashes and of code-affecting deltas such as seeds and `bytes`. Do not loosen identity for code files without a seed revalidation step.

## Latest-translation profiles (branch `latest-translation-profiles`)

Made from the Redump dumps with `tools/sf3patch` and the **default V25.1 selection** (no `--addons`). For every disc the default output was checked against the official V25.1 wizard run under Wine: identical apart from timestamps (see [translation-patcher.md](translation-patcher.md)).

| Launcher slot | Profile id | Base disc (Redump) | `content_sha256` | Seeds |
|---|---|---|---|---|
| Scenario 1 | `scenario1-usa-v1_001` (upstream, unpatched) | MK-81383 V1.001 | `54aa1d21…81a9` | upstream |
| Scenario 1 | `scenario1-usa-translation-v25_1` | MK-81383 V1.001 | `0dee501e…b1b5` | copied from `scenario1-usa-v1_001`. Every seed and BOOT stack-return site has the same bytes as on the unpatched disc. |
| Scenario 2 | `scenario2-translation-v25_1-v2_000` | GS-9188 V2.000 (Rev A) | `1b835e56…7dd9` | copied from v24. The v24 profile was made on the V2.000 base, and its `1ST.BIN` is the same as the original Rev A's. |
| Scenario 2 | `scenario2-translation-v25_1-v1_003` | GS-9188 V1.003 | `b967f067…5d27` | copied from v24, with 10 BOOT (`1ST.BIN`) seeds relocated for V1.003's BOOT. The new addresses were found by matching the function bytes. The stack-return sites are unchanged. |
| Scenario 2 | `scenario2-translation-v24` (upstream) | | | upstream |
| Scenario 3 | `scenario3-translation-v25_1-redump` | GS-9203 V1.001 | `3fe9ec34…987c` | copied from `scenario3-translation-v25_1`. The default V25.1 leaves `1ST.BIN` unchanged. |
| Scenario 3 | `scenario3-translation-v25_1` (upstream) | | `5a50848f…3252` | upstream. Kept, but neither sf3patch nor the official wizard reproduces it from the Redump dump. |

Results on Linux x86-64 (Debian 13, clang 19, `tools/windows.cmake` host, headless, software rendering), 2026-10-24. Each run: probe → audit → generate → emission check (`--player`) → build → `saturn --headless`, 4500 vblanks with a scripted Start/A route.

| Profile | Modules | Functions | Unresolved indirect sites | Review items | Boot |
|---|---|---|---|---|---|
| Sc1 USA unpatched (upstream, control) | 255 | 16572 | 935 | X004, X019, X3ELEM5 | title → Gabriel's opening scene |
| Sc1 USA V25.1 | 255 | 16572 | 935 | X004, X019, X3ELEM5 | title ("Translation V25.1") → opening scene, translated text |
| Sc2 V25.1 / V2.000 | 288 | 20953 | 1159 | X004, X019, X3ELEM5 | title → opening scene |
| Sc2 V25.1 / V1.003 | 288 | 20961 | 1154 | X004, X019, X3ELEM5 | title → opening scene |
| Sc3 V25.1 Redump | 274 | 25227 | 1299 | X004 | title → opening scene |

There were no crashes, hangs, or fatal or unresolved-call messages in the run logs. The audit's remaining "undefined" discovery findings in configured modules (X021/X022/X032, and X019 `060A0000` on Sc3) are the same as on the upstream baseline. This is a **boot check only**. Battles, saves, scene coverage and the routes in [testing-plan.md](testing-plan.md) are not validated yet.

**Why there are no `--addons` profiles.** Every patch selection gives a new `content_sha256`, so the set of possible identities is combinatorial. The V25+ add-ons also change code: Mod Essentials and the icon mods change `X014`/`X017`, and Music Resume Fix changes `1ST.BIN`. Each one would need its own seed revalidation and its own audit. The policy stays as above: one canonical profile per scenario and base, using the wizard's default selection. An add-on profile can be added later, using the same steps, for a selection the Translation Project recommends. The `--addons` images were made and pass EDC/ECC and extraction, but they are not registered.

**Premium Disc (6106979 V1.000).** Not done. The patched content id is `a5976aa8…0ac2`. It needs:
- a fourth launcher slot and data folder, in both launchers and in `prepare*.py --scenario`;
- a base profile from scratch: its load bases, `model_bases`, BOOT seeds and stack-return sites (there is no existing profile to copy);
- a full module audit with `--require-complete`;
- save-format handling, if it uses one.

## Prioritized roadmap

1. **Profiles for the latest-translation-patched Sc1, Sc2, Sc3, then the Premium Disc.** Sc1/Sc2/Sc3 default V25.1 profiles are in (boot-checked on Linux); the Premium Disc and gameplay routes remain.
   - Sc1 USA (MK-81383) plus SF3TRANS latest, alongside the existing unpatched V1.001.
   - Sc2 latest on **both** bases (V1.003 and V2.000), replacing v24 as the default.
   - Sc3 V25.1 plus post-release updates. Recheck BOOT `stack_return_calls` because of the 1ST.BIN music-resume fix.
   - Premium Disc (6106979) last; it has no profile at all yet.
   - Each needs: the audit with `--require-complete`, seeds reviewed for changed code files, a headless boot check, the scene sweep and differential layers from [testing-plan.md](testing-plan.md), and the launcher/allowlist changes listed above.
2. **Scenario 1 real-disc playability on Linux** (the best-covered scenario upstream): run the existing local transition routes and native-state validators on Linux and compare frame/video hashes with Windows results where available.
3. **Linux usability blockers**:
   - an SDL-window (or launcher-embedded) controller-setup UI, POSIX skip/cancel, and platform-neutral messages
   - verify Wayland, PipeWire, a hardware Vulkan GPU, and physical pads
4. **Sc2/Sc3 with the patches**: move from "boot only" to the scene sweep, then full-route coverage (X025/X048/X049, X3 effects, X3ELEM5 review).
5. **Premium Disc** profile and module audit.
6. Packaging: a release artifact for the fork, a `.desktop` entry, an AppImage or Flatpak, and a Steam Deck check.
7. Developer ergonomics: POSIX equivalents of the PowerShell helpers.

## When the ISOs arrive

Do all of this privately; never commit or upload disc-derived files (inventories, extracted files, `generated/`, builds, saves, captures).

1. **Keep the originals read-only.** Record `sha256sum` of every `.bin`/`.cue`/`.iso` and compare against Redump. Sc1 USA V1.001 track 1 must be `089c77470dec14f1dbffaad1ab50d584f06df5e28b475fc712b8e67e5890f951`.
2. **Identify each image** against the registered profiles:
   ```sh
   PYTHONPATH=.local/saturn-recomp/src:tools python3 -c "import sys; from saturnrecomp.disc import Disc, manifest; \
   from disc_profile import content_id; d=Disc(sys.argv[1]); print(d.ip.product, d.ip.version, content_id(manifest(d)))" disc.cue
   ```
   - Unpatched Sc1 should match `54aa1d21…`.
   - A **patched** image will not match any profile; that is expected.
3. **Patch** copies with the latest Translation Project release (PatchWizard via Wine, or on Windows). Record the patch list, versions and base (Sc2: V1.003 or V2.000), then compute the content id again.
4. **Derive a candidate profile:** copy the nearest existing profile, set the new id/title/version/`content_sha256`, and run `probe.py` → `audit-modules.py --profile <copy>`. Review every `needs-*-review` row and every changed seed or stack-return check.
5. **Recompile and boot:** `prepare_posix.py --cue … --work … --scenario N`. This runs audit, generate, module build check, compile and the headless boot check. Then `run_posix.py --work … --headless-fields N` for a longer smoke run.
6. **Test routes:**
   - title → new game → first battle
   - save/load in game
   - F5/F9 native states
   - `import-saturn-save.py` of an existing BIN/YSBAK save
   - `validate-native-states.py` and `validate-game-speed.py` with external route manifests
   - `--coverage` for the executed-function burndown
   - audio sanity (WAV capture, then listen)
   - controller setup from a terminal
7. Add profiles in small commits: profile JSON plus the allowlist/launcher changes, with no disc bytes. Record results as "validated on Linux with <patch list>".

To make translated images on Linux without the Windows PatchWizard, see [translation-patcher.md](translation-patcher.md).
