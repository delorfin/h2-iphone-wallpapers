"""Turns one rendered map view into the 1-second clip a Live Photo wallpaper plays.

On wake the lock screen plays only video frames 17-30, on an ease-out curve over about 1.7 s, and shows
a linear crossfade between neighbouring frames. So the clip is planned frame by frame from that measured
curve rather than at a fixed animation rate:
- each animated object gets its own phase, so pose changes spread over the playback instead of the
  whole picture crossfading at once;
- poses change every game step (250 ms) of on-screen time;
- objects whose poses differ a lot (windmill blades, whirlpools) change only in the short early gaps,
  where a crossfade reads as a cut, and then hold; later, their crossfades show as double exposures.
"""

import math
import random
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

# iOS rejects Live Photo wallpapers in any other size or rate.
WIDTH, HEIGHT = 1080, 1920
OUTPUT_FPS = 60
# The view drifts one map pixel per video frame, which keeps the pixel art crisp. Vertical-only
# drift is left out: it runs under the lock screen clock and widgets.
DIRECTIONS = [(1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]

# Seconds after wake at which each video frame becomes the dominant one on the lock screen, measured by
# USB screen recording on an iPhone 12 Pro with iOS 18.7.2. The playback settles on frame 30 (the still).
SHOWN_AT = {17: 0.0, 18: 0.067, 19: 0.134, 20: 0.201, 21: 0.268, 22: 0.368, 23: 0.469, 24: 0.569,
            25: 0.669, 26: 0.787, 27: 0.954, 28: 1.121, 29: 1.356, 30: 1.657}
GAME_STEP = 0.25  # seconds per adventure-map animation step in the game
# Game poses the renderer must provide: the playback lasts ~1.7 s, plus up to one step of phase.
POSES = math.floor((SHOWN_AT[30] + GAME_STEP) / GAME_STEP) + 1
# Gaps up to frame 25 last 67-100 ms on screen; after that 120-300 ms.
BIG_JUMP_HOLD_FROM = SHOWN_AT[25]
# Pixels (map resolution) an object changes per step above which it counts as a big jump. Windmills
# measure 1300-1850 and whirlpools 1150-1320; boats, flags and units stay well below.
BIG_JUMP_PX = 1000


def view_size(scale: int) -> tuple[int, int]:
    """Map pixels the renderer must draw: the visible area plus room for the pan on both axes."""
    return WIDTH // scale + OUTPUT_FPS, HEIGHT // scale + OUTPUT_FPS


def pose_schedule(phase: float, gated: bool) -> list[int]:
    """Game pose index for each of the 60 video frames of an object with this phase."""
    schedule = []
    for frame in range(OUTPUT_FPS):
        shown = SHOWN_AT[min(max(frame, 17), 30)]
        if gated:
            shown = min(shown, BIG_JUMP_HOLD_FROM)
        schedule.append(min(math.floor((shown + phase) / GAME_STEP + 1e-9), POSES - 1))
    return schedule


def plan_frames(poses: np.ndarray, seed: int) -> np.ndarray:
    """Composes the 60 video frames (map resolution) from the game poses, object by object."""
    changing = np.zeros(poses.shape[1:3], bool)
    for a, b in zip(poses, poses[1:]):
        changing |= (a != b).any(axis=2)
    # Grown a little so each object's changing pixels form one region.
    objects, count = ndimage.label(ndimage.binary_dilation(changing, iterations=3))
    step_change = [0.0] + [
        np.mean([((a != b).any(axis=2) & (objects == i)).sum() for a, b in zip(poses, poses[1:])])
        for i in range(1, count + 1)
    ]
    rng = random.Random(seed)
    # Region 0 is everything that never changes; its pose doesn't matter.
    schedules = np.array([pose_schedule(0.0, False)] + [
        pose_schedule(rng.uniform(0, GAME_STEP), step_change[i] > BIG_JUMP_PX) for i in range(1, count + 1)
    ])
    rows, cols = np.indices(objects.shape)
    return np.stack([poses[schedules[objects, frame], rows, cols] for frame in range(OUTPUT_FPS)])


def _pan_start(step: int, margin: int) -> int:
    return 0 if step > 0 else margin if step < 0 else margin // 2


def make_clip(frames_dir: Path, out: Path, brightness: int, scale: int, direction: tuple[int, int],
              seed: int = 0) -> None:
    """Encodes the clip from the renderer's game poses f00.bmp .. f07.bmp in `frames_dir`."""
    if not 1 <= brightness <= 100:
        raise ValueError(f"brightness must be 1-100, got {brightness}")
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction}")
    paths = sorted(frames_dir.glob("f*.bmp"))
    if len(paths) != POSES:
        raise ValueError(f"expected {POSES} frames in {frames_dir}, found {len(paths)}")
    poses = np.stack([np.asarray(Image.open(p).convert("RGB")) for p in paths])
    expected, actual = view_size(scale), (poses.shape[2], poses.shape[1])
    if actual != expected:
        raise ValueError(f"expected {expected[0]}x{expected[1]} frames for scale {scale}, got {actual[0]}x{actual[1]}")

    frames = plan_frames(poses, seed)
    margin = OUTPUT_FPS * scale  # output pixels the view drifts over the clip
    dx, dy = direction
    x0, y0 = _pan_start(dx, margin), _pan_start(dy, margin)
    level = brightness / 100
    encoder = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-framerate", str(OUTPUT_FPS), "-i", "-",
         # The iPhone camera's own Live Photo format: Display P3 primaries, BT.709 transfer, BT.601
         # matrix, full range. With anything else the lock screen flashed greens at the settle.
         "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv444p,"
                "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv,"
                "colorspace=primaries=smpte432:trc=bt709:space=smpte170m:range=pc:format=yuv420p",
         "-frames:v", str(OUTPUT_FPS),
         "-colorspace", "smpte170m", "-color_primaries", "smpte432", "-color_trc", "bt709", "-color_range", "pc",
         "-c:v", "libx265", "-crf", "20", "-tag:v", "hvc1",
         "-x265-params", "log-level=error:colorprim=smpte432:transfer=bt709:colormatrix=smpte170m:range=full",
         str(out)],
        stdin=subprocess.PIPE,
    )
    for n, frame in enumerate(frames):
        # Nearest-neighbour by a whole factor keeps every map pixel a sharp square.
        big = frame.repeat(scale, axis=0).repeat(scale, axis=1)
        x, y = x0 + dx * scale * n, y0 + dy * scale * n
        encoder.stdin.write((big[y:y + HEIGHT, x:x + WIDTH] * level).astype(np.uint8).tobytes())
    encoder.stdin.close()
    if encoder.wait() != 0:
        raise RuntimeError(f"ffmpeg failed encoding {out}")
