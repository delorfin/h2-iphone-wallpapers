# Findings

What had to be true for the wallpapers to work, how it was established, and what didn't work. All device results are from an iPhone 12 Pro on iOS 18.7.2 (September 2026). Apple documents none of this; expect a future iOS to move the goalposts.

## Live Photo wallpaper format

iOS only plays motion for Live Photos that pass an undocumented check; failures show "Motion not available" or a struck-through Live button.

| Requirement | Evidence |
|---|---|
| Video 1080×1920 (9:16) | 1080×2340 rejected; iOS crops the sides to the screen (~96 px each side on this phone) |
| Exactly 60 fps, evenly spaced, 1 s | Variable frame timing rejected; 120 fps can't be delivered (macOS Photos won't pair it) |
| Timed metadata copied from a real camera Live Photo | goLive's method ([code-path/goLive](https://github.com/code-path/goLive), Apache-2.0, `base/`). Hand-built metadata (makelive, own AVAssetWriter, Video2LivePhoto's template) was rejected |
| goLive's base video track can be dropped | Keeps tracks 2-3 of `base.mov` only; ~3 MB smaller per wallpaper |
| iPhone camera colour format | Video: P3 primaries, BT.709 transfer, BT.601 matrix, full range. Still: the video's own frame at 0.5 s, Display P3 ICC, EXIF ColorSpace Uncalibrated. Anything else (untagged BT.601, BT.709, sRGB- or P3-converted stills) flashed greens when the lock screen settled |
| Still = video frame 30 | A different still makes a visible jump at the settle |

## How the lock screen plays it

Measured by recording the phone's screen over USB (QuickTime → New Movie Recording → iPhone as camera) while waking it, with a 60-cell frame-index strip in the video. Deterministic across wakes:

- Only video frames 17-30 play, over ~1.7 s, easing out: frame f dominates at 17: 0, 18: .067, 19: .134, 20: .201, 21: .268, 22: .368, 23: .469, 24: .569, 25: .669, 26: .787, 27: .954, 28: 1.121, 29: 1.356, 30: 1.657 s.
- Between frames iOS shows a linear crossfade, so a change can't be sharper than the gap it falls in (67 ms early, up to 300 ms late).
- iOS also zooms the wallpaper slightly during the first ~0.6 s.

Consequences built into `h2live/clip.py`: 8 game poses per view; each animated object gets its own random phase (so changes spread out instead of the whole picture crossfading at once); poses change every 250 ms of on-screen time using the table above; objects that change over 1000 px per step (windmills, whirlpools) change only in the fast early gaps and then hold, because late crossfades show them as double exposures. Water, lava and glints animate by palette cycling (`PAL::GetCyclingPalette`), which the renderer bakes into each frame; the clip treats cycling pixels as shimmer, never as a big jump. A diagonal/horizontal pan of one map pixel per video frame stays smooth.

Things tried and rejected for animation: even 15-60 steps/s (a "slide show of frames fading into each other"), pre-blended crossfades, 2 ms cut pairs (VFR, rejected), 120 fps (undeliverable), and using the settle-to-still swap as a cut (it's itself a quick blend).

## Delivery to the phone

| Path | Result |
|---|---|
| AppleScript import into Mac Photos | Pairs the still and video into a Live Photo. PhotoKit from Terminal is denied by TCC |
| AirDrop from Mac Photos | Works; from Finder it sends two separate files |
| Finder photo sync (iCloud Photos off) | Works and keeps motion; synced photos aren't backed up by Google Photos |
| iCloud Photos | Library too big for the free 5 GB |
| iCloud shared album | Reported to break wallpaper compatibility |
| Shortcuts saving files into Photos | No action pairs a still and video into a Live Photo |

Phone → Mac AirDrop of a Live Photo needs Options → All Photos Data, or only the still arrives.

## Engine gotchas

- `make` overwrites `./fheroes2` in place and macOS kills it on launch (stale code signature); `build.sh` copies a fresh file.
- The Makefile never defines `NDEBUG`; some shipped maps (e.g. "Easy Walk.mp2") trip loader assertions and abort. `build.sh` builds with `-DNDEBUG`.
- Non-bundle macOS builds look for data in `~/.fheroes2`; the tool sets `FHEROES2_DATA`.
- The repo's `files/data/resurrection.h2d` is found next to the binary, so the renderer must run from the repo root copy.
- Random castle races are chosen in `SetStartGame()`, so the per-map seed must be set before it.
- Engine state carries over between map loads in one process, changing random artifacts and resources. The tool scouts and renders every map in its own process so the rendered view matches the scouted one.
- On error dialogs (e.g. a missing resource) the engine blocks forever; test runs need timeouts.

## Shortcuts gotchas

- Set Wallpaper Photo's "Show Preview" hides under the action's › arrow and must be off for automations.
- Time of Day automations run daily at most; there's no "every N minutes".
- Finder photo sync failed with error -50 until the "iPod Photo Cache" folder inside the Photos library was cleared and the sync agents (AMPDevicesAgent, AMPDeviceDiscoveryAgent) restarted.
- Finder Wi-Fi sync only holds while the phone is awake or charging; a locked phone drops out of Finder mid-sync. Sync starts when the phone is selected in Finder's sidebar.

## Future paths

- **Replacing the album instead of growing it.** Photos' AppleScript can add to albums and delete albums, but not remove photos from an album, and recreating the album would lose Finder's sync selection. Planned approach: tag the current batch with a keyword (writable via AppleScript), sync a smart album "keyword is h2-current", and move the keyword to each new batch. Open question: whether Finder lets you pick a smart album for sync.
- **Scheduled generation.** A launchd job running the batch monthly, then the sync on the next Finder visit or charging session. Finder sync itself can't be triggered by a script (UI scripting is possible but fragile).
- **Smoother big objects.** Hand-made or RotSprite in-between frames for windmills, so they turn instead of holding.
- **Deferred review minors:** scout cache written non-atomically and not invalidated when maps change; some failures end in raw tracebacks with partial folders; pan direction and view choice unseeded.
