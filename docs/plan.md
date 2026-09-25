# iPhone Live Photo Wallpapers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Mac command that renders a batch of random HoMM2 map views and imports them into Photos as Live Photos that iOS accepts as animated lock screen wallpapers.

**Architecture:** The h2lwp engine gets a `--render-wallpapers` mode that writes BMP animation frames per random map view. A Python package in `ios-livephoto/` upscales and encodes each view to a 1-second clip, grafts it onto a real camera Live Photo's metadata (goLive's method), and imports the pairs into a Photos album through AppleScript. The iPhone side is a Shortcuts automation, set up by hand.

**Tech Stack:** C++17 (fheroes2 engine, SDL2, Make), Python 3.12 via `uv`, pytest, ffmpeg (libx265), GPAC `MP4Box`, `exiftool`, ImageMagick with libheif, AppleScript (`osascript`).

**Spec:** `ios-livephoto/docs/spec.md`

## Global Constraints

- Live Photo video: exactly 1080×1920, 60 fps, HEVC tagged `hvc1`, 60 frames (1.0 s).
- Metadata method: goLive (github.com/code-path/goLive, Apache-2.0), base files `base.HEIC` + `base.mov` copied unmodified into `ios-livephoto/base/` with its license.
- Renderer scale: 2, 3 or 4 only; default 3. Frame size = `1080/scale × 1920/scale`.
- Animation: 8 frames per view, shown at 8 per second (2× the game's 250 ms step).
- Brightness default 70 (percent of full).
- Batch default 60. Capture dates 1996-01-01 00:00 plus one minute per item.
- Album name default `H2 <YYYY-MM-DD>` (today).
- Game data comes from `~/Library/Application Support/fheroes2`; never commit or copy it.
- No git push, no GitHub actions of any kind. Commit messages carry no AI attribution lines.
- All Python tests run with `cd ios-livephoto && uv run pytest`.

## Review Focus

- Two batches rendered on different days show the same maps: expected different maps each run. Pinned by `test_two_runs_pick_different_maps` (Task 2).
- A random view lands on open grass with nothing animated: expected the renderer rerolls the position, so every view moves. Pinned by the per-view animation assertion (Task 2).
- Scale 1 or 5 passed by mistake: expected a clear error and no partial output. Pinned by `test_rejects_scale_outside_2_to_4` (Task 2).
- Rerunning a batch into an existing folder: expected a refusal, not mixed old and new files. Pinned by `test_refuses_non_empty_output_dir` (Task 6).
- Importing 120 files takes longer than AppleScript's default 2-minute timeout, or Photos imports fewer items than expected: expected a long timeout and an error naming the album on a count mismatch. Pinned by `test_photos.py` (Task 5).

---

### Task 1: Build the fork on macOS

**Files:**
- Modify: `src/fheroes2/game/game_wallpaper.cpp:361` (the `SDL_AndroidSendMessage` call)
- Modify: `.gitignore`

**Interfaces:**
- Produces: `./fheroes2` binary in the repo root after `make -j8`.

- [ ] **Step 1: Confirm the build fails**

Run: `make -j8 2>&1 | grep error`
Expected: `game_wallpaper.cpp:361:17: error: use of undeclared identifier 'SDL_AndroidSendMessage'`

- [ ] **Step 2: Guard the Android-only call**

In `renderWallpaper()`, replace

```cpp
                SDL_AndroidSendMessage( COMMAND_PAUSE_NOW, 0 );
```

with

```cpp
#if defined( __ANDROID__ )
                SDL_AndroidSendMessage( COMMAND_PAUSE_NOW, 0 );
#endif
```

- [ ] **Step 3: Build**

Run: `make -j8`
Expected: exit 0 and a `fheroes2` executable in the repo root.

- [ ] **Step 4: Smoke-run the existing wallpaper mode**

Run: `./fheroes2 &` then close it after a few seconds with `pkill -x fheroes2`.
Expected: a window shows an animated map from the game data in `~/Library/Application Support/fheroes2`. If the window reports missing resources, stop and report which paths fheroes2 searched (it logs them).

- [ ] **Step 5: Ignore the binary**

Append to `.gitignore`:

```
# Desktop build output
/fheroes2
```

Run: `git status --short`
Expected: only `.gitignore` and `game_wallpaper.cpp` modified, no build artifacts listed.

- [ ] **Step 6: Commit**

```bash
git add ".gitignore" "src/fheroes2/game/game_wallpaper.cpp"
git commit -m "Build the wallpaper engine on macOS"
```

---

### Task 2: `--render-wallpapers` mode

**Files:**
- Modify: `src/fheroes2/game/game.h` (declaration next to `Wallpaper()`)
- Modify: `src/fheroes2/game/game_wallpaper.cpp` (`loadRandomMap` returns `bool`; new functions)
- Modify: `src/fheroes2/game/fheroes2.cpp` (argument check before `Game::Wallpaper();`)
- Create: `ios-livephoto/pyproject.toml`, `ios-livephoto/h2live/__init__.py`, `ios-livephoto/tests/test_render.py`

**Interfaces:**
- Produces: `fheroes2 --render-wallpapers <outDir> <count> <scale> <frames>`, exit 0 on success. Writes `<outDir>/000/`, `001/`, …, each with `f00.bmp` … `f{frames-1:02d}.bmp` at `1080/scale × 1920/scale`, and `map.txt` containing the map file path. Exits non-zero without creating `<outDir>` when arguments are invalid.

- [ ] **Step 1: Create the Python project**

`ios-livephoto/pyproject.toml`:

```toml
[project]
name = "h2live"
version = "0.1.0"
description = "Turns h2lwp map renders into iPhone Live Photo wallpapers"
requires-python = ">=3.12"

[project.scripts]
h2live = "h2live.batch:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

`ios-livephoto/h2live/__init__.py`: empty file.

- [ ] **Step 2: Write the failing tests**

`ios-livephoto/tests/test_render.py`:

```python
import struct
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RENDERER = REPO / "fheroes2"

pytestmark = pytest.mark.skipif(not RENDERER.exists(), reason="build the fork first: make -j8 in the repo root")


def bmp_size(path: Path) -> tuple[int, int]:
    width, height = struct.unpack("<ii", path.read_bytes()[18:26])
    return width, abs(height)


def render(out: Path, count: int, scale: int, frames: int = 8) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(RENDERER), "--render-wallpapers", str(out), str(count), str(scale), str(frames)],
        capture_output=True, text=True, timeout=600,
    )


