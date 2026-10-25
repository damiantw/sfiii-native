# Playing

In the desktop package, click **Play** after preparation. Source builds can launch with **Launch Native SFIII.cmd** from the external work directory. Use **Controller Setup.cmd** to bind a generic or Saturn USB pad; **Controller Test.cmd** checks its controls. SDL mappings cover PS5, Xbox and other controllers. The Saturn USB pad has been physically tested locally; PS5/Xbox support has not received equivalent physical-device validation.

On Linux and macOS the launcher works the same way ([portable platform setup](POSIX.md)): choose the game, **Browse** to its CUE or CHD and a data folder, **Prepare game** (this generates and builds the game locally, about 8–11 minutes on two cores), then **Play**; **Play** stays disabled until preparation for that disc and package succeeded, and a prepared folder is playable straight away on the next start. Each scenario and disc revision needs its own data folder. Closing the game window returns the launcher to **Ready**.

Keyboard defaults: arrows for movement, Enter for Start, Z/X/C for A/B/C, A/S/D for X/Y/Z, Q/W for L/R. Escape opens the menu. F11 or Alt+Enter toggles fullscreen.

## Controls

| Saturn | Keyboard | Gamepad (SDL mapping) |
|---|---|---|
| D-pad | Arrow keys | as bound in **Controller Setup** (SDL mappings for PS5, Xbox and generic pads) |
| Start | Enter | as bound |
| A / B / C | Z / X / C | as bound |
| X / Y / Z | A / S / D | as bound |
| L / R | Q / W | as bound |

Host keys: Escape opens the menu, F11 or Alt+Enter toggles fullscreen, F6 cycles game speed, F5/F9 save/load the native state (or replay checkpoint on older builds), F8 captures an issue. Gamepads can be connected or removed while the game runs; a removed pad's buttons are released.

### Gamepads and rebinding

Gamepads go through SDL's gamepad layer: the bundled community `gamecontrollerdb.txt` maps Xbox, PlayStation, 8BitDo and most other pads to a positional Xbox-style layout, and **Controller Setup** writes `controller-mappings.txt` for a pad that is missing or wrong (it is loaded after the bundled database, so it wins). Without any settings, every gamepad plays as:

| Saturn | Gamepad position (Xbox / PlayStation label) |
|---|---|
| D-pad | d-pad, or the left stick pushed past half way |
| A / B / C | west / south / east (X / A / B; Square / Cross / Circle) |
| X | north (Y; Triangle) |
| Y / Z | left / right trigger |
| L / R | left / right shoulder |
| Start | Start (Menu; Options) |

Each pad that connects becomes the next free player (the first one is player 1, beside the keyboard). Pads can be plugged in and pulled out while the game runs: a removed pad's buttons are released and its player is freed for the next pad, and a pad that comes back gets its player again.

The keyboard and gamepad bindings live in `settings.ini` (written with its defaults and comments on first run; the desktop package keeps it in its `work` folder, `--settings FILE` names another), `[keyboard]` with SDL key names and `[gamepad]` with the positions above. `stick` and `trigger` in `[gamepad]` set how far (in percent) the left stick or a trigger must move to press. A `[gamepad GUID]` section holds one model's own bindings; the log gives the GUID when the pad connects. Edits are kept across runs. For example:

```ini
[keyboard]
start = Return, Space

[gamepad]
stick = 35
```

A Saturn-style pad such as the 8BitDo M30 has two rows of three face buttons; the database lists it under positional names that do not match the Saturn's A B C / X Y Z rows, so run **Controller Setup** once and press the Saturn labels it asks for (not checked on a physical M30).

For tests, `--virtual-input SCRIPT` (windowed runs) plays an input script on SDL virtual gamepads through the same path as a real pad. `SF3_VIRTUAL_STICK=PERCENT` presses directions with the left stick at that deflection instead of the d-pad, and `SF3_VIRTUAL_UNPLUG=A-B` pulls player 1's pad out at VBlank A and plugs it back in at VBlank B.

## Frame pacing

The window waits for each field's real-time due point first and shows the picture afterwards, so pictures go out at an even ~59.83 Hz cadence even when the cost of running fields varies, and the pad is read as late as possible before the next field. This changes host timing only: the same fields, VBlanks and inputs run in machine time, and a fixed-input run produces bit-identical pictures, sound, machine state and backup memory.

To measure pacing, set `SF3_FRAMETIME=` (summary only) or `SF3_FRAMETIME=present.csv` (also writes every present-to-present interval) and quit through `--vblanks N`. At exit the log reports present intervals, the time each field took to run (emulation, composition and present), the pace wait, and how many fields started behind schedule. A machine that holds 60 fps shows a present interval near 16.7 ms with few fields behind schedule; many fields behind schedule mean the field cost exceeds the 16.7 ms budget on that host.

To prove a runtime change leaves the game unchanged, replay the same input headless with a fixed clock and compare pictures, sound, backup memory and the whole machine state (work RAM included) at the end:

