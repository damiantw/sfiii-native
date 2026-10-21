# Shining Force III Native

An experimental Windows native static recompilation project for **Shining Force III, Scenario 1 (USA, MK-81383 V1.001)**. Game SH-2 code is generated locally as C++ and compiled for the PC. The runtime supplies Saturn graphics, sound, storage and other hardware services; static recompilation does not remove the need to model those systems.

**Work in progress.** Recorded gameplay routes, real Saturn save imports and rendering checks work, but the complete game has not been validated. Scenarios 2–3, the Premium Disc and translated editions are planned, **not supported** by this build profile.

**Development branch:** the launcher is being extended with CHD ingestion, a game selector and a separate experimental Scenario 2 Translation Project v24 profile. See [development launcher details](docs/DESKTOP.md#development-launcher-chd-and-scenario-2). These changes are not present in the published v0.2.0 Windows ZIP; Scenario 2 gameplay validation is ongoing.

## Features

- Keyboard and SDL controllers, including PlayStation, Xbox, generic USB and configurable Saturn USB controllers.
- Original textures with 1×, 2× and 4× rendering of supported geometry through Vulkan or Direct3D 12.
- Experimental 16:9 rendering with centered original framing and additional scenery. Game-side object culling is still incomplete, so edge gaps and pop-in can remain.
- Persistent internal and cartridge backup storage, with import of supported raw Scenario 1 `SFORCE31_XX.BIN` saves.
- Replay checkpoints, plus experimental direct native save states in development builds. Native states are currently validated on limited Scenario 2 translated-v24 routes; the public v0.2.0 package uses input replays.
- A portable Windows first-run application that prepares your own disc automatically, with controller setup and save import buttons.

## What you supply

- Windows 10 (1903 or newer)/11 x64 with .NET Framework 4.8 (normally included), a Vulkan or Direct3D 12 capable GPU, and several GB of free disk space.
- Your own unpatched USA V1.001 **BIN/CUE** disc dump. The supported data-track SHA-256 is:

  `089c77470dec14f1dbffaad1ab50d584f06df5e28b475fc712b8e67e5890f951`

The current runtime provides BIOS services at a high level and **does not load or require a Saturn BIOS file**. No BIOS, game assets, disc images, saves, extracted files or generated game code are distributed here. Do not upload those files, including in issues or pull requests. Other dump formats and patched revisions are not accepted by the current generation profile.

## Get started

**Players:** download **SFIII-Native-0.2.0-alpha-win64.zip** from this repository's **Releases** page, extract the **whole ZIP**, and open **SFIII Native.exe**. Choose your CUE file and a separate game-data folder, click **Prepare game**, then **Play**. Preparation runs offline using bundled tools; there is no compiler installation, manual compilation, Python installation or terminal command to perform. Keep the application folder after preparation. See [desktop setup](docs/DESKTOP.md).

The application compiles game code locally during preparation. No generated game executable is distributed. The complete game is still unvalidated; this is an experimental alpha.

**Developers building from source:** clone this repository, install the [build prerequisites](docs/BUILDING.md), then run from PowerShell in its directory:

```powershell
.\tools\setup-dependencies.ps1
.\tools\prepare-game.ps1 -Cue 'D:\Games\SFIII\Shining Force III (USA).cue' -Work 'D:\SFIII-local' -Python python
```

The work folder must be outside the source repository. Preparation inventories your disc, generates and compiles code locally, and writes a launcher into that work folder. It does not upload your disc or saves. Compilation can take substantial time and disk space.

Source builds write **Launch Native SFIII.cmd** into the work folder. See [building](docs/BUILDING.md) for manual steps and [controls, saves and display settings](docs/USAGE.md) for use. Earlier v0.1.0-alpha downloads are source-only; use the v0.2.0-alpha Windows ZIP for automatic preparation.

## Bring your own saves

The included **Import Saturn Saves.cmd** utility lets you bring your existing progress into the native application. The development launcher accepts raw `SFORCE31_XX.BIN` / `SFORCE32_XX.BIN` saves and version-1 JSON `.ysbak` exports containing those saves. The public v0.2.0 package supports raw Scenario 1 exports only. Scenario 2 requires the experimental translated-v24 profile. Arbitrary `.bin` files, whole backup-memory images and emulator save states are not automatically compatible.

Close the game, click **Import saves** in the desktop application (or open **Import Saturn Saves.cmd** in your work folder), select your exported saves, and choose **internal memory** or **cartridge memory**. Then launch the game and use its own load menu. The importer validates the save layout and checksum, leaves your original export untouched, and backs up an existing destination before writing. The desktop package includes Python; source builds require Python 3.11+. See [save formats and storage details](docs/USAGE.md#game-saves).

## Status and validation

The Scenario 1 v0.2.0 baseline audit compiles 250 configured/candidate modules, including 169 X1 scene modules. Its nine-route regression suite exercises 12 X1 scenes; it does not validate all 169 scenes. Five mapping/entry reviews, nine discovery findings and 918 unresolved indirect sites remain review items. Compilation, emitted entry coverage, executed gameplay and hardware fidelity are separate claims.

Synthetic tests cover arithmetic/DSP, storage, DMA, background composition, controller input, checkpoint integrity and GPU rendering. Captured gameplay diagnostics and historical route fixtures stay local. See [development and publication rules](docs/DEVELOPMENT.md).

## Upcoming features

Planned directions, with no release dates or compatibility guarantees. Faithful gameplay, graphics, audio and reliable saves take priority over enhancements.

- **Broader gameplay validation:** exercise more towns, battles, menus and transitions, fixing crashes and rendering/audio defects as coverage grows.
- **More complete widescreen:** improve game-side object and terrain culling so additional scenery remains visible as the camera moves and rotates.
- **Game and edition selector:** organize locally supplied discs and supported editions in one launcher, with separate progress and settings where appropriate.
- **Scenarios 2–3, Premium Disc and translations:** add revision-specific compilation profiles and validation, including explicit identification of supported translation patch versions.
- **Save portability and campaign transfers:** expand verified emulator/Saroo import and export formats, and validate backed-up progress transfers between compatible scenarios and editions.
- **Optional faithful high-resolution artwork:** revisit sharper replacement assets after gameplay and rendering correctness are further established, while retaining the original-art option.
- **Broader native save-state validation:** extend snapshot tests across battles, transitions and additional scenarios, beyond the currently tested Scenario 2 routes.

These are roadmap items, not features already supported by the current Scenario 1 build.

## Support development

If you'd like to support development and testing, you can [leave a tip via PayPal](https://paypal.me/mattkuhn14). Contributions are optional; the project remains free, and no game data is provided.

## Credits and licensing

Built on [saturn-recomp](https://github.com/callumjenkins/saturn-recomp), derived from [saturnkit](https://github.com/vs-sr-dev/saturnkit). SFIII module mappings were informed by [SF3Tools](https://github.com/Synival/sf3tools). Controller mappings use [SDL_GameControllerDB](https://github.com/mdqinc/SDL_GameControllerDB). Rendering and input use [SDL3](https://github.com/libsdl-org/SDL).

Project source is provided under the [MIT license](LICENSE); third-party code retains its own notices. See [THIRD_PARTY.md](THIRD_PARTY.md). Shining Force III and Sega Saturn belong to their respective rights holders. This is an unofficial project and includes no permission to redistribute game content.