def test_renders_count_views_of_frames_each(tmp_path):
    result = render(tmp_path, 2, 3)
    assert result.returncode == 0, result.stderr
    views = sorted(p for p in tmp_path.iterdir() if p.is_dir())
    assert [v.name for v in views] == ["000", "001"]
    for view in views:
        frames = sorted(view.glob("f*.bmp"))
        assert len(frames) == 8
        assert {bmp_size(f) for f in frames} == {(360, 640)}
        assert len({f.read_bytes() for f in frames}) > 1, f"{view} has no animation"
        assert (view / "map.txt").read_text().strip()


def test_two_runs_pick_different_maps(tmp_path):
    maps = []
    for run in ("a", "b"):
        assert render(tmp_path / run, 3, 3, frames=1).returncode == 0
        maps.append(sorted((tmp_path / run / d / "map.txt").read_text() for d in ("000", "001", "002")))
    assert maps[0] != maps[1]


@pytest.mark.parametrize("scale", [1, 5])
def test_rejects_scale_outside_2_to_4(tmp_path, scale):
    assert render(tmp_path / "out", 1, scale).returncode != 0
    assert not (tmp_path / "out").exists()
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd ios-livephoto && uv run pytest tests/test_render.py -v`
Expected: FAIL. The binary ignores the arguments and opens the normal wallpaper window, so the calls time out or return without output. Kill any leftover window with `pkill -x fheroes2`.

- [ ] **Step 4: Make `loadRandomMap` report failure**

In `game_wallpaper.cpp`, change `void loadRandomMap()` to `bool loadRandomMap()`:
- `return false;` after the existing `LWP map load SKIPPED` log.
- Replace `world.LoadMapMP2( nextMap.filename, false );` with:

```cpp
        if ( !world.LoadMapMP2( nextMap.filename, false ) ) {
            VERBOSE_LOG( "LWP map load FAILED file=" << nextMap.filename.c_str() )
            return false;
        }
```

- `return true;` after the `LWP map load FINISH` log.

The existing callers ignore the result; leave them as they are.

- [ ] **Step 5: Add the render mode**

In `game_wallpaper.cpp`, add includes `<cstdio>`, `<cstdlib>`, `<fstream>` and `"image.h"`, `"image_tool.h"`. Inside the anonymous namespace, after `randomizeGameArea()`, add:

```cpp
    constexpr Interface::RedrawLevelType mapLevels = Interface::RedrawLevelType::LEVEL_OBJECTS | Interface::RedrawLevelType::LEVEL_HEROES;

    // A view with nothing animated (open grass) would make a Live Photo without motion.
    bool viewHasAnimation( const Interface::GameArea & gameArea, fheroes2::Display & display )
    {
        gameArea.Redraw( display, mapLevels );
        fheroes2::Image before( display.width(), display.height() );
        fheroes2::Copy( display, before );

        for ( int step = 0; step < 4; ++step ) {
            Game::updateAdventureMapAnimationIndex();
        }
        gameArea.Redraw( display, mapLevels );

        const size_t size = static_cast<size_t>( display.width() ) * display.height();
        return !std::equal( before.image(), before.image() + size, display.image() );
    }
