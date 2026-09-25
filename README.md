# HoMM2 map wallpapers for iPhone

Renders random views of Heroes of Might and Magic II adventure maps on the Mac and turns them into Live Photos that the iPhone lock screen plays as moving wallpapers. The phone uses only built-in apps: a synced Photos album and a daily Shortcuts automation. iOS has no live wallpaper API for third-party apps, so this is the closest equivalent; see [docs/findings.md](docs/findings.md) for why it works the way it does.

What you get: every morning a new wallpaper on the lock and home screen. On wake, the lock screen plays about 1.7 s of map animation (units, flags, water, a slow pan), then settles on the still.

## Requirements

- macOS with Photos, Homebrew and [uv](https://docs.astral.sh/uv/).
- `brew install sdl2 sdl2_mixer ffmpeg gpac exiftool imagemagick libheif`
- HoMM2 game data in `~/Library/Application Support/fheroes2` (`DATA`, `MAPS`).
- iPhone with iCloud Photos **off** (Finder photo sync only works then).

## Build

```sh
ios-livephoto/build.sh
```

Use the script, not plain `make`: it builds a release engine (developer assertions abort on some shipped maps) and replaces `./fheroes2` with a fresh file (macOS kills a binary that `make` overwrote in place).

## Make wallpapers

```sh
cd ios-livephoto
uv run h2live batch --out ~/Pictures/h2lwp-batches/$(date +%F) --count 365 --album "H2"
```

This scouts every map (first run only, cached per renderer build in `~/Library/Caches/h2live`), picks views that pass the selection rules, renders them, builds Live Photos and imports them into the Photos album. Options: `--scale` (2-4, default 3), `--brightness` (default 70), `--no-import`. A batch of 365 takes a while; each wallpaper is about 3.5 MB.

## Get them onto the iPhone

Finder photo sync, one-time setup:

1. Connect the iPhone by cable, unlock it, trust the Mac.
2. Finder → iPhone → General: tick "Show this iPhone when on Wi-Fi".
3. Photos tab: tick "Sync photos to your device from: Photos", choose "Selected albums", tick **H2**, keep "Include videos" ticked. Apply.

After that, a sync starts when you select the iPhone in Finder's sidebar (cable, or Wi-Fi while the phone is awake or charging). The album appears on the phone as a read-only synced album. Synced photos keep their Live Photo motion, don't count against iCloud storage, and aren't picked up by Google Photos.

## Daily rotation on the iPhone

1. Shortcuts → new shortcut "H2 wallpaper": **Find Photos** (Album is H2) → **Get Item from List** (Random Item) → **Set Wallpaper Photo** (Lock Screen and Home Screen; expand the action with › and turn **Show Preview off**).
2. Automation → Time of Day, e.g. 05:00, Daily, **Run Immediately**, Notify When Run off → run "H2 wallpaper".

Show Preview must be off: with it on, the automation reports success and changes nothing.

## Selection rules

A view is used only if it passes every rule (`h2live/select.py`); the thresholds were calibrated against the user's verdicts on contact sheets, pinned in `tests/test_sheet_verdicts.py`. Objects include trees, mountains and ground decorations; borders between terrains count as content, roads and rivers don't.

| Rule | Fails when |
|---|---|
| Empty | a 6×6-tile patch has no object and no terrain border |
| Clumped | over 45% of the view lies in blank 2×2 patches |
| Sparse | under 22% of tiles hold objects |
| Repetition | 3 identical objects in a straight evenly spaced line, or a 2×2 block of identical objects |
| Frequency | one sprite has 8+ copies covering over 65% of the objects' area |
| Monoculture | one object type covers over 65% of occupied tiles |
| Few types | fewer than 3 object types |
| Animation | fewer than 2 animated objects and fewer than 4 water/lava tiles |
| Pan / overlap | the pan would leave the map, or the view overlaps an already chosen view of the same map |

To recalibrate: `uv run python -m h2live.calibrate <out-dir>` renders a contact sheet of views either side of each threshold.

## Tests

```sh
cd ios-livephoto && uv run pytest
```

Engine tests skip unless `./fheroes2` is built.
