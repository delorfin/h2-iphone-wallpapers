"""Turns a clip into a Live Photo pair that iOS accepts as a lock screen wallpaper.

Follows goLive (https://github.com/code-path/goLive, Apache-2.0): the clip's video
track is muxed with the timed metadata tracks of a real camera Live Photo
(base/base.mov), and the camera photo's tags are copied onto the new still and
video. Hand-built metadata gets rejected by the wallpaper picker. goLive also keeps
the base's own video track; the phone accepts the file without it, which saves ~3 MB.
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
        # Tracks 2 and 3 of base.mov are its live-photo-info and still-image-time metadata.
        _run("MP4Box", "-add", raw, "-add", f"{base_mov}#2", "-add", f"{base_mov}#3", "-new", mov)

        still = tmp / "still.png"
        _run("ffmpeg", "-loglevel", "error", "-y", "-ss", "0.5", "-i", mov, "-map", "0:v:0", "-frames:v", "1", still)
        _run("magick", still, "-quality", "85", heic)

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