```

If `RedrawLevelType` flags cannot be combined in a `constexpr` (compile error), make `mapLevels` a plain `const` local in each function instead.

After `Game::Wallpaper()` at the end of the file, add:

```cpp
int Game::RenderWallpapers( const std::string & outDir, const int count, const int scale, const int frames )
{
    // iOS only accepts 1080x1920 Live Photos as wallpapers; the packer upscales each frame by `scale`.
    constexpr int32_t outputWidth = 1080;
    constexpr int32_t outputHeight = 1920;
    constexpr int maxMapAttempts = 5;
    constexpr int maxViewAttempts = 10;

    // Scale 1 would make the view taller than the smallest (36x36) maps.
    if ( count < 1 || scale < 2 || scale > 4 || frames < 1 ) {
        ERROR_LOG( "Usage: --render-wallpapers <dir> <count >= 1> <scale 2-4> <frames >= 1>" )
        return EXIT_FAILURE;
    }

    const int32_t width = outputWidth / scale;
    const int32_t height = outputHeight / scale;
    fheroes2::Display & display = fheroes2::Display::instance();
    display.setResolution( { width, height, width, height } );
    const Interface::GameArea & gameArea = Interface::AdventureMap::Get().getGameArea();

    for ( int i = 0; i < count; ++i ) {
        for ( int attempt = 1; !loadRandomMap(); ++attempt ) {
            if ( attempt >= maxMapAttempts ) {
                ERROR_LOG( "Could not load a map after " << maxMapAttempts << " attempts" )
                return EXIT_FAILURE;
            }
        }

        randomizeGameArea();
        for ( int attempt = 1; attempt < maxViewAttempts && !viewHasAnimation( gameArea, display ); ++attempt ) {
            randomizeGameArea();
        }

        char name[16];
        std::snprintf( name, sizeof( name ), "%03d", i );
        const std::string dir = System::concatPath( outDir, name );
        std::filesystem::create_directories( dir );

        for ( int frame = 0; frame < frames; ++frame ) {
            Game::updateAdventureMapAnimationIndex();
            gameArea.Redraw( display, mapLevels );
            std::snprintf( name, sizeof( name ), "f%02d.bmp", frame );
            const std::string path = System::concatPath( dir, name );
            if ( !fheroes2::Save( display, path ) ) {
                ERROR_LOG( "Could not save " << path )
                return EXIT_FAILURE;
            }
        }

        std::ofstream( System::concatPath( dir, "map.txt" ) ) << Settings::Get().getCurrentMapInfo().filename << '\n';
    }

    return EXIT_SUCCESS;
}
```

In `game.h`, after `fheroes2::GameMode Wallpaper();`, add:

```cpp
    // Saves `count` random map views, `frames` animation steps each, as BMP files for the iPhone Live Photo packer.
    int RenderWallpapers( const std::string & outDir, const int count, const int scale, const int frames );
```

- [ ] **Step 6: Route the argument in `main`**

In `fheroes2.cpp`, add `<cstdlib>` and `<string_view>` includes if missing, and directly before `Game::Wallpaper();` add:

```cpp
            if ( argc == 6 && std::string_view( argv[1] ) == "--render-wallpapers" ) {
                return Game::RenderWallpapers( argv[2], std::atoi( argv[3] ), std::atoi( argv[4] ), std::atoi( argv[5] ) );
            }
```

`std::atoi` returns 0 for non-numbers, which the range check rejects.

- [ ] **Step 7: Build and run the tests**

Run: `make -j8 && cd ios-livephoto && uv run pytest tests/test_render.py -v`
Expected: 4 passed.

- [ ] **Step 8: Look at a frame**

Run: `open` one `f00.bmp` from a fresh render (`./fheroes2 --render-wallpapers /tmp/h2check 1 3 8`).
Expected: a recognizable HoMM2 map with correct colors, no interface, no black borders. Wrong colors mean `Save()` didn't apply the game palette; stop and report.

- [ ] **Step 9: Commit**

```bash
git add "src/fheroes2/game/game.h" "src/fheroes2/game/game_wallpaper.cpp" "src/fheroes2/game/fheroes2.cpp" "ios-livephoto/pyproject.toml" "ios-livephoto/h2live/__init__.py" "ios-livephoto/tests/test_render.py" "ios-livephoto/uv.lock"
git commit -m "Add --render-wallpapers mode for iPhone Live Photos"
```

---

### Task 3: Frames to clip

**Files:**
- Create: `ios-livephoto/h2live/clip.py`
- Create: `ios-livephoto/tests/conftest.py`, `ios-livephoto/tests/test_clip.py`

**Interfaces:**
- Consumes: a view folder from Task 2 (`f00.bmp` … `f07.bmp`, any of the three sizes).
- Produces: `make_clip(frames_dir: Path, out: Path, brightness: int, steps_per_second: int = 8) -> None`, writing a 1080×1920, 60 fps, 60-frame HEVC `.mov`. Raises `ValueError` on a wrong frame count or brightness outside 1–100. Test helpers `probe(path) -> dict` and `mean_luma(path) -> float` in `conftest.py`; fixture `frames_dir`.

- [ ] **Step 1: Write the fixtures and failing tests**

`ios-livephoto/tests/conftest.py`:

```python
import json
import subprocess
from pathlib import Path

