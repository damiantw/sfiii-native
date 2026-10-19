# Playing

Launch with **Launch Native SFIII.cmd** from your external work directory. Use **Controller Setup.cmd** to bind a generic or Saturn USB pad; **Controller Test.cmd** checks its controls. SDL mappings cover PS5, Xbox and other controllers. The Saturn USB pad has been physically tested locally; PS5/Xbox support has not received equivalent physical-device validation.

Keyboard defaults: arrows for movement, Enter for Start, Z/X/C for A/B/C, A/S/D for X/Y/Z, Q/W for L/R. Escape opens the menu. F11 or Alt+Enter toggles fullscreen.

## Display

Use **1× / 2× / 4×** for supported geometry resolution. Source texture detail remains original. Vulkan is preferred; Direct3D 12 is another supported backend. `SF3_GPU_BACKEND=vulkan` or `direct3d12` can force one for troubleshooting. Unsupported GPU/video paths retain a native fallback, with different performance and enhancement coverage.

**Menu > Aspect ratio (beta) > 16:9** adds horizontal scenery; choose **4:3** for original framing. HUD/dialogue remain centered. The rotation-floor viewport window expands horizontally, retaining its vertical limits. Game-side object culling still uses original assumptions, so missing objects or pop-in at new edges can remain. Higher resolution and widescreen are experimental presentation features, not a claim of exact hardware output.

## Game saves

Use the game's save command for ordinary persistent progress. The external files are `experimental-backup.bin` (32 KiB internal capacity) and `experimental-backup.bin.cartridge` (512 KiB cartridge capacity). They contain native backup records, **not raw emulator memory images**. Back them up before changing versions or importing saves. The full game's save behavior has not been validated.

**Import Saturn Saves.cmd** accepts the supported per-save raw Scenario 1 `SFORCE31_XX.BIN` export format, with a choice of internal or cartridge storage. Imports preserve payloads and back up the destination. Real Saturn exports have been tested locally. Emulator and Saroo exports are usable only when they match that supported format; arbitrary `.bin` files, whole memory dumps, compressed exports and emulator save states are not automatically interchangeable. Stop the game before importing. Python 3.11+ must remain installed.

## Replay checkpoints

Toolbar/menu Save checkpoint and Load checkpoint, or F5 and F9, record a route and restart/fast-forward it. **Load Replay Checkpoint.cmd** loads the latest compatible checkpoint. Keep the complete checkpoint, including initial internal/cartridge backups, clock, settings and input. They are tied to the exact disc and native executable and are not instant save states. New executable versions can invalidate them.

Replay sessions keep their own saves so loading an old checkpoint does not roll back ordinary progress. `publish-replay-save.ps1` is an explicit, separate action for adopting progress from a replay session; never copy historical validation backups over live progress automatically.

## Local session files

Sessions, input recordings and checkpoints stay in your work directory. Optional **Capture issue** (F8) also writes screenshots, memory/video dumps and context there. These are local troubleshooting features; no automatic upload occurs. Do not attach memory/video dumps, extracted assets, generated game code or saves to a repository issue. Describe a problem with the disc revision, scene, settings and reproduction steps instead. The normal launcher does not enable instruction/transition tracing; developers can opt in with `run-native.ps1 -Work WORK -Diagnostics`.
