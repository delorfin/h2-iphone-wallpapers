# HoMM2 map wallpapers for iPhone

Renders random views of Heroes of Might and Magic II adventure maps on the Mac and turns them into Live Photos that the iPhone lock screen plays as moving wallpapers. The phone uses only built-in apps: a synced Photos album and a daily Shortcuts automation. iOS has no live wallpaper API for third-party apps, so this is the closest equivalent; see [docs/findings.md](docs/findings.md) for why it works the way it does.

What you get: every morning a new wallpaper on the lock and home screen. On wake, the lock screen plays about 1.7 s of map animation (units, flags, water, a slow pan), then settles on the still.

## Requirements

- macOS with Photos, Homebrew and [uv](https://docs.astral.sh/uv/).
- `brew install sdl2 sdl2_mixer ffmpeg gpac exiftool imagemagick libheif`
- HoMM2 game data in `~/Library/Application Support/fheroes2` (`DATA`, `MAPS`).
- An iPhone. Finder photo sync, the verified way to deliver them, needs iCloud Photos off; see below for other ways.

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

This scouts the maps, picks views that pass the selection rules, renders them, builds Live Photos and imports them into the Photos album. Options: `--scale` (2-4, default 3), `--brightness` (default 70), `--no-import` (build the files, skip Photos), `--reuse` (see below). A batch of 365 takes a while; each wallpaper is about 3.5 MB.

- **No repeats across batches.** Every batch appends its views to `~/Library/Application Support/h2live/used-views.txt`, and later batches skip anything overlapping them. `--reuse` ignores the history. When too few unused views are left, the batch stops and says how many it found.
- **Adding or removing maps** in `~/Library/Application Support/fheroes2/maps` is picked up by the next batch: the scout cache (`~/Library/Caches/h2live`) remembers each map file by size and date, scouts only new or changed ones and drops removed ones. Maps the engine can't load are remembered and skipped. Rebuilding the renderer rescouts everything.
- **Clean-up.** After a successful import the output folder keeps only `views.txt`; Photos stores its own copy of every file in `~/Pictures/Photos Library.photoslibrary`. With `--no-import` the finished Live Photos stay in `live/`. If a step fails, all intermediate stages stay for diagnosis.

## Get them onto the iPhone

The wallpapers must arrive in the iPhone's Photos app as Live Photos with their metadata intact.

| Path | Suits | Status |
|---|---|---|
| Finder photo sync | iCloud Photos off; the album updates on the phone when you sync | Verified |
| AirDrop from the Photos app on the Mac | Anyone; one-off batches | Verified (from Finder it sends two separate files) |
| iCloud Photos | iCloud Photos on; the album syncs by itself | Untested: whether the wallpaper metadata survives iCloud is unknown |

Finder photo sync, one-time setup:

1. Connect the iPhone by cable, unlock it, trust the Mac.
2. Finder → iPhone → General: tick "Show this iPhone when on Wi-Fi".
3. Photos tab: tick "Sync photos to your device from: Photos", choose "Selected albums", tick **H2**, keep "Include videos" ticked. Apply.

After that, a sync starts when you select the iPhone in Finder's sidebar (cable, or Wi-Fi while the phone is awake or charging). The album appears on the phone read-only. Synced photos keep their Live Photo motion, don't count against iCloud storage, and aren't picked up by Google Photos. Keep the album in Photos on the Mac: sync mirrors it, so photos removed there disappear from the phone at the next sync.

With AirDrop or iCloud Photos the wallpapers land in the camera roll, where backup apps such as Google Photos pick them up. They're all dated 1 January 1996, which keeps them out of the recent timeline and makes them easy to find and delete in one go.

## Rotate them on the iPhone

The shortcut, "H2 wallpaper": **Find Photos** (Album is H2) → **Get Item from List** (Random Item) → **Set Wallpaper Photo** (Lock Screen and Home Screen; expand the action with › and turn **Show Preview off**, or automations report success and change nothing).

Ways to run it:

- **Daily:** Automation → Time of Day (e.g. 05:00, Daily, Run Immediately, Notify When Run off). Time of Day also offers weekly and monthly.
- **On an event:** Automation triggers such as connecting the charger, an alarm going off or a Focus turning on.
- **By hand:** add the shortcut to the Home Screen or as a widget.
- **Lock screen only:** choose Lock Screen instead of both in Set Wallpaper Photo; only the lock screen plays the motion anyway.
- **No automation at all:** pick a wallpaper in Settings → Wallpaper → Add New → Photos, with the Live Photo button on.

On iOS 18, Set Wallpaper Photo fails on about every other run ("NSXPC connection type unavailable for com.apple.PhotosUIPrivate.PhotosPosterProvider"). Shortcuts has no retry, so add a second automation a minute after the first.

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