import pytest


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def mean_luma(path: Path) -> float:
    gray = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True, capture_output=True,
    ).stdout
    return sum(gray) / len(gray)


@pytest.fixture
def frames_dir(tmp_path: Path) -> Path:
    """Eight 360x640 frames shaped like one renderer view (scale 3)."""
    view = tmp_path / "000"
    view.mkdir()
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=360x640:r=8", "-frames:v", "8",
         "-start_number", "0", str(view / "f%02d.bmp")],
        check=True,
    )
    return view
```

`ios-livephoto/tests/test_clip.py`:

```python
import pytest

from conftest import mean_luma, probe
from h2live.clip import make_clip


def test_clip_is_one_second_1080x1920_hevc_at_60fps(frames_dir, tmp_path):
    out = tmp_path / "clip.mov"
    make_clip(frames_dir, out, brightness=70)
    video = probe(out)["streams"][0]
    assert (video["width"], video["height"]) == (1080, 1920)
    assert video["codec_tag_string"] == "hvc1"
    assert video["r_frame_rate"] == "60/1"
    assert int(video["nb_frames"]) == 60


def test_brightness_dims_the_picture(frames_dir, tmp_path):
    make_clip(frames_dir, tmp_path / "full.mov", brightness=100)
    make_clip(frames_dir, tmp_path / "half.mov", brightness=50)
    ratio = mean_luma(tmp_path / "half.mov") / mean_luma(tmp_path / "full.mov")
    # Video luma has a black-level offset, so 50% brightness lands near, not exactly at, half.
    assert 0.35 < ratio < 0.65


def test_rejects_wrong_frame_count(frames_dir, tmp_path):
    (frames_dir / "f07.bmp").unlink()
    with pytest.raises(ValueError, match="expected 8 frames"):
        make_clip(frames_dir, tmp_path / "clip.mov", brightness=70)


@pytest.mark.parametrize("brightness", [0, 101])
def test_rejects_brightness_out_of_range(frames_dir, tmp_path, brightness):
    with pytest.raises(ValueError, match="brightness"):
        make_clip(frames_dir, tmp_path / "clip.mov", brightness=brightness)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd ios-livephoto && uv run pytest tests/test_clip.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'h2live.clip'`

- [ ] **Step 3: Implement**

`ios-livephoto/h2live/clip.py`:

```python
"""Turns one rendered map view into the 1-second clip a Live Photo wallpaper plays."""

import subprocess
from pathlib import Path

# iOS rejects Live Photo wallpapers in any other size.
WIDTH, HEIGHT = 1080, 1920
OUTPUT_FPS = 60


def make_clip(frames_dir: Path, out: Path, brightness: int, steps_per_second: int = 8) -> None:
    if not 1 <= brightness <= 100:
        raise ValueError(f"brightness must be 1-100, got {brightness}")
    frames = sorted(frames_dir.glob("f*.bmp"))
    if len(frames) != steps_per_second:
        raise ValueError(f"expected {steps_per_second} frames in {frames_dir}, found {len(frames)}")

    level = brightness / 100
    # Nearest-neighbour keeps the pixel art sharp; every renderer size divides 1080x1920 exactly.
    video_filter = (
        f"scale={WIDTH}:{HEIGHT}:flags=neighbor,"
        f"colorchannelmixer=rr={level}:gg={level}:bb={level},"
        "format=yuv420p"
    )
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-framerate", str(steps_per_second), "-i", str(frames_dir / "f%02d.bmp"),
         "-vf", video_filter, "-r", str(OUTPUT_FPS), "-frames:v", str(OUTPUT_FPS),
         "-c:v", "libx265", "-crf", "20", "-tag:v", "hvc1", "-x265-params", "log-level=error",
         str(out)],
        check=True,
    )
```

- [ ] **Step 4: Run the tests**

Run: `cd ios-livephoto && uv run pytest tests/test_clip.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add "ios-livephoto/h2live/clip.py" "ios-livephoto/tests/conftest.py" "ios-livephoto/tests/test_clip.py"
git commit -m "Encode rendered map frames into Live Photo clips"
```

---

### Task 4: Clip to wallpaper-compatible Live Photo

**Files:**
- Create: `ios-livephoto/base/base.HEIC`, `ios-livephoto/base/base.mov`, `ios-livephoto/base/LICENSE`, `ios-livephoto/base/NOTICE.md`
- Create: `ios-livephoto/h2live/livephoto.py`
- Create: `ios-livephoto/tests/test_livephoto.py`

**Interfaces:**
- Consumes: `make_clip` (Task 3), `probe` and `frames_dir` from `conftest.py`.
- Produces: `make_live_photo(clip: Path, out_dir: Path, name: str, captured: datetime, base_dir: Path = BASE_DIR) -> tuple[Path, Path]` returning `(heic, mov)` paths named `<name>.HEIC` and `<name>.mov`.

- [ ] **Step 1: Copy the base Live Photo and its license**

```bash
mkdir -p ios-livephoto/base
cp ~/Downloads/h2lwp-livephoto-test/goLive/base/base.HEIC ~/Downloads/h2lwp-livephoto-test/goLive/base/base.mov ios-livephoto/base/
cp ~/Downloads/h2lwp-livephoto-test/goLive/LICENSE ios-livephoto/base/LICENSE
```

If `~/Downloads/h2lwp-livephoto-test/goLive` is gone, clone `https://github.com/code-path/goLive` and copy from there.

