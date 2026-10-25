# Testing plan: proving each scenario is fully playable

Goal: automated, repeatable evidence that each supported disc revision can be played from power-on to the ending, on Linux first. This covers Sc1, Sc2 and Sc3 with the latest Translation Project patches, then the Premium Disc. It complements [linux-bringup.md](linux-bringup.md).

**Data boundary.** Every layer except the synthetic ones needs the user's own discs and the real BIOS (for the emulator reference). They run **only on a private machine** (bring-your-own-disc). Public CI (`synthetic.yml`, `linux-native.yml`, `portable.yml`) runs synthetic tests only. Routes, inputs, checkpoints, RAM dumps, screenshots, coverage files and reports live outside the repository. Each tool here already refuses in-repo output paths (`external()` in `tools/validate-*.py`), and new tools must do the same. A route file is plain button timing and could in principle be shared, but reports derived from it contain disc bytes (RAM, frames) and must not be.

**Priority.** Build layer 2 (differential testing against Beetle Saturn) and layer 3 (scene/battle reachability sweep) first. They find the most bugs per hour of human attention, and they do not depend on having full-game routes. Layers 1, 4 and 6 then turn found routes into regression gates. Layers 5 and 7 add breadth and visual checks.

## Building blocks that already exist

| Piece | Where | What it gives us |
|---|---|---|
| `saturn` runtime CLI | `.local/saturn-recomp/runtime/src/app/main.cpp` | `--headless`, `--vblanks N`, `--input VBLANK:BUTTONS,…\|@FILE`, `--record-input FILE`, `--resume N`, `--peek ADDR[:WORDS]`, `--write VBLANK:ADDR=HEX`, `--cheat`, `--watch LO:HI` (+`--watch-vblanks`), `--shot N,…`, `--dump N,…` (video memory), `--wav`, `--video`, `--coverage FILE` (+`--checkpoint SECONDS`), `--state-in/--state-out/--state-at/--state-every`, `--progress FILE --progress-keep ADDR:BYTES,…`, `--clock`, `--save FILE\|-`, `--agent FD`, `--accurate-drive` |
| Agent socket | `saturnrecomp/agent.py` | Python drives a run: `step(n)`, `pad(buttons)`, `read/read32/write`, `frame()`. Every press is kept as an `--input` step, so a bot-played run turns into a replayable route. |
| Emulator reference | `saturnrecomp/reference.py` (+ `audio.py`) | Beetle Saturn libretro core, headless and frame-stepped. `read/write` of work RAM at Saturn addresses. `play_synced(core, tick_addr, …)` aligns our VBlanks to the core's frames by the game's own frame counter. `difference()` gives a pixel diff; `audio.window` gives a correlation-based sound comparison. Build the core without `-D_LOW_ACCURACY_`. |
| Missing-code discovery | `saturnrecomp/learn.py`, `saturnrecomp/executed.py` | `learn` reruns, adding seeds where a run stops at "call to X, not an entry of an active module". `executed` checks a reference's executed-instruction list against the recompiled map: translated / untranslated / BIOS / no module. |
| Profile audit | `tools/audit-modules.py`, `tools/validate-modules.py --require-complete` | Static closure: unresolved load addresses, entries and indirect targets. |
| Replay checkpoints | `native/replay-checkpoint.{h,cpp}`, `replay_checkpoint` CLI | Saves, verifies and loads checkpoints bound to an initial backup seed, a recording and a frame, rejecting incompatible ones. |
| Native-state validation | `tools/validate-native-states.py` | Snapshot restore compared with an uninterrupted run (frames, video memory, PCM, backup). Accepts routes that start from `state_in`. |
| Speed validation | `tools/validate-game-speed.py` | Identical pixels, video memory, PCM and backup across 1×/2×/3× speed (and `--aa`) for a route. |
| Save import | `tools/import-saturn-save.py` | BIN/YSBAK into `experimental-backup.bin`. |

