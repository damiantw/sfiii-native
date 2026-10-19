# Automatic Windows preparation

Download the **Windows ZIP asset** from the v0.2.0-alpha prerelease, rather than GitHub's automatically generated source archive. Extract the entire ZIP and open **SFIII Native.exe**. The included compiler, embedded Python, build tools and runtime source are application components; players do not install them separately or enter commands.

## First run

1. Click **Browse** and select your own unpatched Scenario 1 USA MK-81383 V1.001 CUE. Keep all referenced BIN tracks beside it.
2. Keep the default game-data location or choose a writable folder outside the application and every source repository. Allow several GB of free space.
3. Click **Prepare game**. Disc checks, extraction, native code generation and compilation happen locally and offline. Progress appears in the window; preparation can take several minutes.
4. When ready, click **Play**. Controller setup and save import are available from the same window.

Windows 10 (1903 or newer)/11 x64 with .NET Framework 4.8 and a suitable Vulkan/Direct3D 12 driver is the target. The application is unsigned, so Windows may identify it as an unknown publisher. No BIOS file is required. Other scenarios, patched revisions and CHD/ISO inputs are not supported by this first desktop package.

Keep both the application and game-data folders. The original disc dump remains necessary while playing. Saves live in the separate game-data folder, not inside the downloadable package. Reopening the app remembers the selected paths. Changing a disc's location requires preparing its new path again. Updates retain the old build and saves; replay checkpoints remain tied to their exact executable and may need recreating after an update.

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