`ios-livephoto/base/NOTICE.md`:

```markdown
`base.HEIC` and `base.mov` come from goLive (https://github.com/code-path/goLive), Apache License 2.0 (see LICENSE). They are a camera Live Photo whose metadata makes iOS accept generated clips as lock screen wallpapers.
```

- [ ] **Step 2: Write the failing tests**

`ios-livephoto/tests/test_livephoto.py`:

```python
import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from conftest import probe
from h2live.clip import make_clip
from h2live.livephoto import make_live_photo


def tags(path: Path) -> dict:
    out = subprocess.run(["exiftool", "-json", "-G", "-ee3", str(path)], check=True, capture_output=True, text=True).stdout
    return json.loads(out)[0]


@pytest.fixture
def pair(frames_dir, tmp_path):
    clip = tmp_path / "clip.mov"
    make_clip(frames_dir, clip, brightness=70)
    out = tmp_path / "live"
    out.mkdir()
    return make_live_photo(clip, out, "H2_000", datetime(1996, 1, 1, 0, 5))


def test_files_are_named_after_the_item(pair):
    heic, mov = pair
    assert (heic.name, mov.name) == ("H2_000.HEIC", "H2_000.mov")


def test_still_and_video_share_one_content_identifier(pair):
    heic, mov = pair
    assert tags(heic)["MakerNotes:ContentIdentifier"] == tags(mov)["QuickTime:ContentIdentifier"]


def test_track_layout_matches_the_proven_golive_output(pair):
    _, mov = pair
    streams = probe(mov)["streams"]
    assert [s["codec_type"] for s in streams] == ["video", "video", "data", "data"]
    clip_track = streams[0]
    assert (clip_track["width"], clip_track["height"]) == (1080, 1920)
    assert clip_track["codec_tag_string"] == "hvc1"
    assert 0.95 <= float(clip_track["duration"]) <= 1.1


def test_still_is_1080x1920(pair):
    heic, _ = pair
    t = tags(heic)
    assert (t["File:ImageWidth"], t["File:ImageHeight"]) == (1080, 1920)


def test_capture_date_is_the_requested_one(pair):
    heic, mov = pair
    assert tags(heic)["EXIF:DateTimeOriginal"] == "1996:01:01 00:05:00"
    assert tags(mov)["QuickTime:CreateDate"].startswith("1996:01:01")


def test_no_location_is_written(pair):
    for path in pair:
        assert not [k for k in tags(path) if "GPS" in k or "Location" in k], path
```

The exact exiftool group names (`MakerNotes:ContentIdentifier`, `File:ImageWidth`) are what exiftool 13 prints for iPhone files. If one differs, run `exiftool -G -s <file>` on the output and adjust the key in the test, not the assertion.

- [ ] **Step 3: Run them to verify they fail**

Run: `cd ios-livephoto && uv run pytest tests/test_livephoto.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'h2live.livephoto'`

- [ ] **Step 4: Implement**

`ios-livephoto/h2live/livephoto.py`:

