import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from conftest import probe
from h2live.clip import make_clip
from h2live.livephoto import make_live_photo


def tags(path: Path) -> dict:
    # QuickTimeUTC shows video dates in local time, as Photos does; they are stored in UTC.
    out = subprocess.run(
        ["exiftool", "-json", "-G", "-ee3", "-api", "QuickTimeUTC", str(path)], check=True, capture_output=True, text=True
    ).stdout
    return json.loads(out)[0]


@pytest.fixture
def pair(frames_dir, tmp_path):
    clip = tmp_path / "clip.mov"
    make_clip(frames_dir, clip, brightness=70, scale=3, direction=(1, 0))
    out = tmp_path / "live"
    out.mkdir()
    return make_live_photo(clip, out, "H2_000", datetime(1996, 1, 1, 0, 5))


def test_files_are_named_after_the_item(pair):
    heic, mov = pair
    assert (heic.name, mov.name) == ("H2_000.HEIC", "H2_000.mov")


def test_still_and_video_share_one_content_identifier(pair):
    heic, mov = pair
    assert tags(heic)["MakerNotes:ContentIdentifier"] == tags(mov)["QuickTime:ContentIdentifier"]


def test_video_carries_the_clip_and_the_base_metadata_tracks_only(pair):
    # goLive also keeps the base's own camera video; the phone accepts the file without it (test B).
    _, mov = pair
    streams = probe(mov)["streams"]
    assert [s["codec_type"] for s in streams] == ["video", "data", "data"]
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


def test_pair_stays_small(pair):
    assert sum(path.stat().st_size for path in pair) < 4_000_000


def test_video_uses_the_iphone_camera_colour_format(pair):
    # Same as camera Live Photos: with BT.709/limited-range video the lock screen flashed greens at the settle.
    _, mov = pair
    video = probe(mov)["streams"][0]
    assert (video["color_primaries"], video["color_transfer"], video["color_space"], video["color_range"]) == \
        ("smpte432", "bt709", "smpte170m", "pc")


def test_still_is_labelled_display_p3_like_camera_photos(pair):
    heic, _ = pair
    t = tags(heic)
    assert t["ICC_Profile:ProfileDescription"] == "Display P3"
    assert t["EXIF:ColorSpace"] == "Uncalibrated"


def test_still_matches_the_video_frame_it_settles_on(pair, tmp_path):
    # iOS crossfades from the video to the still; any colour mismatch shows as a flash.
    # Both hold Display P3 values, so compare them without colour conversion.
    heic, mov = pair
    still, frame = tmp_path / "still.png", tmp_path / "frame.png"
    subprocess.run(["magick", str(heic), "+profile", "*", str(still)], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", "0.5", "-i", str(mov), "-map", "0:v:0", "-frames:v", "1",
                    "-vf", "scale=in_color_matrix=bt601:in_range=pc,format=rgb24", str(frame)], check=True)
    result = subprocess.run(["magick", "compare", "-metric", "MAE", str(still), str(frame), "null:"],
                            capture_output=True, text=True)
    normalized = float(result.stderr.split("(")[1].split(")")[0])
    assert normalized < 0.004


def test_video_is_60_evenly_spaced_frames_at_60_fps(pair):
    # Variable frame timing and other rates are rejected or undeliverable (docs/findings.md).
    _, mov = pair
    video = probe(mov)["streams"][0]
    assert video["r_frame_rate"] == video["avg_frame_rate"] == "60/1"
    assert int(video["nb_frames"]) == 60
    pts = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts",
                          "-of", "csv=p=0", str(mov)], check=True, capture_output=True, text=True).stdout.split()
    pts = sorted(map(int, pts))
    num, den = map(int, video["time_base"].split("/"))
    assert {b - a for a, b in zip(pts, pts[1:])} == {den // (60 * num)}


def test_still_is_video_frame_30(pair, tmp_path):
    # The lock screen settles on frame 30; a still from any other frame jumps at the settle.
    heic, mov = pair
    still, frame = tmp_path / "still.png", tmp_path / "frame.png"
    subprocess.run(["magick", str(heic), "+profile", "*", str(still)], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(mov), "-map", "0:v:0", "-vf",
                    "select=eq(n\\,30),scale=in_color_matrix=bt601:in_range=pc,format=rgb24", "-frames:v", "1",
                    str(frame)], check=True)
    result = subprocess.run(["magick", "compare", "-metric", "MAE", str(still), str(frame), "null:"],
                            capture_output=True, text=True)
    assert float(result.stderr.split("(")[1].split(")")[0]) < 0.004