The missing piece is **SF3-specific RAM knowledge**: addresses of the current scene/map id, battle id and battle-result flag, the game's frame counter (the `tick_addr` for `play_synced`), party roster, levels, HP, gold, and the story-flag array. Step 0 below finds them once per scenario. Translation patches change text and code layout, but they should not move core game-state variables; this must be verified per profile.

## Step 0: a per-scenario memory map (prerequisite)

Create an untracked, private `sf3-memory/<profile-id>.json`. When it is mature, a reviewed, data-free copy of the addresses can go into `profiles/` as an optional `memory_map` field. Its fields:
- `frame_counter`
- `scene_id`
- `battle_id`
- `battle_state`
- `party_base` and `stride`
- `gold`
- `flags_base` and `flags_len`
- `save_slot`

Methods:
- `--watch` with `--watch-vblanks` around a known scene change
- agent RAM diffs between two known states (before/after buying an item gives gold; before/after a level-up gives the party record)
- community notes from SF3Tools / the Translation Project editors (they already know the file formats and many RAM structures)

Cross-check each address against Beetle with `reference.read`. A checker script (`tools/sf3_state.py`, to be written) reads these through the agent or the core and emits one normalized **checkpoint record**: `{vblank, scene, battle, battle_state, party:[{id,level,hp,mp,exp}], gold, flags_sha1}`. Every layer below uses that record format.

## Layer 1: deterministic input-replay routes as full playthroughs

- **Route format:**
  - an `--input @FILE` script (produced by `--record-input`, by the agent's press log, or by a bot)
  - a fixed `--clock`
  - an initial backup seed (`--save` copy, or `-` for empty)
  - settings `-`
  - a route manifest listing checkpoints by VBlank, each with the expected checkpoint record
- **Execution:** `saturn --cue … --headless --input @route.txt --clock … --save seed-copy.bin --progress p.tsv --progress-keep <scene_id>:2,<battle_id>:2,<gold>:4 --coverage cov.tsv --vblanks END`. `--progress` already logs every change of the first watched range, with the VBlank, which gives "entered scene X at VBlank V" for free. A small runner (`tools/run-route.py`, to be written and modeled on `validate-native-states.py`) compares `p.tsv` and agent reads at each checkpoint with the manifest.
- **Segmenting:** `--state-out/--state-at` at each chapter boundary writes native states. Later segments start from `--state-in` (as `validate-native-states.py` already supports), so a 30-hour playthrough becomes parallel 30-60 min segments. Replay checkpoints (`replay_checkpoint`) cover the player-facing path. Native states are bound to the exact executable/disc identity, so regenerate them per build: rerun the previous segment, never migrate a state.
- **Pass criteria:** every checkpoint record matches; no `FATAL` / unresolved-call / runtime warning lines in `--log`; the final checkpoint is the ending scene.

## Layer 2 (priority): lockstep differential testing against Beetle Saturn

- **Inputs:** the same route as layer 1. `reference.play_synced(core, tick_addr=memory_map.frame_counter, …)` places each of our presses at the same game-tick on the core, so BIOS boot and CD-timing differences do not desynchronize the runs. Run ours with `--accurate-drive` to reduce load-timing drift.
- **Compare at checkpoints:**
  - the normalized checkpoint record (exact match required)
  - selected work-RAM windows (exact): the game-state structures from Step 0, **not** all of RAM, because stacks, DMA buffers and timing counters legitimately differ
  - optionally a frame diff (layer 7) and an audio correlation (`audio.window`)
- **First divergence:**
  1. On a mismatch, bisect between the last matching and the first mismatching checkpoint by stepping both sides in game ticks through the agent (`run.step`) and the core (`core.run`), comparing the state windows every tick.
  2. Report the first tick that differs, the differing addresses, and the active modules.
  3. Rerun our side with `--watch <addr>` and `--watch-vblanks` around it to get the storing function. That points directly at the recompiled function to inspect.
- **Wiring:** a `tools/differential.py` (private-run tool, data-free source) composes `agent.start(...)` and `reference.Core(...)`, following saturn-recomp's documented `play_synced` / `difference` usage (pc-saturnbomberman's `bomberman compare` is the upstream example). Output: a JSON report outside the repo.
- **Coverage tie-in:** run Beetle with an instruction trace and feed it to `python -m saturnrecomp.executed` to list *untranslated* code that the reference executed on the same route. That is a direct worklist of missing seeds for `audit-modules.py`.

