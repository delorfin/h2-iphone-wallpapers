"""Renders a batch of HoMM2 map views and turns them into iPhone Live Photo wallpapers."""

import argparse
import os
import random
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from h2live.clip import DIRECTIONS, POSES, make_clip, view_size
from h2live.gamedata import NoGameData, find_game_data, get_demo_command
from h2live.livephoto import make_live_photo
from h2live.photos import import_pairs
from h2live.select import NotEnoughViews, View, scout_maps, select_views, window_tiles

REPO = Path(__file__).resolve().parents[1]
# Built by build.sh.
RENDERER = REPO / "engine" / "fheroes2"
# Keeps every batch together on one day of the Photos and Google Photos timelines, away from real photos.
# Noon keeps all items on that day in any timezone.
FIRST_CAPTURE = datetime(1996, 1, 1, 12)


def scout_cache() -> Path:
    return Path(os.environ.get("H2LIVE_SCOUT_CACHE", Path.home() / "Library/Caches/h2live"))


def history_file() -> Path:
    """Every view used by earlier batches, one "x y mapfile" line each. App data, not cache: losing it
    would let new batches repeat old wallpapers."""
    return Path(os.environ.get("H2LIVE_HISTORY", Path.home() / "Library/Application Support/h2live/used-views.txt"))


def used_views(history: Path, maps: list) -> list[View]:
    """Views from the history, matched to the scouted maps by file name so moving the game folder is fine."""
    paths = {Path(m.path).name: m.path for m in maps}
    views = []
    for line in history.read_text().splitlines() if history.exists() else []:
        if line.startswith("#"):  # a note heading each batch
            continue
        x, y, name = line.split(" ", 2)
        if name in paths:
            views.append(View(paths[name], int(x), int(y)))
    return views


def remember(history: Path, views: list[View], album: str | None) -> None:
    history.parent.mkdir(parents=True, exist_ok=True)
    where = f"album {album}" if album else "not imported"
    with history.open("a") as out:
        out.write(f"# {datetime.now():%Y-%m-%d %H:%M} {where}, {len(views)} views\n")
        out.writelines(f"{v.x} {v.y} {Path(v.map).name}\n" for v in views)


def default_out(no_import: bool, cache: Path) -> Path:
    """A work folder in the cache, removed after import; or, for --no-import, an export folder in Downloads."""
    stamp = f"{datetime.now():%Y-%m-%d-%H%M%S}"
    if no_import:
        return Path(os.environ.get("H2LIVE_EXPORT_DIR", Path.home() / "Downloads")) / f"h2live-{stamp}"
    return cache / "work" / stamp


def parse_args(argv: list[str]) -> argparse.Namespace:
    if argv[:1] == ["batch"]:
        argv = argv[1:]
    parser = argparse.ArgumentParser(prog="h2live batch", description=__doc__)
    parser.add_argument("--out", type=Path, help="empty or new folder to work in (default: a folder in the cache, "
                        "or ~/Downloads/h2live-<date> with --no-import)")
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--scale", type=int, choices=(2, 3, 4), default=3)
    parser.add_argument("--brightness", type=int, default=70)
    parser.add_argument("--album", default=f"H2 {date.today():%Y-%m-%d}")
    parser.add_argument("--no-import", action="store_true", help="build the files but skip Photos")
    parser.add_argument("--renderer", type=Path, default=RENDERER, help="built by build.sh")
    parser.add_argument("--scout-cache", type=Path, default=scout_cache(), help="where scouted maps are kept between batches")
    parser.add_argument("--game-data", type=Path, help="folder with the game's DATA and MAPS (default: fheroes2's "
                        "data folder, else the demo from h2live get-demo)")
    parser.add_argument("--history", type=Path, default=history_file(), help="views used by earlier batches")
    parser.add_argument("--reuse", action="store_true", help="allow views used by earlier batches")
    return parser.parse_args(argv)


def render_views(renderer: Path, views: list[View], out: Path, width: int, height: int, frames: int,
                 game_data: Path) -> None:
    """Renders each view into out/NNN in its own renderer process, several at a time: loading several
    maps in one process lets engine state carry over, so random objects would differ from the scout."""
    def render_one(index: int, view: View) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            spec = Path(scratch) / "view.txt"
            spec.write_text(f"{view.x} {view.y} {view.map}\n")
            rendered = subprocess.run(
                [str(renderer), "--render-views", str(spec), str(Path(scratch) / "out"), str(width), str(height), str(frames)],
                env={**os.environ, "FHEROES2_DATA": str(game_data)}, capture_output=True, text=True,
            )
            if rendered.returncode != 0:
                raise RuntimeError(f"renderer failed with exit code {rendered.returncode} on {view.map}: {rendered.stderr[-500:]}")
            (Path(scratch) / "out" / "000").rename(out / f"{index:03d}")

    out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        list(pool.map(lambda item: render_one(*item), enumerate(views)))


def render_good_views(args: argparse.Namespace, frames: Path) -> list[View]:
    """Renders `args.count` views that pass the map rules, and no earlier batch used, into frames/NNN."""
    width, height = view_size(args.scale)
    maps = scout_maps(args.renderer, args.game_data, args.scout_cache)
    used = [] if args.reuse else used_views(args.history, maps)
    views = select_views(maps, args.count, *window_tiles(width, height), random.Random(), exclude=used)
    # Kept after the batch as the record of which map views it holds.
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "views.txt").write_text("".join(f"{v.x} {v.y} {v.map}\n" for v in views))
    render_views(args.renderer, views, frames, width, height, POSES, args.game_data)
    return views


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["get-demo"]:
        return get_demo_command()
    args = parse_args(argv)
    try:
        args.game_data = find_game_data(args.game_data)
    except NoGameData as error:
        print(error, file=sys.stderr)
        return 1
    if args.out is None:
        args.out = default_out(args.no_import, args.scout_cache)
    if args.out.exists() and any(args.out.iterdir()):
        print(f"{args.out} is not empty; choose a new folder", file=sys.stderr)
        return 1

    frames, clips, live = args.out / "frames", args.out / "clips", args.out / "live"
    # Printed first, so a failed batch's leftovers can be found; they stay for diagnosis.
    print(f"Working in {args.out}")
    try:
        views = render_good_views(args, frames)
    except (NotEnoughViews, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    clips.mkdir(parents=True)
    live.mkdir(parents=True)
    pairs = []
    for i, view in enumerate(sorted(p for p in frames.iterdir() if p.is_dir())):
        clip = clips / f"{view.name}.mov"
        direction = random.choice(DIRECTIONS)
        make_clip(view, clip, args.brightness, args.scale, direction, seed=i)
        pairs.append(make_live_photo(clip, live, f"H2_{view.name}", FIRST_CAPTURE + timedelta(minutes=i)))
        print(f"{i + 1}/{args.count} pan {direction} {(view / 'map.txt').read_text().strip()} at {(view / 'view.txt').read_text().strip()}")

    # The rendered stages are only needed to build the Live Photos; a failure above keeps them for diagnosis.
    shutil.rmtree(frames)
    shutil.rmtree(clips)
    if args.no_import:
        remember(args.history, views, None)
        print(f"Built {len(pairs)} Live Photos in {live}")
        return 0

    import_pairs(pairs, args.album)
    remember(args.history, views, args.album)
    # Photos keeps its own copy of every imported file, and the history records the views.
    shutil.rmtree(args.out)
    print(f"Imported {len(pairs)} Live Photos into the Photos album {args.album!r}.")
    print("Next: select the iPhone in Finder's sidebar to sync the album (it must be ticked under Photos → Selected albums).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
