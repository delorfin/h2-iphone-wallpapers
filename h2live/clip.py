"""Turns one rendered map view into the 1-second clip a Live Photo wallpaper plays."""

import struct
import subprocess
from pathlib import Path

# iOS rejects Live Photo wallpapers in any other size.
WIDTH, HEIGHT = 1080, 1920
OUTPUT_FPS = 60
# The view drifts one map pixel per video frame, which keeps the pixel art crisp. Vertical-only
# drift is left out: it runs under the lock screen clock and widgets.
DIRECTIONS = [(1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]


def view_size(scale: int) -> tuple[int, int]:
    """Map pixels the renderer must draw: the visible area plus room for the pan on both axes."""
    return WIDTH // scale + OUTPUT_FPS, HEIGHT // scale + OUTPUT_FPS


def _bmp_size(path: Path) -> tuple[int, int]:
    width, height = struct.unpack("<ii", path.read_bytes()[18:26])
    return width, abs(height)


def _pan_start(step: int, margin: int) -> int:
    return 0 if step > 0 else margin if step < 0 else margin // 2


def make_clip(frames_dir: Path, out: Path, brightness: int, scale: int, direction: tuple[int, int],
              steps_per_second: int = 30) -> None:
    if not 1 <= brightness <= 100:
        raise ValueError(f"brightness must be 1-100, got {brightness}")
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction}")
    frames = sorted(frames_dir.glob("f*.bmp"))
    if len(frames) != steps_per_second:
        raise ValueError(f"expected {steps_per_second} frames in {frames_dir}, found {len(frames)}")
    expected, actual = view_size(scale), _bmp_size(frames[0])
    if actual != expected:
        raise ValueError(f"expected {expected[0]}x{expected[1]} frames for scale {scale}, got {actual[0]}x{actual[1]}")

    margin = OUTPUT_FPS * scale  # output pixels the view drifts over the clip
    dx, dy = direction
    x = f"{_pan_start(dx, margin)}+{dx * scale}*n"
    y = f"{_pan_start(dy, margin)}+{dy * scale}*n"
    level = brightness / 100
    video_filter = (
        f"fps={OUTPUT_FPS},"
        # Nearest-neighbour by a whole factor keeps every map pixel a sharp square.
        f"scale=iw*{scale}:ih*{scale}:flags=neighbor,"
        f"crop={WIDTH}:{HEIGHT}:x='{x}':y='{y}',"
        f"colorchannelmixer=rr={level}:gg={level}:bb={level},"
        # The iPhone camera's own Live Photo format: Display P3 primaries, BT.709 transfer, BT.601
        # matrix, full range. With anything else the lock screen flashed greens at the settle.
        "scale=out_color_matrix=bt709:out_range=tv,format=yuv444p,"
        "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv,"
        "colorspace=primaries=smpte432:trc=bt709:space=smpte170m:range=pc:format=yuv420p"
    )
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-framerate", str(steps_per_second), "-i", str(frames_dir / "f%02d.bmp"),
         "-vf", video_filter, "-frames:v", str(OUTPUT_FPS),
         "-colorspace", "smpte170m", "-color_primaries", "smpte432", "-color_trc", "bt709", "-color_range", "pc",
         "-c:v", "libx265", "-crf", "20", "-tag:v", "hvc1",
         "-x265-params", "log-level=error:colorprim=smpte432:transfer=bt709:colormatrix=smpte170m:range=full",
         str(out)],
        check=True,
    )
