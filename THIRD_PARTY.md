# Third-party notices

The root MIT license applies to this project's original source, not Sega game content or all dependencies indiscriminately.

## saturn-recomp / saturnkit

`tools/runtime-diagnostics.patch` modifies saturn-recomp revision `c8b724dc8140431a21627fc4c8c98b75a5346ca7`, derived from saturnkit.

Copyright (c) 2026 Samuele Voltan. Copyright (c) 2026 Callum Jenkins. MIT license; the complete notice is retained in `LICENSES/saturn-recomp.txt`. Setup obtains the upstream source rather than vendoring it here. Its `THIRD_PARTY.md` and source notices cover Musashi, SoftFloat, minicoro, stb_truetype, Inter, Dear ImGui and MAME-derived sound behavior. Keep those notices with any redistributed upstream runtime code or permitted runtime binaries. The optional Mednafen-derived GPL rasterizer is not enabled by the supported build configuration.

## SDL3 and controller mappings

SDL3 is distributed under the zlib license; its downloaded development archive contains its notices. SDL_GameControllerDB uses the zlib license and keeps author/contributor details in its upstream repository. The build copies its `LICENSE` as `CONTROLLER-DATABASE-LICENSE.txt` into the local work folder.

## Shader compiler and toolchain

Microsoft DirectX Shader Compiler is fetched as a development tool with the licenses and notices in its official release archive. LLVM/Clang and Visual Studio are separately installed build tools and are not redistributed in this repository.

## SFIII information and game content

SF3Tools informed module load-address metadata; this project does not vendor its implementation or any game data. See `tools/audit-modules.py` for the mapping provenance revision. Common instruction-pattern recognition and module entry/address metadata are used to generate code from the user's locally supplied disc.

No game assets, disc images, BIOS files, saves, extracted binaries or generated game code are licensed or distributed by this source repository. Owning a source-code license does not grant rights to those materials.
