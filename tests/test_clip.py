import pytest

from conftest import gray_frame, mean_luma, probe
import numpy as np

from h2live.clip import DIRECTIONS, POSES, make_clip, plan_frames, pose_schedule, view_size


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
    (frames_dir / "f07.bmp").unlink()
    with pytest.raises(ValueError, match="expected 8 frames"):
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


def changes(schedule):
    return [f for f in range(1, len(schedule)) if schedule[f] != schedule[f - 1]]


def test_poses_change_evenly_on_screen_given_the_measured_lock_screen_curve():
    # Measured: frame 21 shows at 0.27 s, 24 at 0.57, 26 at 0.79, 28 at 1.12, 29 at 1.36, 30 at 1.66.
    assert changes(pose_schedule(phase=0.0, gated=False)) == [21, 24, 26, 28, 29, 30]


def test_big_jump_objects_change_only_in_the_short_early_gaps():
    assert changes(pose_schedule(phase=0.0, gated=True)) == [21, 24]


def test_schedule_never_runs_past_the_rendered_poses():
    assert max(pose_schedule(phase=0.249, gated=False)) == POSES - 1


def toggling_squares(count, size=6, gap=10):
    """Poses where `count` separate squares alternate between black and white every game step."""
    width = count * (size + gap)
    poses = np.zeros((POSES, 20, width, 3), np.uint8)
    for p in range(POSES):
        for i in range(count):
            poses[p, 5:5 + size, i * (size + gap):i * (size + gap) + size] = 255 * (p % 2)
    return poses


def test_each_object_animates_on_its_own_phase():
    frames = plan_frames(toggling_squares(12), seed=1)
    visible = [f for f in range(18, 31) if (frames[f] != frames[f - 1]).any()]
    # In sync, changes would land on only 6 frames; independent phases spread them out.
    assert len(visible) >= 10


def test_phases_are_reproducible_per_seed():
    poses = toggling_squares(5)
    assert (plan_frames(poses, seed=3) == plan_frames(poses, seed=3)).all()


def test_objects_with_big_jumps_hold_after_the_early_gaps():
    poses = np.zeros((POSES, 60, 60, 3), np.uint8)
    for p in range(POSES):
        poses[p, 5:55, 5:55] = 255 * (p % 2)  # 2500 px change every step, like windmill blades
    frames = plan_frames(poses, seed=0)
    assert all(f <= 25 for f in range(18, 31) if (frames[f] != frames[f - 1]).any())
