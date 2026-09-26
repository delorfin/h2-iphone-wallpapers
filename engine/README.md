# Engine

A copy of the [fheroes2](https://github.com/ihhub/fheroes2) engine as adapted by [h2lwp](https://github.com/IlyaPomaskin/h2lwp) (an Android live wallpaper), taken at h2lwp commit 9ed990e1f, licensed GPL-2.0 (see LICENSE). Only what the macOS build needs is kept; the Android app and other platforms are left out.

Changes for this project, all in `src/fheroes2/game/` (`game_wallpaper.cpp`, `game.h`, `fheroes2.cpp`):

- `--render-wallpapers <dir> <count> <width> <height> <frames>`: random views, animation frames with palette cycling baked in.
- `--scout-maps <dir> [map...]`: per-map JSON of every tile's terrain and object parts, for view selection.
- `--render-views <views.txt> <dir> <width> <height> <frames>`: frames for chosen views; map loading is seeded per map (before random races are picked) so scouting and rendering agree.
- Scout and render modes read both `.mp2`/`.mx2` and fheroes2's `.fh2m` maps.
- A macOS build fix (Android-only calls guarded).

`maps/` holds fheroes2's bundled `.fh2m` maps (see `maps/README.md`); h2lwp's own bundled `.mp2` maps were dropped, since their source and license are unknown.

Build it with `../build.sh`, not plain `make` (see the main README).
