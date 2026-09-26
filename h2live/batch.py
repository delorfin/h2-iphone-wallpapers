"""Renders a batch of HoMM2 map views and turns them into iPhone Live Photo wallpapers."""

import argparse
import os
import random
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from h2live.clip import DIRECTIONS, POSES, make_clip, view_size
from h2live.gamedata import NoGameData, find_game_data, get_demo_command
from h2live.livephoto import make_live_photo
from h2live.photos import PhotosImportError, import_pairs
from h2live.select import ENGINE_TIMEOUT, NotEnoughViews, View, scout_maps, select_views, window_tiles

REPO = Path(__file__).resolve().parents[1]
# Built by build.sh.
RENDERER = REPO / "engine" / "fheroes2"
# Command-line tools the Live Photos are built with, and the Homebrew packages that provide them.
TOOLS = {"ffmpeg": "ffmpeg", "ffprobe": "ffmpeg", "MP4Box": "gpac", "exiftool": "exiftool", "magick": "imagemagick"}
# Keeps the wallpapers together at the start of the Photos and Google Photos timelines, away from real photos.
# Each wallpaper is one minute after the previous one, across batches: the capture time is the only identity
# a shortcut can read on the phone, and minutes after this = the wallpaper's line in the history.
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
    for line in view_lines(history):
        x, y, name = line.split(" ", 2)
        if name in paths:
            views.append(View(paths[name], int(x), int(y)))
    return views


def view_lines(history: Path) -> list[str]:
    """The history's "x y mapfile" lines, without the note heading each batch or blank lines."""
    lines = history.read_text().splitlines() if history.exists() else []
    return [line for line in lines if line.strip() and not line.startswith("#")]


def views_in(history: Path) -> int:
    return len(view_lines(history))


def remember(history: Path, views: list[View], where: str) -> None:
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a") as out:
        out.write(f"# {datetime.now():%Y-%m-%d %H:%M} {where}, {len(views)} views\n")
        out.writelines(f"{v.x} {v.y} {Path(v.map).name}\n" for v in views)


def default_out(no_import: bool, cache: Path) -> Path:
    """A work folder in the cache, removed after import; or, for --no-import, an export folder in Downloads."""
    stamp = f"{datetime.now():%Y-%m-%d-%H%M%S}"
    if no_import:
        return Path(os.environ.get("H2LIVE_EXPORT_DIR", Path.home() / "Downloads")) / f"h2live-{stamp}"
    return cache / "work" / stamp


def number_in(low: int, high: int | None = None):
    def parse(text: str) -> int:
        value = int(text)
        if value < low or (high is not None and value > high):
            raise argparse.ArgumentTypeError(f"must be {low}-{high}" if high else f"must be at least {low}")
        return value
    return parse


def parse_args(argv: list[str]) -> argparse.Namespace:
    if argv[:1] == ["batch"]:
        argv = argv[1:]
    parser = argparse.ArgumentParser(
        prog="h2live batch", description=__doc__,
        epilog="The other command, h2live get-demo, downloads the free HoMM2 demo to render with (see the README).")
    parser.add_argument("--out", type=Path, help="empty or new folder to work in (default: a folder in the cache, "
                        "or ~/Downloads/h2live-<date> with --no-import)")
    parser.add_argument("--count", type=number_in(1), default=60, help="wallpapers to make (default: 60)")
    parser.add_argument("--scale", type=int, choices=(2, 3, 4), default=3, help="screen pixels per map pixel (default: 3)")
    parser.add_argument("--brightness", type=number_in(1, 100), default=70,
                        help="percent, dims the map so the clock stays readable (default: 70)")
    parser.add_argument("--album", default="H2", help="Photos album to add them to (default: H2)")
    parser.add_argument("--no-import", action="store_true", help="build the files but skip Photos")
    parser.add_argument("--renderer", type=Path, default=RENDERER, help="built by build.sh")
    parser.add_argument("--scout-cache", type=Path, default=scout_cache(), help="where scouted maps are kept between batches")
    parser.add_argument("--game-data", type=Path, help="folder with the game's DATA and MAPS (default: fheroes2's "
                        "data folder, else the demo from h2live get-demo)")
    parser.add_argument("--history", type=Path, default=history_file(), help="views used by earlier batches")
    parser.add_argument("--reuse", action="store_true", help="allow views used by earlier batches")
    parser.add_argument("--seed", type=int, help="makes the choice of views and pans repeatable")
    return parser.parse_args(argv)


