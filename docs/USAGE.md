# Playing

In the desktop package, click **Play** after preparation. Source builds can launch with **Launch Native SFIII.cmd** from the external work directory. Use **Controller Setup.cmd** to bind a generic or Saturn USB pad; **Controller Test.cmd** checks its controls. SDL mappings cover PS5, Xbox and other controllers. The Saturn USB pad has been physically tested locally; PS5/Xbox support has not received equivalent physical-device validation.

Keyboard defaults: arrows for movement, Enter for Start, Z/X/C for A/B/C, A/S/D for X/Y/Z, Q/W for L/R. Escape opens the menu. F11 or Alt+Enter toggles fullscreen.

## Display

Use **1× / 2× / 4× / 5×** for supported geometry resolution. 5× renders 56% more pixels than 4×, so it needs more GPU headroom. Source texture detail remains original. Vulkan is preferred; Direct3D 12 is another supported backend. `SF3_GPU_BACKEND=vulkan` or `direct3d12` can force one for troubleshooting. Unsupported GPU/video paths retain a native fallback, with different performance and enhancement coverage.

Gameplay and audio keep the original roughly 59.8 Hz NTSC clock. Presentation targets that rate; higher monitor refresh does not speed up the game, and individual animations can update less often. Internal resolution stays at your chosen value: there is no automatic quality reduction. GPU tile binning and parallel composition of supported background rows reduce rendering overhead on suitable hardware, but performance in untested scenes is not guaranteed.

**Menu > Aspect ratio (beta) > 16:9** adds horizontal scenery; choose **4:3** for original framing. HUD/dialogue remain centered. The rotation-floor viewport window expands horizontally, retaining its vertical limits. Game-side object culling still uses original assumptions, so missing objects or pop-in at new edges can remain. Higher resolution and widescreen are experimental presentation features, not a claim of exact hardware output.

## Game saves

Use the game's save command for ordinary persistent progress. The external files are `experimental-backup.bin` (32 KiB internal capacity) and `experimental-backup.bin.cartridge` (512 KiB cartridge capacity). They contain native backup records, **not raw emulator memory images**. Back them up before changing versions or importing saves. The full game's save behavior has not been validated.

**Import Saturn Saves.cmd** accepts per-save raw `SFORCE31_XX.BIN` (12904 bytes), `SFORCE32_XX.BIN` (16248 bytes), and version-1 JSON `.ysbak` exports with matching filename, size and checksum. Scenario 2 gameplay requires the experimental translated-v24 profile; accepting a save format does not validate every scene it can load.

Choose internal or cartridge storage. A Scenario 2 save occupies 33 cartridge blocks; internal storage fits one Scenario 2 save. Imports preserve payloads and back up the destination. YSBAK filename, ASCII comment, language and save date are retained; embedded screenshots and remote URLs are ignored. Raw BIN imports generate comment/date metadata. Emulator and Saroo exports must match a supported format; whole memory dumps and emulator save states are not interchangeable. Stop the game before importing. The desktop package supplies Python; source builds need Python 3.11+ installed.

## Native save states and replay checkpoints

v0.3.0 builds with native state continuations provide **Save state / Load state** in the toolbar and menu, or **F5 / F9**. They capture and restore the machine directly, including both CPUs, RAM, video, sound, CD state and internal/cartridge backup contents. Loading briefly restarts the native process; it does not replay earlier inputs. **Load Native State.cmd** loads the latest compatible state without first playing through the title screen.

There is one quick slot per exact executable/disc identity under `native-states` in the game-data folder. Wait for the window title to confirm the write. Corrupt and incompatible states are rejected. Updating the executable requires a new state; older slots remain intact. Native states are currently validated on limited Scenario 2 translated-v24 routes, not the complete game.

**Loading a native state restores its backup memory too.** Exact pre-load internal/cartridge files and the loaded state are retained in that session directory. Ordinary game saves and older replay checkpoints remain available. Replay checkpoint creation/loading within a session restored from a native state is disabled; use native states there.

The public v0.2.0 build and older native builds retain the replay controls described below. v0.3.0 keeps them as separate menu actions; F5/F9 now select native states.

Toolbar/menu Save checkpoint and Load checkpoint, or F5 and F9, record a route and restart/fast-forward it. **Load Replay Checkpoint.cmd** loads the latest compatible checkpoint. Keep the complete checkpoint, including initial internal/cartridge backups, clock, settings and input. They are tied to the exact disc and native executable and are not instant save states. New executable versions can invalidate them.

Replay sessions keep their own saves so loading an old checkpoint does not roll back ordinary progress. `publish-replay-save.ps1` is an explicit, separate action for adopting progress from a replay session; never copy historical validation backups over live progress automatically.

## Local session files

Sessions, input recordings and checkpoints stay in your work directory. Optional **Capture issue** (F8) also writes screenshots, memory/video dumps and context there. These are local troubleshooting features; no automatic upload occurs. Do not attach memory/video dumps, extracted assets, generated game code or saves to a repository issue. Describe a problem with the disc revision, scene, settings and reproduction steps instead. The normal launcher does not enable instruction/transition tracing; developers can opt in with `run-native.ps1 -Work WORK -Diagnostics`.