```python
"""Turns a clip into a Live Photo pair that iOS accepts as a lock screen wallpaper.

Follows goLive (https://github.com/code-path/goLive, Apache-2.0): the clip's video
track is muxed with every track of a real camera Live Photo (base/base.mov), and
the camera photo's tags are copied onto the new still and video. Hand-built
metadata gets rejected by the wallpaper picker.
"""

import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent / "base"


def _run(*args) -> bytes:
    return subprocess.run([str(a) for a in args], check=True, capture_output=True).stdout


def make_live_photo(clip: Path, out_dir: Path, name: str, captured: datetime, base_dir: Path = BASE_DIR) -> tuple[Path, Path]:
    base_mov, base_heic = base_dir / "base.mov", base_dir / "base.HEIC"
    heic, mov = out_dir / f"{name}.HEIC", out_dir / f"{name}.mov"
    content_id = str(uuid.uuid4()).upper()
    stamp = captured.strftime("%Y:%m:%d %H:%M:%S")

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        raw = tmp / "clip.hevc"
        _run("MP4Box", "-raw", "1", clip, "-out", raw)
        mov.unlink(missing_ok=True)
        _run("MP4Box", "-add", raw, "-add", base_mov, "-new", mov)

        still = tmp / "still.png"
        _run("ffmpeg", "-loglevel", "error", "-y", "-ss", "0.5", "-i", mov, "-map", "0:v:0", "-frames:v", "1", still)
        icc = tmp / "base.icc"
        icc.write_bytes(_run("exiftool", "-icc_profile", "-b", base_heic))
        profile = ["-profile", icc] if icc.stat().st_size else []
        _run("magick", still, "-depth", "10", "-quality", "100", "-define", "heic:lossless=true", *profile, heic)

    for target, source in ((mov, base_mov), (heic, base_heic)):
        _run("exiftool", "-ee3", "-TagsFromFile", source, "-all:all", target, "-overwrite_original", "-m", "-F")

    shared = [
        "-api", "QuickTimeUTC",
        f"-QuickTime:CreateDate={stamp}", f"-QuickTime:ModifyDate={stamp}",
        f"-QuickTime:TrackCreateDate={stamp}", f"-QuickTime:TrackModifyDate={stamp}",
        f"-QuickTime:MediaCreateDate={stamp}", f"-QuickTime:MediaModifyDate={stamp}",
        f"-SubSecCreateDate={stamp}.000",
        f"-QuickTime:ContentIdentifier={content_id}", f"-Apple:ContentIdentifier={content_id}",
        f"-Apple:ImageUniqueID={content_id}",
        "-gps:all=",
        "-overwrite_original", "-m",
    ]
    _run("exiftool", *shared,
         "-LivePhotoAuto=1", "-LivePhotoVitalityScore=1", "-LivePhotoVitalityScoringVersion=4",
         "-LivePhotoVideoIndex=1", mov)
    _run("exiftool", *shared, f"-AllDates={stamp}", "-LivePhotoVideoIndex=0", heic)
    return heic, mov
```

- [ ] **Step 5: Run the tests**

Run: `cd ios-livephoto && uv run pytest tests/test_livephoto.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add "ios-livephoto/base" "ios-livephoto/h2live/livephoto.py" "ios-livephoto/tests/test_livephoto.py"
git commit -m "Build wallpaper-compatible Live Photos with goLive's method"
```

---

### Task 5: Import into Photos

**Files:**
- Create: `ios-livephoto/h2live/photos.py`
- Create: `ios-livephoto/tests/test_photos.py`

**Interfaces:**
- Consumes: `(heic, mov)` pairs from Task 4.
- Produces: `import_pairs(pairs: list[tuple[Path, Path]], album: str, run=subprocess.run) -> int`, returning the number of Live Photos imported. Raises `RuntimeError` naming the album when Photos reports a different count.

- [ ] **Step 1: Write the failing tests**

`ios-livephoto/tests/test_photos.py`:

```python
import subprocess
from pathlib import Path

import pytest

from h2live.photos import import_pairs

PAIRS = [(Path("/x/H2_000.HEIC"), Path("/x/H2_000.mov")), (Path("/x/H2_001.HEIC"), Path("/x/H2_001.mov"))]


def fake_osascript(stdout: str, calls: list):
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")
    return run


def test_returns_imported_count_and_targets_album():
    calls = []
    assert import_pairs(PAIRS, "H2 2026-09-25", run=fake_osascript("2\n", calls)) == 2
    script = calls[0][-1]
    assert 'album "H2 2026-09-25"' in script
    assert 'POSIX file "/x/H2_001.mov"' in script


def test_allows_long_imports():
    calls = []
    import_pairs(PAIRS, "H2", run=fake_osascript("2\n", calls))
    assert "with timeout of 1800 seconds" in calls[0][-1]


def test_count_mismatch_names_the_album():
    with pytest.raises(RuntimeError, match="H2 test"):
        import_pairs(PAIRS, "H2 test", run=fake_osascript("4\n", []))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd ios-livephoto && uv run pytest tests/test_photos.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'h2live.photos'`

- [ ] **Step 3: Implement**

`ios-livephoto/h2live/photos.py`:

```python
"""Imports Live Photo pairs into a Photos album.

Goes through the Photos app with AppleScript: it pairs the still and video into
one Live Photo, and it doesn't need the Photos privacy permission that the
terminal lacks.
"""

import subprocess
from pathlib import Path


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def import_pairs(pairs: list[tuple[Path, Path]], album: str, run=subprocess.run) -> int:
    files = ", ".join(f"POSIX file {_quote(str(path))}" for pair in pairs for path in pair)
    # A batch of 60 pairs takes minutes; AppleScript's default timeout is 2 minutes.
    script = f"""with timeout of 1800 seconds
tell application "Photos"
set imported to import {{{files}}} skip check duplicates true
if not (exists album {_quote(album)}) then make new album named {_quote(album)}
add imported to album {_quote(album)}
return count of imported
end tell
end timeout"""
    result = run(["osascript", "-e", script], check=True, capture_output=True, text=True)
    imported = int(result.stdout.strip())
    if imported != len(pairs):
        raise RuntimeError(
            f"Photos imported {imported} items into album {album!r}, expected {len(pairs)} Live Photos; "
            "some pairs were not recognised as Live Photos"
        )
    return imported
```