def missing_setup(renderer: Path) -> str | None:
    """What's missing before a batch can run, as a message; None if nothing is."""
    if not renderer.exists():
        return f"No renderer at {renderer}; build it first with ./build.sh"
    missing = [tool for tool in TOOLS if shutil.which(tool) is None]
    if missing:
        packages = " ".join(sorted({TOOLS[tool] for tool in missing}))
        return f"Missing tools: {', '.join(missing)}. Install them with: brew install {packages}"
    return None


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
                env={**os.environ, "FHEROES2_DATA": str(game_data)}, capture_output=True, text=True, timeout=ENGINE_TIMEOUT,
            )
            if rendered.returncode != 0:
                raise RuntimeError(f"renderer failed with exit code {rendered.returncode} on {view.map}: {rendered.stderr[-500:]}")
            shutil.move(Path(scratch) / "out" / "000", out / f"{index:03d}")

    out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        list(pool.map(lambda item: render_one(*item), enumerate(views)))


def render_good_views(args: argparse.Namespace, frames: Path, rng: random.Random) -> list[View]:
    """Renders `args.count` views that pass the map rules, and no earlier batch used, into frames/NNN."""
    width, height = view_size(args.scale)
    maps = scout_maps(args.renderer, args.game_data, args.scout_cache)
    used = [] if args.reuse else used_views(args.history, maps)
    views = select_views(maps, args.count, *window_tiles(width, height), rng, exclude=used)
    # Kept after the batch as the record of which map views it holds.
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "views.txt").write_text("".join(f"{v.x} {v.y} {v.map}\n" for v in views))
    render_views(args.renderer, views, frames, width, height, POSES, args.game_data)
    return views


def tool_failure(error: subprocess.CalledProcessError) -> str:
    output = error.stderr or error.output or b""
    text = output.decode(errors="replace") if isinstance(output, bytes) else output
    return f"{Path(str(error.cmd[0])).name} failed: {text.strip()[-500:] or f'exit code {error.returncode}'}"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["get-demo"]:
        return get_demo_command()
    args = parse_args(argv)
    problem = missing_setup(args.renderer)
    if problem:
        print(problem, file=sys.stderr)
        return 1
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
    rng = random.Random(args.seed)
    first_capture = FIRST_CAPTURE + timedelta(minutes=views_in(args.history))
    try:
        views = render_good_views(args, frames, rng)
    except (NotEnoughViews, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    clips.mkdir(parents=True)
    live.mkdir(parents=True)
    pairs = []
    try:
        for i, view in enumerate(sorted(p for p in frames.iterdir() if p.is_dir())):
            clip = clips / f"{view.name}.mov"
            direction = rng.choice(DIRECTIONS)
            make_clip(view, clip, args.brightness, args.scale, direction, seed=i)
            pairs.append(make_live_photo(clip, live, f"H2_{view.name}", first_capture + timedelta(minutes=i)))
            print(f"{i + 1}/{args.count} pan {direction} {(view / 'map.txt').read_text().strip()} "
                  f"at {(view / 'view.txt').read_text().strip()}")
    except subprocess.CalledProcessError as error:
        print(f"{tool_failure(error)}\nThe batch's files are kept in {args.out}", file=sys.stderr)
        return 1

    # The rendered stages are only needed to build the Live Photos; a failure above keeps them for diagnosis.
    shutil.rmtree(frames)
    shutil.rmtree(clips)
    if args.no_import:
        remember(args.history, views, "not imported")
        print(f"Built {len(pairs)} Live Photos in {live}")
        return 0

    try:
        import_pairs(pairs, args.album)
    except PhotosImportError as error:
        # The Live Photos already carry their capture times, so the history counts them either way.
        remember(args.history, views, f"import into album {args.album} failed")
        print(f"{error}\nThe Live Photos are in {live}; you can also drag that folder into Photos.", file=sys.stderr)
        return 1
    remember(args.history, views, f"album {args.album}")
    # Photos keeps its own copy of every imported file, and the history records the views.
    shutil.rmtree(args.out)
    print(f"Imported {len(pairs)} Live Photos into the Photos album {args.album!r}.")
    print("Next: select the iPhone in Finder's sidebar to sync the album (it must be ticked under Photos → Selected albums).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
