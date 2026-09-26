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
    (folder / "DATA").mkdir(exist_ok=True)
    (folder / "DATA/HEROES2.AGG").write_text("fake")
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


def test_maps_that_fail_for_another_reason_are_retried_and_reported(tmp_path, monkeypatch, capsys):
    # A crash or missing game data says nothing about the map, so it mustn't be remembered as unloadable.
    log = tmp_path / "scouts.log"
    monkeypatch.setenv("FAKE_SCOUT_LOG", str(log))
    data = fake_game_data(tmp_path, "good")
    (data / "maps/crash.mp2").write_text("fake")
    assert scout(tmp_path, data) == ["a.mp2", "b.mp2", "dull.mp2"]
    assert "No AGG data files found" in capsys.readouterr().err
    log.unlink()
    scout(tmp_path, data)
    assert scouted_names(log) == ["crash.mp2"]


def test_when_no_map_scouts_the_error_shows_the_engine_message(tmp_path):
    from h2live.select import scout_maps
    data = tmp_path / "data"
    (data / "maps").mkdir(parents=True)
    (data / "maps/crash.mp2").write_text("fake")
    with pytest.raises(RuntimeError, match="No AGG data files found"):
        scout_maps(Path(fake_renderer(tmp_path)), data, tmp_path / "cache")


def test_other_game_data_rescouts_everything(tmp_path, monkeypatch):
    # The bundled maps keep their paths when the game data changes, e.g. from the demo to a full install.
    from h2live.select import scout_maps
    log = tmp_path / "scouts.log"
    monkeypatch.setenv("FAKE_SCOUT_LOG", str(log))
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "a.mp2").write_text("fake")
    monkeypatch.setenv("H2LIVE_BUNDLED_MAPS", str(bundled))
    for data in ("demo", "full"):
        (tmp_path / data).mkdir()
        scout_maps(Path(fake_renderer(tmp_path)), tmp_path / data, tmp_path / "cache")
    assert scouted_names(log) == ["a.mp2", "a.mp2"]


def test_bundled_maps_are_scouted_too(tmp_path, monkeypatch):
    from h2live.select import map_files
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "Extra.fh2m").write_text("fake")
    (bundled / "notes.txt").write_text("not a map")
    monkeypatch.setenv("H2LIVE_BUNDLED_MAPS", str(bundled))
    data = fake_game_data(tmp_path, "good")
    assert [p.name for p in map_files(data)] == ["a.mp2", "b.mp2", "dull.mp2", "Extra.fh2m"]


def test_stops_with_the_options_when_there_is_no_game_data(tmp_path, monkeypatch, capsys):
    from h2live import gamedata
    monkeypatch.setattr(gamedata, "FHEROES2_DATA", tmp_path / "no-fheroes2")
    monkeypatch.setenv("H2LIVE_DEMO_DIR", str(tmp_path / "no-demo"))
    assert main(["--out", str(tmp_path / "batch"), "--count", "1", "--no-import", "--renderer", fake_renderer(tmp_path)]) != 0
    assert "h2live get-demo" in capsys.readouterr().err
    assert not (tmp_path / "batch").exists()


def test_get_demo_is_a_command(monkeypatch):
    from h2live import batch
    calls = []
    monkeypatch.setattr(batch, "get_demo_command", lambda: calls.append("get-demo") or 0)
    assert main(["get-demo"]) == 0
    assert calls == ["get-demo"]


