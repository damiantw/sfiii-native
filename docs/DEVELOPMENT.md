# Development and publication

Only reusable source, scripts, synthetic tests, pinned dependency identifiers and public-facing documentation belong in Git. The root ignore rules intentionally allowlist these files. Local research/history, external fixtures, captures, logs, game-derived output and builds are excluded. Source-level diagnostic support is part of the runtime; recorded diagnostics are not part of the repository.

Before pushing, run `python tools/check-source-package.py --tracked` and inspect `git diff --cached --stat`. This checks the selected publication files for binary data, game/build outputs, machine-specific paths and common credential patterns. It is an additional guard, not proof that arbitrary future files are appropriate to publish. Never force-add game files around the ignore rules.

## Synthetic tests

After dependency setup, from PowerShell:

```powershell
. .\tools\dev-env.ps1
cmake -S tools/tests -B 'D:\SFIII-checks' -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ "-DSATURN_RUNTIME=$PWD/.local/saturn-recomp/runtime"
cmake --build 'D:\SFIII-checks' --target dsp_regression core_regression bup_regression machine_regression background_regression audio_buffer game_speed
```

Run each of those six executables from the checks directory. GPU/UI synthetic targets are available in the generated game's build; captured video inputs are optional external data and must never be committed. A test without its required fixture is unavailable validation, not a pass. Public tests use invented data; local captured routes are not distributed.

Also run `game_speed` for 1×/2×/3× deadlines, stalls and restored clocks. The SDL `replay_ui_selftest` exercises speed-button/F6/menu changes, queue clearing, scaled audio priming and pause rebasing with synthetic data. `validate-game-speed.py` complements headless transition checks with a windowed, audio-enabled replay comparison at all three rates. Its report separates requested and achieved speed from identical native pixels/video memory, virtual PCM and backup contents. The route manifest, exact initial backups, clock and inputs must be external. Fast-forward is whole-game host pacing, not a modification to battle logic; pitch follows the audio playback ratio.

Design references: [Snap64 Recomp v1.0.8](https://github.com/JackandBeans/Snap64Recomp/releases/tag/v1.0.8) documents fast-forward through accelerated clocks, reduced presentation work and faster/higher-pitched audio. This is its maintainer's documented behavior; that project was not built or tested here. Our audio path uses SDL's [stream frequency ratio](https://wiki.libsdl.org/SDL3/SDL_SetAudioStreamFrequencyRatio), which changes consumption speed and pitch. The machine still generates its original PCM. At 2×/3× we execute every machine field but compose/present every second/third host picture, preserving the selected resolution while limiting CPU/GPU presentation overhead. Input polling, VDP1 execution, interrupts and sound continue on skipped pictures; requested diagnostic screenshots and video recording can force extra composition. This does not certify complete battles, every scene or campaign-wide determinism.

Before promoting runtime changes into an existing playing installation, also replay the exact available transition fixtures using preserved initial internal/cartridge backups, clock, settings and input. Compare native frame/video hashes and inspect changed frames. Preserve the previous runnable build and checkpoints. Never use historical validation saves as live progress. Local maintainer transition tooling and fixtures may be kept separately; the public source does not reproduce private route fixtures by itself.

## Known coverage limits

The audited profile can emit far more scene programs than have been exercised. Review unresolved indirect targets, ambiguous overlays and load-address findings rather than treating compilation as execution proof. Current local nine-route validation covers 12 X1 scenes out of 169 compiled scene modules. The complete game, other scenarios/regions, translation patches and full hardware fidelity remain unvalidated.

The runtime patch must be reproducible against the exact commit in `dependencies.json`. Keep the upstream MIT notice with it. Generated game C++, object files and executables stay external even when they are useful for debugging. No public CI job should require or download copyrighted game or BIOS files.
