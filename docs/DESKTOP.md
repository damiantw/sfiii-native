# Automatic Windows preparation

## v0.3.0-alpha changes

- Select Scenario 1 USA V1.001 or the registered Scenario 2 Translation Project v24 edition, each with its own disc path and game-data folder.
- Use BIN/CUE or standalone CHD input. Bundled chdman converts CHDs locally; users install no extra tools.
- Import supported Scenario 1/2 raw BIN saves or version-1 JSON YSBAK exports into internal or cartridge storage.
- Save/load direct native machine snapshots with F5/F9 or the toolbar. Separate legacy replay actions remain available.
- Choose 1×, 2×, 4× or 5× supported geometry rendering through Vulkan or Direct3D 12. Original texture detail remains unchanged.
- Launcher preferences persist beside the application when writable, with a fallback to the existing per-user settings location.

Scenario 2 remains experimental. The recorded route suite reaches startup, the opening sequence, docks, and imported-save church/town transitions; it does not certify battles, later chapters, campaign transfers or complete-game compatibility. Static mapping/discovery findings remain separate from executed coverage. Widescreen can still expose missing terrain or objects at the edges because the game retains original view-culling assumptions.

Each selector remembers its own disc and data folder. Keep separate folders for the two scenarios; setup rejects switching revisions inside an existing installation. Internal/cartridge progress, native states and replay checkpoints stay with that installation. Close the game before importing saves or updating.

CHDs are verified and extracted locally with bundled `chdman` during preparation, then the native game reads the extracted CUE/BIN. This is a disc-container conversion, not an interpreter gameplay path. The original CHD remains unchanged. Allow additional space for the decompressed disc and keep `disc-cache` in the selected data folder. Its receipt records the source and extracted-file hashes; a changed cache is rejected. Parent/delta CHDs and ISO input are not supported. Disc identity checks include the IP area, every filesystem file and audio tracks, rather than trusting a filename or translation label.

CHD input details are recorded in `disc-input.log`; compilation details remain under `preparation`. Extraction, preparation and save files never enter the source repository. The bundled MAME 0.289 tool requires an x86-64-v2 CPU. Its notices and corresponding source archive accompany the package.

Download the **Windows ZIP asset** from the v0.3.0-alpha prerelease, rather than GitHub's automatically generated source archive. Extract the entire ZIP and open **SFIII Native.exe**. The included compiler, embedded Python, build tools and runtime source are application components; players do not install them separately or enter commands.

## First run

1. Select the scenario and click **Browse** for your supported CUE or CHD image. Keep all referenced BIN tracks beside a CUE.
2. Keep the default game-data location or choose a writable folder outside the application and every source repository. Allow several GB of free space.
3. Click **Prepare game**. Disc checks, extraction, native code generation and compilation happen locally and offline. Progress appears in the window; preparation can take several minutes.
4. When ready, click **Play**. Controller setup and save import are available from the same window.

Windows 10 (1903 or newer)/11 x64 with .NET Framework 4.8 and a suitable Vulkan/Direct3D 12 driver is the target. The application is unsigned, so Windows may identify it as an unknown publisher. No BIOS file is required. Only the registered Scenario 1 USA V1.001 and Scenario 2 translated-v24 revisions are accepted. Scenario 3, Premium Disc, other patches, parent/delta CHDs and ISO input are unsupported.

Keep both the application and game-data folders. The original disc dump remains necessary while playing. Saves live in the separate game-data folder, not inside the downloadable package. Reopening the app remembers the selected paths. Changing a disc's location requires preparing its new path again. Updates retain the old build and saves. Native states and replay checkpoints are tied to their exact executable/disc identity: create a new quick state after an update. Older slots stay intact for their original build. Loading a native state restores its captured internal/cartridge memory; exact pre-load backups remain in that session folder.

## Failure and cancellation

Cancel stops the preparation process and its compiler children. An unfinished build is not selected for play. Existing internal/cartridge backups and checkpoints are not replaced by validation saves. Retry preparation after correcting a missing track, unsupported revision or insufficient space. A lock prevents simultaneous preparations in the same data folder, and setup refuses a folder with a running game.

Local details are under `preparation/BUILD_ID/setup.log` in the game-data folder. These logs and any generated files stay local. Do not upload game data, generated code, saves or memory/video dumps to issues. No automatic upload occurs.

## Building the downloadable package

This is a maintainer step, not a player requirement. After normal dependency setup, use Python 3.11+ and the Windows .NET Framework C# compiler:

```powershell
python tools/package-desktop.py --out 'D:\SFIII-packages\SFIII-Native-0.2.0-alpha-win64' --cache 'D:\SFIII-packages\downloads' --zip
```

The packager verifies archive hashes from `desktop/dependencies.json`, copies reusable source and required licenses, compiles the launcher and project-owned GPU shaders, and creates an external file inventory and ZIP checksum. It never reads a disc or takes generated game code as input. LLVM-MinGW supplies its own headers, libraries and static C++ runtime; the end-user build does not use Visual Studio or the Windows SDK. Python is the official isolated embedded distribution. Microsoft C++ headers/libraries are not bundled.

The default developer workflow still supports Visual Studio/Clang. The portable MinGW workflow is separately validated because a compiler/ABI change is not automatically gameplay-equivalent. Before releasing a package, run all six runtime regression targets and the available transition suite with its locally compiled executable, inspect reference frames, and test controller/GPU/checkpoint behavior. A build in a sanitized environment is useful evidence; it is not a substitute for independent tests across Windows PCs and GPU drivers.
