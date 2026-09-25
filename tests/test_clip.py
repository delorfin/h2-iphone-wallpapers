import pytest

from conftest import gray_frame, mean_luma, probe
from h2live.clip import DIRECTIONS, make_clip, view_size


def test_view_size_leaves_one_map_pixel_of_pan_per_video_frame():
    assert view_size(3) == (420, 700)
    assert view_size(2) == (600, 1020)


def test_clip_is_one_second_1080x1920_hevc_at_60fps(frames_dir, tmp_path):
    out = tmp_path / "clip.mov"
    make_clip(frames_dir, out, brightness=70, scale=3, direction=(1, 0))
    video = probe(out)["streams"][0]
    assert (video["width"], video["height"]) == (1080, 1920)
    assert video["codec_tag_string"] == "hvc1"
    assert video["r_frame_rate"] == "60/1"
    assert int(video["nb_frames"]) == 60


@pytest.mark.parametrize("direction", [(1, 0), (-1, 1)])
def test_pan_moves_three_output_pixels_per_frame_in_the_chosen_direction(still_frames_dir, tmp_path, direction):
    out = tmp_path / "clip.mov"
    make_clip(still_frames_dir, out, brightness=100, scale=3, direction=direction)
    width, height, first = gray_frame(out, 0)
    _, _, last = gray_frame(out, 59)
    dx, dy = direction[0] * 177, direction[1] * 177  # 59 frames x 3 px
    diffs = []
    for y in range(400, 1500, 7):
        for x in range(300, 780, 7):
            diffs.append(abs(first[(y + dy) * width + x + dx] - last[y * width + x]))
    assert sum(diffs) / len(diffs) < 4


def test_brightness_dims_the_picture(frames_dir, tmp_path):
    make_clip(frames_dir, tmp_path / "full.mov", brightness=100, scale=3, direction=(1, 0))
    make_clip(frames_dir, tmp_path / "half.mov", brightness=50, scale=3, direction=(1, 0))
    ratio = mean_luma(tmp_path / "half.mov") / mean_luma(tmp_path / "full.mov")
    # Video luma has a black-level offset, so 50% brightness lands near, not exactly at, half.
    assert 0.35 < ratio < 0.65


def test_rejects_wrong_frame_count(frames_dir, tmp_path):
    (frames_dir / "f39.bmp").unlink()
    with pytest.raises(ValueError, match="expected 40 frames"):
        make_clip(frames_dir, tmp_path / "clip.mov", brightness=70, scale=3, direction=(1, 0))


def test_rejects_frames_of_the_wrong_size(frames_dir, tmp_path):
    with pytest.raises(ValueError, match="420x700"):
        make_clip(frames_dir, tmp_path / "clip.mov", brightness=70, scale=2, direction=(1, 0))


@pytest.mark.parametrize("brightness", [0, 101])
def test_rejects_brightness_out_of_range(frames_dir, tmp_path, brightness):
    with pytest.raises(ValueError, match="brightness"):
        make_clip(frames_dir, tmp_path / "clip.mov", brightness=brightness, scale=3, direction=(1, 0))


def test_directions_are_horizontal_or_diagonal():
    assert len(DIRECTIONS) == 6
    assert all(dx != 0 for dx, _ in DIRECTIONS)
