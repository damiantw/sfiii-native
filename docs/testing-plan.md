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

_Placeholder: to be filled in with the full-game replay sources per profile._

| Profile | Replay source (route/input file, origin, licence) | Initial backup / clock | Checkpoints manifest | Status |
|---|---|---|---|---|
| Sc1 USA V1.001 (unpatched) | TBD | TBD | TBD | not started |
| Sc1 + latest Translation Project | TBD | TBD | TBD | not started |
| Sc2 V1.003 + latest TP | TBD | TBD | TBD | not started |
| Sc2 V2.000 + latest TP | TBD | TBD | TBD | not started |
| Sc3 + latest TP (V25.1 + V25+ updates) | TBD | TBD | TBD | not started |
| Premium Disc | TBD | TBD | TBD | not started |