```sh
saturn --headless --cue game.cue --save copy.bin --settings - --input @route.txt --vblanks 12000 \
  --clock 2026-01-01T12:00:00 --shot 1000,1100,... --wav out.wav --state-at 11990 --state-out end.state
```

`--clock` pins the SMPC clock; without it the game reads the host's time, and a few bytes of work RAM differ between runs. A command-line `--state-out` needs no `SF3_STATE_ID`: the state is then tied to the build's recompiled modules and the disc's file name. Compare state files by their parts (everything after the identity header).

The software compositor (the `software` renderer, screenshots and headless runs) composes each field in bands of rows on up to four threads; every row depends only on the field's VRAM, colour RAM, registers and sprite framebuffer, so the picture is the same as from one thread, and the game sees no difference in timing. `SF3_SERIAL_COMPOSITION=1` composes on one thread, for comparison. Disc-free timings of these paths on Linux and macOS (Apple Silicon and Intel) come from the "Runtime hot-path benchmark" workflow (`runtime/tests/runtime_bench.cpp`, run by hand or after each push to `main`).

## Display

Use **1× / 2× / 4× / 5×** for supported geometry resolution. 5× renders 56% more pixels than 4×, so it needs more GPU headroom. Source texture detail remains original. Vulkan is preferred; Direct3D 12 is another supported backend. `SF3_GPU_BACKEND=vulkan` or `direct3d12` can force one for troubleshooting. Unsupported GPU/video paths retain a native fallback, with different performance and enhancement coverage.

At normal speed, gameplay and audio keep the original roughly 59.8 Hz NTSC clock. Presentation targets that rate; higher monitor refresh does not speed up the game, and individual animations can update less often. Internal resolution stays at your chosen value: there is no automatic quality reduction. GPU tile binning and parallel composition of supported background rows reduce rendering overhead on suitable hardware, but performance in untested scenes is not guaranteed.

**Menu > Aspect ratio (beta) > 16:9** adds horizontal scenery; choose **4:3** for original framing. HUD/dialogue remain centered. The rotation-floor viewport window expands horizontally, retaining its vertical limits. Game-side object culling still uses original assumptions, so missing objects or pop-in at new edges can remain. Higher resolution and widescreen are experimental presentation features, not a claim of exact hardware output.

### Window, fullscreen and scaling

The window opens with the picture at 320x240 times `[display] scale` (default 3) and the button bar above it, so `scale = 1` shows the game's 320-pixel lines one to one. It can be resized freely; the picture keeps 4:3 (or 16:9) and stays centred. **F11** or **Alt+Enter** switches fullscreen, and the choice is saved as `[display] fullscreen` for the next start (`--fullscreen` and `--scale` on the command line win over the file). On a HiDPI display (Retina Macs, scaled Windows/Linux desktops) the picture is drawn at the display's full pixel density, and the button bar scales with it.

`[display] integer_scale = true` draws the picture at the largest whole multiple of the game's pixels that fits, with sharp (nearest) pixels and black borders, instead of filling the window smoothly; it applies to 4:3. `[display] vsync = true` presents in step with the display. It is off by default: the game paces itself to the clock, so a compositor that stops sending frames to a hidden window (KWin does) cannot stall it, and with vsync on, a hitch can only be made up at the display's rate, so the game can fall a little behind at 60 Hz. The log notes each picture size (`display: 960x720 picture at 0,36 ...`).

### Quitting

Close the window, choose **Quit** in the menu, or send the process SIGTERM: the run stops at the next field, also in the middle of a CD read or with audio playing, and exits cleanly. Progress saved in the game is already on disk (see Game saves).

## Game speed

Choose **Menu > Game speed (F6) > 1× / 2× / 3×**, click the **Speed** toolbar button, or press **F6** to cycle speeds. Each new process starts at 1×. Game speed is separate from rendering resolution: 5× resolution can stay selected while playing at 2× speed.

Start with 2× for long animations and return to 1× for normal play. The optional 3× setting is experimental; maintaining the selected multiplier is secondary to correct gameplay. No battle logic or save format is patched to force a speed increase.

Fast-forward runs the original game ticks sooner in real time. Battle calculations and virtual hardware clocks retain their original relationships. It applies to the whole game, including dialogue and menus; switch back to 1× for precise input. Audio plays faster and at a higher pitch. Each speed change clears queued playback and primes fresh audio, avoiding a backlog when returning to 1×. Requested 2×/3× speed requires CPU/GPU headroom and is not guaranteed in every scene. No automatic resolution reduction occurs. The experimental `--realtime` mode does not support the speed selector.

Game speed is included in v0.5.0-alpha; earlier v0.3.0/v0.4.0-preview1 downloads predate it. Developers can run `tools/validate-game-speed.py --help` for a windowed, real-audio comparison of an external route at all three speeds; it checks final native pixels, video memory, virtual PCM and backup contents independently from measured speed.

## Light anti-aliasing (development builds)

