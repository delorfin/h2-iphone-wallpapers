import pytest
import sys
from pathlib import Path

from h2live.batch import main

FAKE = Path(__file__).with_name("fake_renderer.py")


def fake_renderer(tmp_path: Path) -> str:
    wrapper = tmp_path / "renderer"
    if wrapper.exists():  # rewriting it would look like a renderer rebuild to the scout cache
        return str(wrapper)
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
    wrapper.chmod(0o755)
    return str(wrapper)


def test_builds_one_pair_per_view_without_importing(tmp_path):
    out = tmp_path / "batch"
    code = main(["--out", str(out), "--count", "2", "--no-import", "--renderer", fake_renderer(tmp_path),
                 "--game-data", str(fake_game_data(tmp_path, "good"))])
    assert code == 0
    assert sorted(p.name for p in (out / "live").iterdir()) == ["H2_000.HEIC", "H2_000.mov", "H2_001.HEIC", "H2_001.mov"]


def test_refuses_non_empty_output_dir(tmp_path):
    out = tmp_path / "batch"
    out.mkdir()
    (out / "old.txt").write_text("previous batch")
    assert main(["--out", str(out), "--count", "1", "--no-import", "--renderer", fake_renderer(tmp_path),
                 "--game-data", str(fake_game_data(tmp_path, "good"))]) != 0
    assert sorted(p.name for p in out.iterdir()) == ["old.txt"]


def test_renderer_failure_stops_the_batch(tmp_path):
    failing = tmp_path / "renderer"
    failing.write_text("#!/bin/sh\nexit 3\n")
    failing.chmod(0o755)
    assert main(["--out", str(tmp_path / "batch"), "--count", "1", "--no-import", "--renderer", str(failing),
                 "--game-data", str(fake_game_data(tmp_path, "good"))]) != 0


def fake_game_data(tmp_path: Path, maps: str) -> Path:
    folder = tmp_path / "game-data"
    (folder / "maps").mkdir(parents=True, exist_ok=True)
    for name in (["empty.mp2"] if maps == "empty" else ["a.mp2", "b.mp2", "dull.mp2"]):
        (folder / "maps" / name).write_text("fake")
    return folder


def run(tmp_path: Path, count: int, maps: str = "good", out: str = "batch", *extra: str) -> int:
    return main(["--out", str(tmp_path / out), "--count", str(count), "--no-import",
                 "--renderer", fake_renderer(tmp_path), "--scout-cache", str(tmp_path / "cache"),
                 "--game-data", str(fake_game_data(tmp_path, maps)), "--history", str(tmp_path / "used-views.txt"), *extra])


def test_renders_every_view_that_passes_the_map_rules(tmp_path):
    # dull.mp2 renders flat; the user dropped the image check because it rejected views they liked.
    assert run(tmp_path, 3) == 0
    views = (tmp_path / "batch/views.txt").read_text().splitlines()
    assert sorted(Path(line.split(" ", 2)[2]).name for line in views) == ["a.mp2", "b.mp2", "dull.mp2"]
    assert all(line.split()[:2] == ["0", "0"] for line in views)


def test_stops_with_a_message_when_too_few_views_pass(tmp_path, capsys):
    assert run(tmp_path, 4) != 0
    assert "3 of 4" in capsys.readouterr().err
    assert not (tmp_path / "batch/live").exists()


def test_stops_when_no_map_has_a_good_view(tmp_path, capsys):
    assert run(tmp_path, 1, maps="empty") != 0
    assert "0 of 1" in capsys.readouterr().err


def test_scouting_is_cached_per_renderer_build(tmp_path):
    assert run(tmp_path, 1) == 0
    assert len(list((tmp_path / "cache").glob("*.pickle"))) == 1


def test_default_scout_cache_follows_the_environment(tmp_path, scout_cache):
    out = tmp_path / "batch"
    assert main(["--out", str(out), "--count", "1", "--no-import", "--renderer", fake_renderer(tmp_path),
                 "--game-data", str(fake_game_data(tmp_path, "good"))]) == 0
    assert len(list(scout_cache.glob("*.pickle"))) == 1


def test_without_import_only_the_finished_live_photos_and_view_list_stay(tmp_path):
    assert run(tmp_path, 2) == 0
    assert sorted(p.name for p in (tmp_path / "batch").iterdir()) == ["live", "views.txt"]


def fake_import(monkeypatch) -> list:
    import h2live.batch as batch
    imported = []
    monkeypatch.setattr(batch, "import_pairs", lambda pairs, album: imported.extend(pairs) or len(pairs))
    return imported


def batch_args(tmp_path: Path, *extra: str) -> list[str]:
    return ["--count", "2", "--renderer", fake_renderer(tmp_path), "--scout-cache", str(tmp_path / "cache"),
            "--game-data", str(fake_game_data(tmp_path, "good")), *extra]


def test_after_import_the_batch_folder_is_removed(tmp_path, monkeypatch):
    # Photos keeps its own copy of every imported file, and the history records the views.
    imported = fake_import(monkeypatch)
    assert main(batch_args(tmp_path, "--out", str(tmp_path / "batch"))) == 0
    assert len(imported) == 2
    assert not (tmp_path / "batch").exists()


