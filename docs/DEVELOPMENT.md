# Development and publication

Only reusable source, scripts, synthetic tests, pinned dependency identifiers and public-facing documentation belong in Git. The root ignore rules intentionally allowlist these files. Local research/history, external fixtures, captures, logs, game-derived output and builds are excluded. Source-level diagnostic support is part of the runtime; recorded diagnostics are not part of the repository.

Before pushing, run `python tools/check-source-package.py --tracked` and inspect `git diff --cached --stat`. This checks the selected publication files for binary data, game/build outputs, machine-specific paths and common credential patterns. It is an additional guard, not proof that arbitrary future files are appropriate to publish. Never force-add game files around the ignore rules.

## Synthetic tests

After dependency setup, from PowerShell:

```powershell
. .\tools\dev-env.ps1
cmake -S tools/tests -B 'D:\SFIII-checks' -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ "-DSATURN_RUNTIME=$PWD/.local/saturn-recomp/runtime"
cmake --build 'D:\SFIII-checks' --target dsp_regression core_regression bup_regression machine_regression background_regression audio_buffer
```

Run each of those six executables from the checks directory. GPU/UI synthetic targets are available in the generated game's build; captured video inputs are optional external data and must never be committed. A test without its required fixture is unavailable validation, not a pass. Public tests use invented data; local captured routes are not distributed.

Before promoting runtime changes into an existing playing installation, also replay the exact available transition fixtures using preserved initial internal/cartridge backups, clock, settings and input. Compare native frame/video hashes and inspect changed frames. Preserve the previous runnable build and checkpoints. Never use historical validation saves as live progress. Local maintainer transition tooling and fixtures may be kept separately; the public source does not reproduce private route fixtures by itself.

## Known coverage limits

The audited profile can emit far more scene programs than have been exercised. Review unresolved indirect targets, ambiguous overlays and load-address findings rather than treating compilation as execution proof. Current local nine-route validation covers 12 X1 scenes out of 169 compiled scene modules. The complete game, other scenarios/regions, translation patches and full hardware fidelity remain unvalidated.

The runtime patch must be reproducible against the exact commit in `dependencies.json`. Keep the upstream MIT notice with it. Generated game C++, object files and executables stay external even when they are useful for debugging. No public CI job should require or download copyrighted game or BIOS files.