Choose **Menu > Edge AA (beta) > Light** to soften selected diagonal geometry edges on the GPU. **Off** restores the unfiltered picture; new processes start with AA off. Use 2×, 4× or 5× GPU rendering to try it. This is a small spatial filter with no previous-frame history or ray-tracing requirement, and it does not add texture detail.

The filter uses known geometry ownership to preserve ordinary sprite/text paths and unsupported background paths. The native toolbar and menu are drawn afterward. Unclassified geometry edges are deliberately left alone, and unusual game UI paths still need broader validation. Available with the GPU renderer; there is no CPU filtering fallback. Resolution, game speed, native video memory, game logic and save formats are unchanged. Light AA is included in v0.5.0-alpha. Developer route comparisons can enable it with `validate-game-speed.py --aa`.

## Game saves

Use the game's save command for ordinary persistent progress. The external files are `experimental-backup.bin` (32 KiB internal capacity) and `experimental-backup.bin.cartridge` (512 KiB cartridge capacity). They contain native backup records, **not raw emulator memory images**. Each in-game save is written to disk the moment the game saves (written beside the file, flushed, then renamed over it, and the folder flushed), not when the app exits, so a crash, a killed process or a power cut after the game says it has saved keeps the save. Back them up before changing versions or importing saves. The full game's save behavior has not been validated.

**Import Saturn Saves.cmd** accepts per-save raw `SFORCE31_XX.BIN` (12904 bytes), `SFORCE32_XX.BIN` (16248 bytes), and version-1 JSON `.ysbak` exports with matching filename, size and checksum. Development builds also accept `SFORCE33_XX.BIN` (24344 bytes) and matching YSBAK exports. Scenario 2 gameplay requires the experimental translated-v24 profile; Scenario 3 development uses the registered Translation Project v25.1 disc. Accepting a save format does not validate every scene it can load. The published Windows v0.3.0 and Linux/macOS v0.4.0-preview1 packages predate Scenario 3 support.

Choose internal or cartridge storage. A Scenario 2 save occupies 33 cartridge blocks; internal storage fits one Scenario 2 save. Imports preserve payloads and back up the destination. YSBAK filename, ASCII comment, language and save date are retained; embedded screenshots and remote URLs are ignored. Raw BIN imports generate comment/date metadata. Emulator and Saroo exports must match a supported format; whole memory dumps and emulator save states are not interchangeable. Stop the game before importing. The desktop package supplies Python; source builds need Python 3.11+ installed.

A Scenario 3 save occupies 49 cartridge blocks. Internal memory fits one Scenario 3 save; use cartridge storage when keeping completed earlier-scenario files alongside it. Each launcher scenario remembers its own disc and data folder. Carryover requires explicitly importing a completed earlier-scenario save into the destination scenario's backup storage; the launcher does not merge or overwrite your other games' progress.

## Native save states and replay checkpoints

v0.3.0 builds with native state continuations provide **Save state / Load state** in the toolbar and menu, or **F5 / F9**. They capture and restore the machine directly, including both CPUs, RAM, video, sound, CD state and internal/cartridge backup contents. Loading briefly restarts the native process; it does not replay earlier inputs. **Load Native State.cmd** loads the latest compatible state without first playing through the title screen.

There is one quick slot per exact executable/disc identity under `native-states` in the game-data folder. Wait for the window title to confirm the write. Corrupt and incompatible states are rejected. Updating the executable requires a new state; older slots remain intact. Native states are validated on limited Scenario 2 translated-v24 routes and a Scenario 3 v25.1 startup-to-ship route, not the complete game.

**Loading a native state restores its backup memory too.** Exact pre-load internal/cartridge files and the loaded state are retained in that session directory. Ordinary game saves and older replay checkpoints remain available. Replay checkpoint creation/loading within a session restored from a native state is disabled; use native states there.

The public v0.2.0 build and older native builds retain the replay controls described below. v0.3.0 keeps them as separate menu actions; F5/F9 now select native states.

Toolbar/menu Save checkpoint and Load checkpoint, or F5 and F9, record a route and restart/fast-forward it. **Load Replay Checkpoint.cmd** loads the latest compatible checkpoint. Keep the complete checkpoint, including initial internal/cartridge backups, clock, settings and input. They are tied to the exact disc and native executable and are not instant save states. New executable versions can invalidate them.

Replay sessions keep their own saves so loading an old checkpoint does not roll back ordinary progress. `publish-replay-save.ps1` is an explicit, separate action for adopting progress from a replay session; never copy historical validation backups over live progress automatically.

## Local session files

Sessions, input recordings and checkpoints stay in your work directory. Optional **Capture issue** (F8) also writes screenshots, memory/video dumps and context there. These are local troubleshooting features; no automatic upload occurs. Do not attach memory/video dumps, extracted assets, generated game code or saves to a repository issue. Describe a problem with the disc revision, scene, settings and reproduction steps instead. The normal launcher does not enable instruction/transition tracing; developers can opt in with `run-native.ps1 -Work WORK -Diagnostics`.