def test_without_out_the_batch_works_in_the_cache_and_cleans_up(tmp_path, monkeypatch, capsys):
    fake_import(monkeypatch)
    assert main(batch_args(tmp_path)) == 0
    work = tmp_path / "cache" / "work"
    assert str(work) in capsys.readouterr().out
    assert not work.exists() or not any(work.iterdir())


def test_a_failed_batch_keeps_its_work_folder(tmp_path, monkeypatch, capsys):
    import h2live.batch as batch
    def broken(*args, **kwargs):
        raise RuntimeError("encoder broke")
    monkeypatch.setattr(batch, "make_clip", broken)
    with pytest.raises(RuntimeError):
        main(batch_args(tmp_path))
    kept = [p for p in (tmp_path / "cache" / "work").iterdir()]
    assert len(kept) == 1 and (kept[0] / "frames").is_dir()
    assert str(kept[0]) in capsys.readouterr().out


def test_without_import_or_out_the_live_photos_go_to_the_export_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("H2LIVE_EXPORT_DIR", str(tmp_path / "Downloads"))
    assert main(batch_args(tmp_path, "--no-import")) == 0
    exported = list((tmp_path / "Downloads").glob("h2live-*"))
    assert len(exported) == 1
    assert len(list((exported[0] / "live").glob("*.mov"))) == 2


def test_history_notes_each_batch(tmp_path, monkeypatch):
    fake_import(monkeypatch)
    assert main(batch_args(tmp_path, "--album", "H2", "--history", str(tmp_path / "used.txt"))) == 0
    lines = (tmp_path / "used.txt").read_text().splitlines()
    assert lines[0].startswith("# ") and "H2" in lines[0] and "2 views" in lines[0]
    assert len(lines) == 3


def scouted_names(log: Path) -> list[str]:
    return sorted(log.read_text().split()) if log.exists() else []


def scout(tmp_path: Path, data: Path) -> list[str]:
    from h2live.select import scout_maps
    return sorted(Path(m.path).name for m in scout_maps(Path(fake_renderer(tmp_path)), data, tmp_path / "cache"))


def test_new_maps_are_scouted_and_known_ones_reused(tmp_path, monkeypatch):
    log = tmp_path / "scouts.log"
    monkeypatch.setenv("FAKE_SCOUT_LOG", str(log))
    data = fake_game_data(tmp_path, "good")
    (data / "maps/dull.mp2").unlink()
    assert scout(tmp_path, data) == ["a.mp2", "b.mp2"]
    log.unlink()
    (data / "maps/dull.mp2").write_text("fake")
    assert scout(tmp_path, data) == ["a.mp2", "b.mp2", "dull.mp2"]
    assert scouted_names(log) == ["dull.mp2"]


def test_removed_maps_drop_out_without_rescouting_the_rest(tmp_path, monkeypatch):
    log = tmp_path / "scouts.log"
    monkeypatch.setenv("FAKE_SCOUT_LOG", str(log))
    data = fake_game_data(tmp_path, "good")
    scout(tmp_path, data)
    log.unlink()
    (data / "maps/b.mp2").unlink()
    assert scout(tmp_path, data) == ["a.mp2", "dull.mp2"]
    assert scouted_names(log) == []


def test_changed_maps_are_rescouted(tmp_path, monkeypatch):
    log = tmp_path / "scouts.log"
    monkeypatch.setenv("FAKE_SCOUT_LOG", str(log))
    data = fake_game_data(tmp_path, "good")
    scout(tmp_path, data)
    log.unlink()
    (data / "maps/a.mp2").write_text("fake, edited")
    scout(tmp_path, data)
    assert scouted_names(log) == ["a.mp2"]


def test_maps_that_fail_to_load_are_not_retried(tmp_path, monkeypatch):
    log = tmp_path / "scouts.log"
    monkeypatch.setenv("FAKE_SCOUT_LOG", str(log))
    data = fake_game_data(tmp_path, "good")
    (data / "maps/broken.mp2").write_text("fake")
    assert scout(tmp_path, data) == ["a.mp2", "b.mp2", "dull.mp2"]
    log.unlink()
    scout(tmp_path, data)
    assert scouted_names(log) == []


def test_next_batch_avoids_views_used_before(tmp_path):
    assert run(tmp_path, 2, "good", "first") == 0
    used = [line for line in (tmp_path / "used-views.txt").read_text().splitlines() if not line.startswith("#")]
    assert len(used) == 2
    # Each fake map has exactly one good view, so only the third map is left.
    assert run(tmp_path, 1, "good", "second") == 0
    third = (tmp_path / "second/views.txt").read_text().split(" ", 2)[2].strip()
    assert Path(third).name not in {line.split(" ", 2)[2] for line in used}
    assert run(tmp_path, 1, "good", "third") != 0


def test_reuse_ignores_the_history(tmp_path):
    assert run(tmp_path, 3, "good", "first") == 0
    assert run(tmp_path, 3, "good", "second", "--reuse") == 0


def test_failed_batch_leaves_the_history_alone(tmp_path):
    assert run(tmp_path, 4, "good", "too-many") != 0
    assert not (tmp_path / "used-views.txt").exists()
