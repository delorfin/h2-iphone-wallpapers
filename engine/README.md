# Engine

A copy of the [fheroes2](https://github.com/ihhub/fheroes2) engine as adapted by [h2lwp](https://github.com/IlyaPomaskin/h2lwp) (an Android live wallpaper), taken at h2lwp commit 9ed990e1f and licensed GPL-2.0-or-later (see LICENSE). `src/thirdparty/libsmacker` is under LGPL-2.1-or-later (see its COPYING). Only what the macOS build and rendering need is kept: the Android app, other platforms, translations, music, tools, the Mac app bundle and CMake files are left out.

Changes for this project, each file marked with a "Changed in 2026" note:

- `src/fheroes2/game/game_wallpaper.cpp`, `game.h`, `fheroes2.cpp`: command-line modes that h2live runs.
  - `--scout-maps <dir> [map...]` writes per-map JSON of every tile's terrain and object parts, for view selection.
  - `--render-views <views.txt> <dir> <width> <height> <frames>` renders animation frames for chosen views, with palette cycling baked in. Map loading is seeded per map, before random races are picked, so scouting and rendering agree.
  - `--render-wallpapers <dir> <count> <width> <height> <frames>` renders random views; h2live no longer uses it.
  - Both scout and render read `.mp2`/`.mx2` maps and fheroes2's `.fh2m` maps.
  - A macOS build fix: Android-only calls are guarded.
- `Makefile`, `src/dist/Makefile`, `src/dist/fheroes2/Makefile`: build only the engine binary, without the tools or the translation template (so gettext isn't needed).

`maps/` holds fheroes2's bundled `.fh2m` maps (see `maps/README.md`); h2lwp's own bundled `.mp2` maps were dropped, since their source and license are unknown.

Build it with `../build.sh`, not plain `make` (see the main README).