def capture_time(heic: Path) -> str:
    import subprocess
    return subprocess.run(["exiftool", "-s3", "-DateTimeOriginal", str(heic)],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_capture_times_continue_across_batches(tmp_path):
    # The capture time is the wallpaper's only identity a shortcut can read on the phone (synced photos'
    # names read as UUIDs), so no two batches may share one: minutes after the first capture = line in the history.
    assert run(tmp_path, 2, "good", "first") == 0
    assert run(tmp_path, 1, "good", "second") == 0
    times = [capture_time(p) for p in [*sorted((tmp_path / "first/live").glob("*.HEIC")), *(tmp_path / "second/live").glob("*.HEIC")]]
    assert times == ["1996:01:01 12:00:00", "1996:01:01 12:01:00", "1996:01:01 12:02:00"]


def test_default_album_is_the_one_the_sync_instructions_name(tmp_path, monkeypatch):
    import h2live.batch as batch
    albums = []
    monkeypatch.setattr(batch, "import_pairs", lambda pairs, album: albums.append(album) or len(pairs))
    assert main(batch_args(tmp_path)) == 0
    assert albums == ["H2"]


def test_missing_tools_stop_the_batch_before_rendering(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    assert main(batch_args(tmp_path, "--no-import", "--out", str(tmp_path / "batch"))) != 0
    assert "brew install" in capsys.readouterr().err
    assert not (tmp_path / "batch").exists()


def test_missing_renderer_says_to_build_it(tmp_path, capsys):
    args = batch_args(tmp_path, "--no-import", "--out", str(tmp_path / "batch"))
    args[args.index("--renderer") + 1] = str(tmp_path / "not-built")
    assert main(args) != 0
    assert "./build.sh" in capsys.readouterr().err


@pytest.mark.parametrize("option, value", [("--brightness", "0"), ("--brightness", "101"), ("--count", "0")])
def test_bad_numbers_are_refused_before_rendering(tmp_path, option, value):
    with pytest.raises(SystemExit):
        main([*batch_args(tmp_path, "--no-import", "--out", str(tmp_path / "batch")), option, value])
    assert not (tmp_path / "batch").exists()


def test_blank_lines_in_the_history_are_ignored(tmp_path):
    (tmp_path / "used-views.txt").write_text("# old batch\n0 0 a.mp2\n\n")
    assert run(tmp_path, 1) == 0
    lines = (tmp_path / "used-views.txt").read_text().splitlines()
    assert sum(bool(line) and not line.startswith("#") for line in lines) == 2


def test_a_failed_photos_import_keeps_the_files_and_records_the_views(tmp_path, monkeypatch, capsys):
    # The Live Photos on disk already carry their capture times, so the history must count them.
    import h2live.batch as batch
    from h2live.photos import PhotosImportError
    def refuse(pairs, album):
        raise PhotosImportError("Photos refused")
    monkeypatch.setattr(batch, "import_pairs", refuse)
    history = tmp_path / "used.txt"
    assert main(batch_args(tmp_path, "--out", str(tmp_path / "batch"), "--history", str(history))) != 0
    assert "Photos refused" in capsys.readouterr().err
    assert len(list((tmp_path / "batch/live").glob("*.mov"))) == 2
    lines = history.read_text().splitlines()
    assert "failed" in lines[0] and len(lines) == 3


def test_a_failing_tool_is_named_with_its_message(tmp_path, monkeypatch, capsys):
    import subprocess
    import h2live.batch as batch
    def broken(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["MP4Box", "-add"], stderr=b"Bad Parameter")
    monkeypatch.setattr(batch, "make_live_photo", broken)
    assert main(batch_args(tmp_path, "--no-import", "--out", str(tmp_path / "batch"))) != 0
    err = capsys.readouterr().err
    assert "MP4Box" in err and "Bad Parameter" in err and str(tmp_path / "batch") in err


def test_the_same_seed_makes_the_same_batch(tmp_path, capsys):
    printed = []
    for out in ("one", "two"):
        assert run(tmp_path, 2, "good", out, "--seed", "7", "--reuse") == 0
        printed.append([line.split(" ", 1)[1] for line in capsys.readouterr().out.splitlines() if "/2 pan" in line])
    assert printed[0] == printed[1]
    assert (tmp_path / "one/views.txt").read_text() == (tmp_path / "two/views.txt").read_text()


def test_help_mentions_get_demo(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "h2live get-demo" in capsys.readouterr().out