- [ ] **Step 4: Run the tests**

Run: `cd ios-livephoto && uv run pytest tests/test_photos.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add "ios-livephoto/h2live/photos.py" "ios-livephoto/tests/test_photos.py"
git commit -m "Import Live Photo pairs into a Photos album"
```

---

### Task 6: `h2live batch` command

**Files:**
- Create: `ios-livephoto/h2live/batch.py`
- Create: `ios-livephoto/tests/test_batch.py`, `ios-livephoto/tests/fake_renderer.py`

**Interfaces:**
- Consumes: the renderer CLI (Task 2), `make_clip` (Task 3), `make_live_photo` (Task 4), `import_pairs` (Task 5).
- Produces: `h2live batch --out DIR [--count 60] [--scale 3] [--brightness 70] [--album NAME] [--no-import] [--renderer PATH]` and `main(argv: list[str] | None = None) -> int`. Output layout: `DIR/frames/NNN/`, `DIR/clips/NNN.mov`, `DIR/live/H2_NNN.HEIC|mov`.

- [ ] **Step 1: Write the fake renderer and the failing tests**

`ios-livephoto/tests/fake_renderer.py`:

```python
"""Stands in for `fheroes2 --render-wallpapers` so batch tests don't need game data."""

import subprocess
import sys
from pathlib import Path

_, flag, out, count, scale, frames = sys.argv
assert flag == "--render-wallpapers"
size = f"{1080 // int(scale)}x{1920 // int(scale)}"
for i in range(int(count)):
    view = Path(out) / f"{i:03d}"
    view.mkdir(parents=True)
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=8", "-frames:v", frames,
         "-start_number", "0", str(view / "f%02d.bmp")],
        check=True,
    )
    (view / "map.txt").write_text("fake.mp2\n")
```

`ios-livephoto/tests/test_batch.py`:

```python
import sys
from pathlib import Path

from h2live.batch import main

FAKE = Path(__file__).with_name("fake_renderer.py")


def fake_renderer(tmp_path: Path) -> str:
    wrapper = tmp_path / "renderer"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
    wrapper.chmod(0o755)
    return str(wrapper)


def test_builds_one_pair_per_view_without_importing(tmp_path):
    out = tmp_path / "batch"
    code = main(["--out", str(out), "--count", "2", "--no-import", "--renderer", fake_renderer(tmp_path)])
    assert code == 0
    assert sorted(p.name for p in (out / "live").iterdir()) == ["H2_000.HEIC", "H2_000.mov", "H2_001.HEIC", "H2_001.mov"]


def test_refuses_non_empty_output_dir(tmp_path):
    out = tmp_path / "batch"
    out.mkdir()
    (out / "old.txt").write_text("previous batch")
    assert main(["--out", str(out), "--count", "1", "--no-import", "--renderer", fake_renderer(tmp_path)]) != 0
    assert sorted(p.name for p in out.iterdir()) == ["old.txt"]


def test_renderer_failure_stops_the_batch(tmp_path):
    failing = tmp_path / "renderer"
    failing.write_text("#!/bin/sh\nexit 3\n")
    failing.chmod(0o755)
    assert main(["--out", str(tmp_path / "batch"), "--count", "1", "--no-import", "--renderer", str(failing)]) != 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd ios-livephoto && uv run pytest tests/test_batch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'h2live.batch'`

- [ ] **Step 3: Implement**

`ios-livephoto/h2live/batch.py`:

