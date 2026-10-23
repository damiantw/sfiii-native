# Shining Force III Native

An experimental native static recompilation project for **Shining Force III**, with profiles for **Scenario 1 USA MK-81383 V1.001**, **Scenario 2 Translation Project v24** and **Scenario 3 Translation Project v25.1**. Game SH-2 code is generated locally as C++ and compiled for the PC. Windows is the established development platform; experimental Linux x64, Apple Silicon and Intel Mac candidates are built separately. The runtime supplies Saturn graphics, sound, storage and other hardware services; static recompilation does not remove the need to model those systems.

**Work in progress.** Scenario 1 USA, Scenario 2 Translation Project v24 and Scenario 3 Translation Project v25.1 are supported experimental profiles. Recorded Windows gameplay routes pass; the complete games, Premium Disc and unregistered revisions remain unvalidated or unsupported.

**v0.5.0-alpha:** [download the latest Windows, Linux and macOS packages](https://github.com/mattkuhnQAAI/sfiii-native/releases/tag/v0.5.0-alpha). This update adds Scenario 3, optional 2×/3× game speed and Light AA, expands native effect/scene compilation, and strengthens save-state and regression checks. Windows gameplay validation covers 28 recorded routes across the three scenarios. Linux/macOS packages have synthetic validation; real-disc gameplay on those platforms remains unvalidated. See [desktop setup](docs/DESKTOP.md) and [portable setup](docs/POSIX.md).

When updating, extract into a new application folder and choose your existing scenario data folder, then run **Prepare game** again. The bundled tools handle preparation automatically. Existing in-game saves remain in the separate data folder. Native quick states are build-specific: keep your previous application and prepared build if you need its old states; use an ordinary in-game save to transfer progress to the new build.

## Features

- Keyboard and SDL controllers, including PlayStation, Xbox, generic USB and configurable Saturn USB controllers.
- Original textures with 1×, 2×, 4× and 5× rendering of supported geometry through Vulkan, Direct3D 12 or Metal (macOS preview).
- Experimental 16:9 rendering with centered original framing and additional scenery. Game-side object culling is still incomplete, so edge gaps and pop-in can remain.
- Persistent internal and cartridge backup storage, with import of supported Scenario 1/2/3 raw BIN and version-1 JSON YSBAK saves.
- Direct native save states (F5/F9), with separate legacy replay checkpoints. Snapshot validation covers limited Scenario 2 translated-v24 routes; broader snapshot compatibility remains unvalidated.
- A portable Windows first-run application that prepares your own disc automatically, with controller setup and save import buttons.
- Experimental Linux/macOS launchers with bundled offline preparation tools, controller setup and save imports.
- Separate 1×/2×/3× game-speed controls (F6 or menu), with accelerated audio. Rendering resolution stays fixed; available speed depends on scene and hardware.
- Optional Light edge anti-aliasing for identified GPU geometry, with ordinary sprite/text paths protected and an exact unfiltered Off mode. Broader scene coverage remains unvalidated.

## Screenshots

Native Windows captures with the original game artwork. Click an image to open its full resolution. These images illustrate development progress; they do not establish Linux/macOS gameplay compatibility.

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

## What you supply

- **Windows:** Windows 10 (1903 or newer)/11 x64 with .NET Framework 4.8 (normally included), a Vulkan or Direct3D 12 capable GPU, and several GB of free disk space.
- **Linux/macOS preview:** Ubuntu 22.04 or newer x86-64 desktop, or macOS 13 or newer on Apple Silicon/Intel; see [platform requirements](docs/POSIX.md).
- Your own supported **BIN/CUE or standalone CHD** disc: unpatched Scenario 1 USA V1.001, or the registered Scenario 2 Translation Project v24 edition. Disc contents are verified; a filename or patch label alone is insufficient. The Scenario 1 data-track SHA-256 is:

  `089c77470dec14f1dbffaad1ab50d584f06df5e28b475fc712b8e67e5890f951`

The current runtime provides BIOS services at a high level and **does not load or require a Saturn BIOS file**. No BIOS, game assets, disc images, saves, extracted files or generated game code are distributed here. Do not upload those files, including in issues or pull requests. Other revisions, translation patch versions, parent/delta CHDs and ISO input are not accepted. CHDs are converted locally with bundled chdman; gameplay uses compiled native code.

## Get started

**Windows players:** download **SFIII-Native-0.5.0-alpha-win64.zip** from this repository's **Releases** page, extract the **whole ZIP**, and open **SFIII Native.exe**. Choose the scenario, your CUE or CHD image and a separate game-data folder, click **Prepare game**, then **Play**. Preparation runs offline using bundled tools; there is no compiler installation, manual compilation, Python installation or terminal command to perform. Keep the application folder after preparation. See [desktop setup](docs/DESKTOP.md).

**Linux/macOS:** download your platform archive from [v0.5.0-alpha](https://github.com/mattkuhnQAAI/sfiii-native/releases/tag/v0.5.0-alpha), extract the complete archive, and open **SFIII Native** (**SFIII Native.app** on Mac). See [portable platform setup](docs/POSIX.md) for preparation and validation limits. Hosted native builds do not certify real-disc gameplay.

The application compiles game code locally during preparation. No generated game executable is distributed. The complete game is still unvalidated; this is an experimental alpha.

**Developers building from source:** clone this repository, install the [build prerequisites](docs/BUILDING.md), then run from PowerShell in its directory:

```powershell
.\tools\setup-dependencies.ps1
.\tools\prepare-game.ps1 -Cue 'D:\Games\SFIII\Shining Force III (USA).cue' -Work 'D:\SFIII-local' -Python python
```

The work folder must be outside the source repository. Preparation inventories your disc, generates and compiles code locally, and writes a launcher into that work folder. It does not upload your disc or saves. Compilation can take substantial time and disk space.

Source builds write **Launch Native SFIII.cmd** into the work folder. See [building](docs/BUILDING.md) for manual steps and [controls, saves and display settings](docs/USAGE.md) for use. Earlier v0.1.0-alpha downloads are source-only; use the current Windows ZIP for automatic preparation.

## Bring your own saves

The included **Import Saturn Saves.cmd** utility lets you bring your existing progress into the native application. The launcher accepts raw `SFORCE31_XX.BIN` / `SFORCE32_XX.BIN` saves and version-1 JSON `.ysbak` exports containing those saves. Scenario 2 requires the experimental translated-v24 profile. Arbitrary `.bin` files, whole backup-memory images and emulator save states are not automatically compatible.

Close the game, click **Import saves** in the desktop application (or open **Import Saturn Saves.cmd** in your work folder), select your exported saves, and choose **internal memory** or **cartridge memory**. Then launch the game and use its own load menu. The importer validates the save layout and checksum, leaves your original export untouched, and backs up an existing destination before writing. The desktop package includes Python; source builds require Python 3.11+. See [save formats and storage details](docs/USAGE.md#game-saves).

## Status and validation

The Scenario 1 development audit compiles 252 configured/candidate modules, including 169 X1 scene modules. Its nine-route regression suite exercises 12 X1 scenes; it does not validate all 169 scenes. Three mapping/entry reviews, nine discovery findings and 935 unresolved indirect sites remain review items. X046 now has revision-specific loader evidence for compilation; its gameplay path remains untested. Compilation, emitted entry coverage, executed gameplay and hardware fidelity are separate claims.

The Scenario 2 development audit compiles 285 configured/candidate modules, including 195 X1 scene programs and 59 X3 effects. Eleven local routes exercise 14 X1 scenes, including imported-save church/town and battle transitions, Healing Drop use through X3ITEM, the magic menu's no-target path, and an Egress return to the church. There are three mapping/entry reviews, 25 discovery findings and 1159 unresolved indirect sites; the larger indirect-site count includes newly compiled effect code. Repeated native snapshots before and during the item animation matched video, audio and backup contents. Repeated native snapshots during the Egress transition also matched video, audio and backup contents. Other effects, unvisited gameplay and other snapshot times remain unvalidated.

The spell/special dispatch tables have also been reviewed: all 81 Scenario 1, 93 Scenario 2 and 111 Scenario 3 entries resolve to mapped modules or container sections. This is static dispatch coverage, not validation of every spell animation. Additional direct loader/call evidence maps X049 in all three scenarios and X025/X048 in Scenarios 2/3. Seven mapping/entry reviews remain across the revisions: X004 in each scenario, and X019/X3ELEM5 in Scenarios 1/2. X019 in Scenarios 1/2 is modeled as monster-table data; its executable classification remains under review. X3ELEM5 does not appear in the reviewed effect dispatch tables and is not assigned a speculative load address.

The v0.3.0 candidate passed the six required runtime regression targets, the four Scenario 2 routes and 64 GPU shader cases, including 5×, plus native-state and toolbar checks. Synthetic tests cover arithmetic/DSP, storage, DMA, background composition, controller input, checkpoint integrity and GPU rendering. Captured gameplay diagnostics and historical route fixtures stay local. See [development and publication rules](docs/DEVELOPMENT.md).

Scenario 3 v25.1 development compiles 273 configured/candidate modules, including 169 X1 scene programs and 69 separately loaded sections of EFFECT.BIN. Eight Windows routes reach the title, fresh-game setup, ship dialogue, a first-battle screen and a priest interior, exercising five X1 scenes. One module mapping/entry, 17 discovery findings and 1299 indirect sites remain review items; individual container effects have not received gameplay validation. The runtime also reports unimplemented VDP2 scroll/extended-color paths in this route; rendering is not certified hardware-faithful. Downloaded completed saves are isolated test fixtures, never installed as player progress. Broader battles, ordinary in-game saving/loading, full campaign transfers and Linux/macOS Scenario 3 gameplay remain unvalidated.

## Upcoming features

Planned directions, with no release dates or compatibility guarantees. Faithful gameplay, graphics, audio and reliable saves take priority over enhancements.

- **Broader gameplay validation:** exercise more towns, battles, menus and transitions, fixing crashes and rendering/audio defects as coverage grows.
- **More complete widescreen:** improve game-side object and terrain culling so additional scenery remains visible as the camera moves and rotates.
- **More supported editions:** register additional disc revisions while keeping each installation’s progress separate.
- **Scenario 2/3 coverage, Premium Disc and more translations:** expand gameplay validation and add revision-specific compilation profiles, identifying supported patch versions explicitly.
- **Save portability and campaign transfers:** expand verified emulator/Saroo import and export formats, and validate backed-up progress transfers between compatible scenarios and editions.
- **Optional faithful high-resolution artwork:** revisit sharper replacement assets after gameplay and rendering correctness are further established, while retaining the original-art option.
- **Broader native save-state validation:** extend snapshot tests across battles, transitions and additional scenarios, beyond the limited Scenario 2/3 routes tested so far.

These are roadmap items; the supported profiles and tested coverage are listed above.

## Support development

If you'd like to support development and testing, you can [leave a tip via PayPal](https://paypal.me/mattkuhn14). Contributions are optional; the project remains free, and no game data is provided.

## Credits and licensing

Built on [saturn-recomp](https://github.com/callumjenkins/saturn-recomp), derived from [saturnkit](https://github.com/vs-sr-dev/saturnkit). SFIII module mappings were informed by [SF3Tools](https://github.com/Synival/sf3tools). Controller mappings use [SDL_GameControllerDB](https://github.com/mdqinc/SDL_GameControllerDB). Rendering and input use [SDL3](https://github.com/libsdl-org/SDL).

Project source is provided under the [MIT license](LICENSE); third-party code retains its own notices. See [THIRD_PARTY.md](THIRD_PARTY.md). Shining Force III and Sega Saturn belong to their respective rights holders. This is an unofficial project and includes no permission to redistribute game content.