## Layer 3 (priority): scene and battle reachability sweep

The audited profiles compile far more programs than routes reach (upstream notes 12 of 169 X1 scenes exercised in Sc1). The sweep boots **every** scene program and battle:
1. **Enumerate targets** from `module-audit/candidate-profile.json` / `module-audit` rows: every X1 scene file, X1BTL\*, X3 effects (Sc2 files, Sc3 `EFFECT.BIN` chunks), X025/X048/X049.
2. **Jump there:** load a native state from a known stable point (e.g. standing in the first town), then set the scene/battle request variables with `--write VBLANK:ADDR=HEX` (or the agent's `write`) and trigger the transition (a door, or the game's own debug/stage-select path if one is found in Step 0, which Translation Project tooling may document). The same `--write` mechanism is how saturn-recomp suggests stage selects. Each target is a separate headless process, run in parallel.
3. **Run N frames** (e.g. 1800), optionally with a scripted "press C / move randomly" input to open menus, start a battle turn, and cast. Battles can use `--cheat` for invincibility or auto-win flags so a battle can also be driven to its cleared state.
4. **Assert:**
   - the exit status is clean
   - no `FATAL` lines (calls into non-entries, unresolved indirect jumps, unmapped module loads)
   - no runtime warnings
   - the scene id reached equals the target
   - frames are not all black or identical (a cheap "not hung" check via `--shot` hashes)
   - optionally the same check on Beetle (layer 2 lite: same writes, compare the scene id and a frame)
5. **Triage loop:** for an unresolved call, run `saturnrecomp.learn` with the same saturn args to collect seeds, then review them into the profile. Results table: target × {boots, survives N frames, battle clearable, matches Beetle}.

## Layer 4: execution coverage burndown