```python
"""Renders a batch of HoMM2 map views and turns them into iPhone Live Photo wallpapers."""

import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from h2live.clip import make_clip
from h2live.livephoto import make_live_photo
from h2live.photos import import_pairs

REPO = Path(__file__).resolve().parents[2]
STEPS_PER_SECOND = 8
# Keeps every batch together in one day of the Photos and Google Photos timelines, away from real photos.
FIRST_CAPTURE = datetime(1996, 1, 1)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="h2live", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    batch = sub.add_parser("batch", help="render a batch and import it into Photos")
    batch.add_argument("--out", type=Path, required=True, help="empty or new folder for this batch")
    batch.add_argument("--count", type=int, default=60)
    batch.add_argument("--scale", type=int, choices=(2, 3, 4), default=3)
    batch.add_argument("--brightness", type=int, default=70)
    batch.add_argument("--album", default=f"H2 {date.today():%Y-%m-%d}")
    batch.add_argument("--no-import", action="store_true", help="build the files but skip Photos")
    batch.add_argument("--renderer", type=Path, default=REPO / "fheroes2")
    args = argv if argv is None else (["batch", *argv] if argv[:1] != ["batch"] else argv)
    return parser.parse_args(args)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.out.exists() and any(args.out.iterdir()):
        print(f"{args.out} is not empty; choose a new folder", file=sys.stderr)
        return 1

    frames, clips, live = args.out / "frames", args.out / "clips", args.out / "live"
    rendered = subprocess.run(
        [str(args.renderer), "--render-wallpapers", str(frames), str(args.count), str(args.scale), str(STEPS_PER_SECOND)]
    )
    if rendered.returncode != 0:
        print(f"renderer failed with exit code {rendered.returncode}", file=sys.stderr)
        return 1

    clips.mkdir(parents=True)
    live.mkdir(parents=True)
    pairs = []
    for i, view in enumerate(sorted(p for p in frames.iterdir() if p.is_dir())):
        clip = clips / f"{view.name}.mov"
        make_clip(view, clip, args.brightness, STEPS_PER_SECOND)
        pairs.append(make_live_photo(clip, live, f"H2_{view.name}", FIRST_CAPTURE + timedelta(minutes=i)))
        print(f"{i + 1}/{args.count} {(view / 'map.txt').read_text().strip()}")

    if args.no_import:
        print(f"Built {len(pairs)} Live Photos in {live}")
        return 0

    import_pairs(pairs, args.album)
    print(f"Imported {len(pairs)} Live Photos into the Photos album {args.album!r}.")
    print("Next: in Photos on the Mac, select the album's items → Share → AirDrop → your iPhone,")
    print("then on the iPhone add them to the H2 album.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Note: `parse_args` accepts both `main(["--out", …])` from tests and `h2live batch --out …` from the command line.

- [ ] **Step 4: Run all tests**

Run: `cd ios-livephoto && uv run pytest -v`
Expected: all tests pass (the Task 2 tests run too because the binary exists).

- [ ] **Step 5: Commit**

```bash
git add "ios-livephoto/h2live/batch.py" "ios-livephoto/tests/test_batch.py" "ios-livephoto/tests/fake_renderer.py"
git commit -m "Add h2live batch command"
```

---

### Task 7: Calibration on the phone (manual, with the user)

**Files:** none changed unless the user picks a different default scale (then `batch.py` default and the spec's Settings table).

- [ ] **Step 1: Render two samples per scale**

```bash
cd ios-livephoto
uv run h2live batch --out ~/Pictures/h2lwp-batches/calibration-s2 --count 2 --scale 2 --album "H2 calibration"
uv run h2live batch --out ~/Pictures/h2lwp-batches/calibration-s3 --count 2 --scale 3 --album "H2 calibration"
uv run h2live batch --out ~/Pictures/h2lwp-batches/calibration-s4 --count 2 --scale 4 --album "H2 calibration"
```

Expected: album "H2 calibration" in Photos with 6 items; `uvx osxphotos query --album "H2 calibration" --json` reports `live_photo: true` for all 6.

- [ ] **Step 2: User checks on the iPhone**

Ask the user to AirDrop the album from Photos on the Mac and set each one as the lock screen wallpaper. For each: is the Live button normal (not struck through), does it animate on wake, and which scale reads best under the clock and icons?

Expected: all 6 pass the Live check. If real map renders fail where the test "1" passed, compare `exiftool -G -s` and `ffprobe` output of a failing file against `~/Downloads/h2lwp-livephoto-test/ab/red-live.mov` before changing anything.

- [ ] **Step 3: Record the choice**

If the user picks scale 2 or 4, change the `--scale` default in `batch.py` and the spec's Settings table, run `uv run pytest`, and commit:

```bash
git add "ios-livephoto/h2live/batch.py" "ios-livephoto/docs/spec.md"
git commit -m "Use scale N for iPhone wallpapers"
```

---

### Task 8: First real batch and phone setup (manual, with the user)

- [ ] **Step 1: Render the batch**

```bash
cd ios-livephoto
uv run h2live batch --out ~/Pictures/h2lwp-batches/$(date +%F)
```

Expected: 60 items printed, then "Imported 60 Live Photos into the Photos album 'H2 <date>'".

- [ ] **Step 2: User transfers and sets up the phone**

Walk the user through:
1. Photos on the Mac → album "H2 <date>" → select all → Share → AirDrop → iPhone.
2. iPhone Photos → select the new items (they sit on 1 Jan 1996 in the Library view) → Add to Album → `H2`.
3. Shortcuts: change "H2 wallpaper" to Find Photos (Album is H2) → Get Item from List (Random Item) → Set Wallpaper Photo (Lock Screen and Home Screen, Show Preview off).
4. Automation: Time of Day 05:00, Daily, Run Immediately, Notify When Run off, runs "H2 wallpaper".
5. Delete the test albums and items from the Mac and the phone (the "h2lwp …" albums, the numbered test images, the `h2lwp-test` iCloud Drive folder).

- [ ] **Step 3: Confirm the next morning**

Ask the user whether the wallpaper changed at 05:00 and animates on wake.

- [ ] **Step 4: README (only after the user confirms it works)**

Ask the user before writing `ios-livephoto/README.md` covering: prerequisites (`brew install ffmpeg gpac exiftool imagemagick libheif sdl2 sdl2_mixer`), the build, the batch command, and the phone setup from Step 2. Commit it separately once approved.
