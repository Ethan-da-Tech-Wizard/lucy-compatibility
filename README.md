# Lucy mod compatibility check

This tool reads a mod JAR and reports its declared loader and Minecraft requirements. It does not install, modify, extract, run or port a mod; it cannot prove a game will work. It accepts a local JAR path and optionally a Prism instance directory. No Pixelmon JAR is included or downloaded.

Run on the existing Lucy game as a check:

```sh
python3 lucy_compat.py "$HOME/Library/Application Support/PrismLauncher/instances/LucysGame/.minecraft/mods/lucys-game-1.0.0.jar" --instance "$HOME/Library/Application Support/PrismLauncher/instances/LucysGame"
```

To check a Pixelmon JAR you already possess, replace the first path with its actual location and use the same `--instance` argument. `incompatible` means a declared loader or supported numeric Minecraft version conflicts. `unknown` means metadata is missing, unreadable or uses an unsupported constraint. `metadata_match_only` means the two supported declarations match; game runtime, API, dependencies, multiplayer and licensing remain unverified. An incompatible or unknown result exits with status 2. The checker recognizes exact numeric versions and simple Maven version ranges; unsupported range syntax stays unknown.

Test with:

```sh
python3 -m unittest -v
```

## Audit an experimental Radical Red registry

This separate read-only check compares an embedded registry against the independently sourced species and move fixtures, verifies the optional candidate-JAR hash, and reports field presence, declared validation gaps and whether an items table exists. It does not prove that battle effects, a game client, or multiplayer work. Exit status 2 means an error, a fixture mismatch, or an incomplete registry; passing fixtures do not override a partial status.

```sh
python3 registry_audit.py \
  lucys-game-1.0.0.jar \
  --fixtures rr-independent-fixtures.json \
  --move-fixtures rr_move_fixtures.json \
  --expected-sha256 4a3a6f30ab5cf4eb1859cb7790347578e7420001fa0b23760f6c7f709892670f
```

For a newer release, replace the JAR and expected hash with that release's independently verified manifest value. Fixture revision must match the embedded source commit; absence of a supplied move-fixture file means move fixtures were not checked.

## Projects by Ethan-da-Tech-Wizard

This repository is part of a suite of systems, tools, and experiments maintained at [github.com/Ethan-da-Tech-Wizard](https://github.com/Ethan-da-Tech-Wizard):

- [ashr](https://github.com/Ethan-da-Tech-Wizard/ashr) — Phone-in-the-loop agent supervisor.
- [space_map](https://github.com/Ethan-da-Tech-Wizard/space_map) — Spatial computing & treemap disk engine in C++20 and Qt6.
- [lucy-compatibility](https://github.com/Ethan-da-Tech-Wizard/lucy-compatibility) — Minecraft mod compatibility checker & Radical Red registry audit.
- [twu-wasm-engine](https://github.com/Ethan-da-Tech-Wizard/twu-wasm-engine) — WebAssembly sandbox execution engine & celestial simulation in Rust.
- [lantern-runelite-remote](https://github.com/Ethan-da-Tech-Wizard/lantern-runelite-remote) — View and control your RuneLite window from iOS.

## License

Dual-licensed under either of:

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE))
- MIT License ([LICENSE-MIT](LICENSE-MIT))

at your option.
