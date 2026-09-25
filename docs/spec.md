# HoMM2 map wallpapers for iPhone

iOS has no live wallpaper API for third-party apps. The closest equivalent is a Live Photo on the lock screen, which plays about a second of motion each time the phone wakes, and a daily Shortcuts automation that swaps the wallpaper. This folder turns h2lwp's wallpaper engine into a Mac tool that produces those Live Photos.

## What the user gets

- Every morning, a new random piece of a random HoMM2 map on the lock and home screen.
- On wake, the lock screen plays one second of map animation (water, flags, mills).
- The phone runs no custom code: only the built-in Photos and Shortcuts apps.

## How it works

1. **Render (Mac):** `fheroes2 --render-wallpapers <dir> <count> <scale> <frames>` picks a random map and a random spot per wallpaper, as the Android wallpaper does, and saves `<frames>` consecutive animation steps as BMP files at `1080/scale × 1920/scale`.
2. **Pack (Mac):** a Python tool upscales the frames (nearest neighbour) to 1080×1920, dims them, encodes a 1-second 60 fps HEVC clip, and turns it into a Live Photo with goLive's method: the clip is grafted onto a real camera Live Photo's metadata tracks and tags.
3. **Import (Mac):** the pairs go into a Photos album `H2 <date>` through AppleScript. Photos pairs them as Live Photos.
4. **Transfer (manual, about every two months):** the user AirDrops the album from Photos on the Mac and adds the items to the `H2` album on the iPhone.
5. **Rotate (iPhone):** a Shortcuts automation at 05:00 daily runs Find Photos (album `H2`) → Get Random Item → Set Wallpaper Photo (lock and home, Show Preview off).

## Constraints proven on the user's iPhone 12 Pro, iOS 18.7.2

| Constraint | Evidence |
|---|---|
| The Live Photo video must be 1080×1920 | Same pipeline at 1080×2340: Live button struck through |
| Metadata must come from a real camera Live Photo (goLive method) | Hand-built pairs (makelive, own AVAssetWriter, Video2LivePhoto template) were rejected |
| Photos pairs files only when imported through the Photos app | AirDrop from Finder delivers two separate items |
| Set Wallpaper Photo needs Show Preview off | With it on, the automation reports success and changes nothing |
| Set Wallpaper Photo keeps Live Photo motion | Tested with the red "1" test photo |

## Settings

| Setting | Value | Reason |
|---|---|---|
| Scale | 3 (2–4 allowed) | About 9 tiles visible across after iOS crops the sides |
| Animation | 8 steps per second (2× game speed) | The game advances every 250 ms, too slow for a 1 s clip |
| Brightness | 70% | Clock and icon legibility |
| Batch | 60 wallpapers | About two months of daily changes |
| Capture date | 1996-01-01, one minute apart | Keeps batches out of the recent timeline in Photos and Google Photos |

## Out of scope

On-device rendering, App Store distribution, panning on home screen swipes, continuous animation. iOS doesn't allow any of these for a free, non-jailbroken personal setup.