- Each route, sweep and bot run passes `--coverage cov-<run>.tsv` (with `--checkpoint 60` for long runs, so a crash still leaves data). A merge script unions them: function × ran-at-least-once, grouped by module, plus indirect-jump targets observed (from the `learn`/FATAL logs and the reference's `executed` output).
- **Metrics per profile:**
  - % of recompiled functions executed
  - % of X1 scenes and battles reached
  - number of *untranslated* instructions the reference executed (target: 0)
  - unresolved indirect targets (target: 0)
- Track these as a burndown in the private report directory. Publish only aggregate numbers (no addresses tied to disc bytes needed) in docs.

## Layer 5: memory-reading scripted bot (breadth between checkpoints)

- A Python bot on `saturnrecomp.agent` reads the Step 0 map each tick. It walks the map toward exits, talks to NPCs, opens shops/menus/HQ, fights battles with a simple policy (attack the nearest enemy, heal under X% HP), and saves at churches.
- Its press log *is* an `--input` route, so any crash it finds is reproducible with layer 1 and comparable with layer 2.
- Use it to fill gaps between checkpoints: every shop, every menu, every spell and item on the field, promotion, the cross-scenario save prompt. Randomized seeds widen coverage; record the seed in the report.

## Layer 6: save/load and cross-scenario transfer at each checkpoint

At every layer-1 checkpoint:
1. **In-game save:** write a save, restart from power-on with that backup, load it, and require an identical checkpoint record.
2. **Native state (F5/F9) and replay checkpoint:** run `validate-native-states.py` from that point. It already compares restore against an uninterrupted run.
3. **Speed invariance:** run `validate-game-speed.py` on a short segment around a battle.
4. **Import:** take a BIN/YSBAK exported from Beetle at the same point, import it with `import-saturn-save.py`, load it, and require the same record.
5. **Cross-scenario:** take the Sc1 ending save (and Sc2's), start Sc2/Sc3 with that backup, run the game's import, and check the transferred party/flags with the Step 0 map. Then run the same on Beetle and compare (layer 2). Include the Premium Disc's save-reading once its profile exists. Note that `--other-disc` / `--from-other` exist for multi-disc file access.

## Layer 7: frame-hash and perceptual screenshot diffs against the emulator at 1×

- Run at `--render-scale 1`. Take `--shot` frames at layer-1/2 checkpoints and compare them with the core's frames through `reference.difference` (which knows Beetle's 330×240 framing of a 320×224 screen).
- Use **exact** hashes for self-regression (our build vs our previous build: same route, same frames, as `validate-game-speed.py` already does). Use a **perceptual** threshold for us-vs-Beetle: dots-differ ratio plus max channel error, reported with side-by-side images. `--dump` video memory helps separate VDP1 from VDP2 composition differences.
- Exclude interpolated/HD presentation (out of scope); test 1× native output only.

## How it runs

- `tools/` gains data-free scripts: `sf3_state.py`, `run-route.py`, `differential.py`, `scene-sweep.py`, `coverage-merge.py`, `bot.py`. Each takes `--cue/--work/--out` paths that must be outside the repo, and writes JSON reports. Unit tests use invented data, in the same style as `tools/tests`.
- A private runner script runs nightly per profile:
  - layer 3 sweep
  - layer 2 on all routes
  - layers 1 and 6 on all routes
  - layer 4 merge
- It runs on the user's Linux machine with discs, a BIOS and a Beetle core. Public CI keeps running only the synthetic suites.
- Acceptance for "fully playable" per profile:
  - every final acceptance replay reaches the ending with all checkpoint records equal to Beetle's
  - the sweep is green for all scenes and battles
  - zero untranslated reference-executed instructions on those runs
  - save, import and cross-scenario checks are green

## Final acceptance replays

### Sources (researched 2026-10-24)

No full-game Shining Force III TAS, movie or input file exists publicly. TASVideos has no SF3 entry, and [speedrun.com](https://www.speedrun.com/shining_force_3s1) has only Scenario 1 videos, with no input logs. We therefore **record our own segmented replays**.

**Recording tool:** BizHawk 2.10+ with the Saturnus core (Mednafen 1.32.1).
- Its `.bk2` input log is a per-frame text log ([BK2 format](https://tasvideos.org/Bizhawk/BK2Format)), trivially convertible to our `--input` syntax and to `reference.play_synced` presses.
- Pin, in each segment's manifest, the disc `content_sha256`, the BizHawk version and the core SyncSettings (region, BIOS, cart, RTC).

**Segmentation:**
- one segment per chapter, and per battle where useful
- each segment starts from a known save, so a broken segment is re-recorded in isolation

**Anchor saves.** Link to these; **do not vendor** them in this repository.

- Translation Project FTP, [Game Saves / Emulator Saves](https://sf3transftp.shiningforcecentral.com/Game%20Saves/Emulator%20Saves/):
  - complete-game saves for Sc1-3 in many emulator formats, including Mednafen `.bkr`
  - chapter saves (Sc1 ×3, Sc2 ×6, Sc3 ×7) with time and location notes
  - real-hardware Sc2 saves under [Game Saves / Hardware Saves](https://sf3transftp.shiningforcecentral.com/Game%20Saves/Hardware%20Saves/)
- bucanero's [saturn-save-tools: Shining Force III](https://bucanero.github.io/saturn-save-tools/shining-force-3/): pre- and post-final-battle `.BUP` saves.
- Save editor: [game-tools-collection SF3 save editor](https://game-tools-collection.com/shining-force-3/save-editor), for crafting targeted states, e.g. a party for a battle-sweep start.
- Format facts:
  - saves are `SFORCE31_NN` / `SFORCE32_NN` / `SFORCE33_NN` entries in Saturn backup RAM, with a simple-sum checksum
  - `import-saturn-save.py` already brings BIN/YSBAK into `experimental-backup.bin`
  - Mednafen `.bkr` and `.BUP` need converters (to be written, data-free)

### Harness

- **Event-driven, not frame-exact, for long segments.** CD timing, lag frames and RNG drift mean a frame-exact input log from Saturnus will not stay aligned with our runtime over a chapter. The runner advances to RAM *conditions* from the Step 0 memory map, then replays the next input block. Example conditions:
  - "waiting for input"
  - "battle N started"
  - "battle N won"
  - "save written"

  This is layer 1 with conditions instead of VBlank numbers, plus `--progress` for scene changes.
- **Frame-exact lockstep only for short segments.** For in-battle segments started from a save, use layer 2: frame-exact input with RAM diffs against Mednafen/Beetle at every tick. Precedents: [zelda3](https://github.com/snesrev/zelda3)'s lockstep RAM comparison against the original, and sm64-port's `controller_recorded_tas.c` playback.
- **RNG:** SF3's RNG source is unknown. Find it in the recompiled code: look for the LCG/seed update, and whether it is fed by frame counts, input or the RTC. That determines whether event-driven replays stay deterministic through battles, or whether the runner must pin the seed with `--write` at segment start.

### Story driver and committed segments (`tools/sf3-story.py`)

- `drive` loads one save record and plays forward with the closed-loop autoplay (aimed battles,
  walker in towns). The goals are the scenario's later records in play-time order: a record is
  reached when every story-flag bit it holds (record bytes 0x240-0x400, mirrored in work RAM per
  profile, see `sf3test/story.py`) is set live; town/complete records that add no flag bits are
  reached when their map holds. Every pad change (and every test-only `--assist` poke) is logged
  with its VBlank in `segment.txt`, with the end RAM and story-flag hashes.
- Determinism: every run passes a fixed `--clock` (the SMPC clock; the game keeps the date in work
  RAM, so host-clock runs a few seconds apart ended with different RAM hashes). With the clock
  fixed, a replay is frame-exact: same RAM hash, same flags, same goals at the same VBlank.
- `replay SEG` reruns one segment and checks the end hashes, the goals reached and no FATAL.
  `suite` replays every `tools/story-replays/<key>/*.seg` (`sc1 sc2v2 sc2v1 sc3`) with the build,
  cue and saves from `SF3_BUILD_<KEY>`, `SF3_CUE_<KEY>`, `SF3_SAVES_<KEY>`.
- Committed segments are pad presses only: no pokes, no assist, a clock and an end hash, and only
  the header keys in `story.SEGMENT_KEYS` (profile, save file name, record id and hash, seed,
  build hash, end hashes, goals). `tools/tests/test_story.py` and `check-source-package.py`
  reject anything else. A segment is bound to its build (`binary`): a runtime change that alters
  timing needs the segment re-recorded (rerun `drive` with the same seed), which is the point.

### Pass condition per scenario

1. Reach the ending and write the complete-game save (`_02`).
2. Byte-compare that save, excluding names and timestamps, with the emulator's save produced from the same replay.
3. Import it into the next scenario (Sc1 → Sc2 → Sc3) and pass that scenario's opening transfer checkpoint (layer 6).

### Caveats

- Separate recordings are needed per revision (Sc2 V1.003 vs V2.000), per Translation Project patch level, and for NTSC vs PAL.
- The Premium Disc has no saves to anchor on. Use a boot-and-browse script that walks every menu and viewer, instead of a playthrough.

### Per-profile status

| Profile | Replay source | Anchor saves | Checkpoints manifest | Status |
|---|---|---|---|---|
| Sc1 USA V1.001 (unpatched) | own BizHawk segments (to record) | TP FTP Sc1 chapter ×3 + complete | TBD | not started |
| Sc1 + latest Translation Project | own BizHawk segments (to record) | TP FTP Sc1 chapter ×3 + complete | TBD | sweep + differential running (see Status) |
| Sc2 V1.003 + latest TP | own BizHawk segments (to record) | TP FTP Sc2 chapter ×6 + complete; hardware saves | TBD | sweep + differential running (see Status) |
| Sc2 V2.000 + latest TP | own BizHawk segments (to record) | TP FTP Sc2 chapter ×6 + complete; hardware saves | TBD | sweep + differential running (see Status) |
| Sc3 + latest TP (V25.1 + V25+ updates) | own BizHawk segments (to record) | TP FTP Sc3 chapter ×7 + complete; bucanero pre/post final battle | TBD | sweep + differential running (see Status) |
| Premium Disc | boot-and-browse script | none | TBD | not started |

## Status (2026-10-24): layers 2 and 3 for the latest-translation profiles

**Layer 3, reachability sweep** (`tools/sf3-sweep.py`). Each save record of the TP FTP chapter saves, the complete-game saves and the hardware/bucanero saves is loaded through Continue, then driven by seeded input for 8000 VBlanks:

```
python tools/sf3-sweep.py --saturn BUILD/saturn --cue DISC.cue --profile scenario1-usa-v25_1 \
    --out /private/sweep/sc1 --saves A.bin B.bkr C.BUP --jobs 5 [--maps 0-255 --map-base SAVE:NN]
```

| profile | targets | result | maps / battle ids reached | functions run (union) |
|---|---|---|---|---|
| Sc1 V25.1 | 112 | 112 ok | 65 / 44 | 3.7% |
| Sc2 V2.000 | 125 | 125 ok | 71 / 50 | 3.3% |
| Sc2 V1.003 | 125 | 125 ok | 73 / 52 | 3.4% |
| Sc3 | 116 | 114 ok, 2 false no-loads (fixed in the analyzer) | 59 / 49 | 3.1% |

No crash, FATAL, unresolved call, hang, black or frozen run. The VDP2 features the runtime noted as missing (line scroll, extended colour calculation) were implemented; the remaining notes are line colour from rotation coefficients (KTCTL LCCE) and vertical cell scroll.

**Layer 2, differential** (`tools/sf3-diff.py`). The reference is a libretro core passed by path (no emulator code in this repository). Each side drives its own menus to the load; inputs and checkpoints are then placed by the game's play-time tick. The state block at every checkpoint matched for Sc1, Sc2 (both revisions) and Sc3 chapter-1 records. Caveats:
- Yabause with the HLE BIOS stops in Sc1/Sc2 battles (invalid opcode), so it is only a valid reference through boot, menus, loading and towns. Beetle/Mednafen with a real BIOS is needed for battles.
- Frame diffs drift once dialogue/camera timing desynchronizes the input placement; treat them as evidence only before the first divergence.
- Sweep runs are reproducible: the same target run three times concurrently under full host load gave identical coverage, progress and shots, and two whole sweeps (before/after #5) matched run for run. An earlier "divergence" came from comparing runs with different input scripts; `result.json` now records `input_sha1` so only comparable runs are compared.
- **Beetle Saturn with a real BIOS** (`--bios DIR`, a directory of your own BIOS dumps under Mednafen's names; they are linked into the run's directory, never copied into the repository). Build the core from libretro/beetle-saturn-libretro and pass it as `--core`. This is the battle-accurate reference; Yabause/HLE remains usable for boot, menus and towns.
- **Step edges vs Beetle.** Beetle Saturn's `retro_run` returns at raster line 262 (VCounter 262 in its VDP2 state), after the VBlank-IN handler has written the game's pad word and with that VBlank's SMPC INTBACK in flight. The agent's step ends at VBlank-IN, before that handler, so the same press showed up one step later in our records: a harness phase, not SMPC latency (on both sides the INTBACK that first sees the press falls in the same step, and the game copies it to its pad word 3 VBlanks later). `sf3test.diff` therefore sets `SF3_AGENT_LINE=262` for Beetle runs, which holds our pause to the same line; the game ticks at load and a held press then match frame for frame. One small difference remains: ours samples the pad when INTBACK is issued, Beetle a little after its step edge, so a press held for one step only can be caught by ours and missed by Beetle.
- **CPU time model.** Each recompiled block charges its SH-2 issue cycles (the SH-2 programming manual's counts, summed by the emitter: `SH2_CYC(c, n, m)`, plus 2 cycles for a taken `bt`/`bf` and 1 for a taken delayed one) and `m` memory accesses at `SF3_MEM_Q` quarter cycles each (default 8, two cycles of average cache/bus wait). A device register access adds its bus's wait (mmio.cpp: on-chip 3, SCU 4, A-bus/CD 12, VDP1/VDP2 10 read 6 write, SCSP 16/12, SMPC 12 cycles; our estimates, `SF3_BUS_WAITS` overrides). DMA and device traffic is charged to no CPU (`BusQuiet`). Safe points (`SH2_SAFE`) poll when the budget (4·2932 quarter cycles) is spent; virtual time is cycles × 34921 ps (`SF3_PS_PER_CYCLE`). Code generated before the model (`SH2_POLL`) still builds and charges the old flat 400 ns per safe point. Fitted on Sc1 battle 1 with `--accurate-drive` against Beetle (sweep/r30): battle-counter start 356 vs 357 and the first 24 counter values (1,2,3,3,3,4,5,5,5,…) equal; the old flat 400 ns gave 336. `SF3_MEM_Q` 0/4/8/10/12 → start 349/352/356/355/359. **CD end of play** (`--accurate-drive`): the drive reports BUSY for one sector time after the last sector, then PAUSE with PEND, as Beetle does (2 sectors after the end FAD); the periodic report comes once per sector time while playing; data reads start 3 ms later. That value is fitted to two Beetle targets: the Sc1 battle-1 counter start (358 vs 357, plateaus 24/24) and the church (record 01) load's fade-in. For the fade-in, ours was 4 VBlanks early with the old 400 ns + old CD model and is now within 1 VBlank. The fade-in does not move with `SF3_MEM_Q` (0 and 8 give the same frames), so that load is drive-bound.
- **Sc1 battle 1 vs Beetle at no-input alignment.** Camera and units match. The remaining work-RAM differences are not port bugs: 0x06064000-0x06067FFF is the title screen's animation table, last written by X009 before START and never touched again, so its contents depend on the frame START is pressed on (moving START by 10 VBlanks changes it; of the 22 words battle code writes in 0x06063000-0x06067FFF, all match except a per-frame counter at 0x060633A8); 0x0609C000 is a pre-load buffer Beetle refills later than ours and partly leaves stale; 0x060B0000 is a 16-bit image rebuilt every few frames (same colours, different animation phase). The floor's per-pixel differences come from VDP1 texture stepping: the runtime's own rasterizer, not RAM.
- **VDP1 replay, no timing** (`tools/sf3-vdp1-replay.py`). `snap` keeps the reference core's VDP1 VRAM, draw/erase registers and draw framebuffer from its save-state interface at chosen frames; `replay` draws the same VRAM with our rasterizer alone (`runtime/tests` target `vdp1_replay`) and reports dot-exact match over 320x224. A state is taken at one point of the frame and the draw runs at another, so each snapshot holds two pairings (the frame's own draw, and the VRAM just before the next frame change with the draw after it) and the better one counts. Exact match before/after the round-2 texture sampling rules: Sc1 church 75.2% -> 97.3%, church with more people 76.0% -> 97.3%, battle 1 87.5% -> 96.7%, Sc3 deck 84.8%/90.8% -> 87.6%/95.8%, Continue menu 99.8-100% -> 99.8-100%. The rules came from coordinate-coded characters written into the reference core's VRAM through its save-state interface (each texel encodes its own column and row) and read back from its framebuffer: a shrunk line or row samples the texel under each dot's centre; high speed shrink steps over column pairs and takes the EOS parity of the stored (unflipped) character; an anti-aliasing dot takes the next step's texel and Gouraud colour; enlarged columns round exact halves up. These fixed the church's 48x48 wall stripes.
- **VDP2 replay, no timing** (`tools/sf3-vdp1-replay.py replay2`, `runtime/tests` target `vdp2_replay`). The same snapshots also keep VDP2's VRAM, CRAM and registers, both VDP1 framebuffers and the reference core's output picture; our VDP2 compositor composes the frame from that state with the shown VDP1 framebuffer, and the picture is compared dot for dot. Round 3: 100.00% exact on all nine snapshots (Sc1 Continue menu, church, battle 1 at two frames, Sc2 battle 2 at two frames, Sc3 battle 3 at two frames with the rotated floor, Sc3 deck), so static priority, colour calculation, scroll, rotation, windows and shadow agree; what remains for VDP2 is register changes during a frame, which one register set cannot show.
- Round 3 VDP1 rule: an enlarged, vertically flipped character's rows round exact halves up (counted in drawing order), unflipped ones down. Exact match before -> after: Sc2 battle 2 90.2% -> 91.3%, Sc3 battle 3 88.1% -> 88.5%, Sc3 deck 87.6% -> 88.0%, Sc1 battle 1 96.7% -> 96.8%, church 97.3% and menu 99.8% unchanged. The deck's horizontally flipped portraits (distorted sprites, 40x40 and 48x40) look one dot narrower in the reference than their vertices give, but the portraits move between frames and a narrower rule for every flipped enlarged line makes the battles worse, so that is left as a pairing question rather than a rule.
- **Map sweep, 0x61** read 0x003030EC: work RAM low appears twice, at 0x00200000 and 0x00300000, and the runtime mapped only the first. Fixed in `tools/runtime-diagnostics.patch`; map 0x61 now plays.

### Scenario 3 map sweep: crashes at 0x6B/0x74/0x75/0x76 and 0x4D (round 6)

- 0x6B, 0x74, 0x75 and 0x76 load and play on Beetle Saturn with a real BIOS (valid maps). In the port they died
  with a 2-byte read of 001FFEAA: X003 (function 06038970) indexes a WRAM-L table at 0x00200030 with
  (id - 32) * 26 for an id of 0x11, landing 390 bytes below WRAM-L. That address is in the backup-RAM area,
  which repeats every 64 KiB from 0x00180000 to 0x001FFFFF; the runtime only mapped the first 64 KiB.
  Fixed by mirroring backup RAM over the whole area; all four maps now run 8000 VBlanks ok.
- 0x4D: black screen after the load on Beetle, then map id 0, so it is not a map the game can enter; the
  port's crash (4-byte write to 00FF00FF after a jump to 0) is not a port bug. Marked invalid.

## GPU renderer against the CPU path

`gpu_parity OUTDIR SHADERDIR` (built from `tools/tests/gpu-parity.cpp`) renders synthetic VDP1 command lists and VDP2 register scenes written by the test itself (sprites, distorted floor tiles, colour-calculation effects, clipping, priority against an NBG0 bitmap and three random command replays). No disc or BIOS data is used. Each scene goes through the accurate CPU path and then through the GPU renderer at 1×, 2× and 4×. 1× must match the CPU frame exactly. At 2× and 4×, the number of output dots whose colour exists in no CPU dot nearby must stay within per-scene limits. Those dots are subpixel resampling of distorted polygons, not glitches. For each scale the test writes `-cpu`, `-gpu-Nx` and `-diff-Nx` PNGs: grey means equal, yellow near, magenta alien, red miss and cyan lost. Linux CI runs it on lavapipe (artifact `gpu-parity-linux-lavapipe`). The package jobs run it on Metal for macOS and Vulkan for Linux (artifact `gpu-parity-<target>`).

The app defaults to internal scale 1× at 4:3, which uses the accurate CPU path. The GPU path runs only when the player picks 2×/4×/5× or 16:9.
