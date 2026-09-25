"""Renders a batch of HoMM2 map views and turns them into iPhone Live Photo wallpapers."""

import argparse
import os
import random
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from h2live.clip import DIRECTIONS, make_clip, view_size
from h2live.livephoto import make_live_photo
from h2live.photos import import_pairs
from h2live.select import (MAX_DUPLICATE_TILES, NotEnoughViews, bmp_pixels, duplicate_tile_share, scout_maps,
                           select_views, window_tiles)

REPO = Path(__file__).resolve().parents[2]
# Non-bundle macOS builds only look in ~/.fheroes2 unless told otherwise.
GAME_DATA = Path.home() / "Library/Application Support/fheroes2"
# iOS plays about 0.2 s of the clip over about 2 s on the lock screen, crossfading between video
# frames. 30 steps per second (each pose held for 2 frames) balanced speed against smearing best.
STEPS_PER_SECOND = 30
# Keeps every batch together on one day of the Photos and Google Photos timelines, away from real photos.
# Noon keeps all items on that day in any timezone.
FIRST_CAPTURE = datetime(1996, 1, 1, 12)
SCOUT_CACHE = Path(os.environ.get("H2LIVE_SCOUT_CACHE", Path.home() / "Library/Caches/h2live"))
# Rounds of rendering replacements for views whose still repeats too much.
MAX_ROUNDS = 10


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["batch"]:
        argv = argv[1:]
    parser = argparse.ArgumentParser(prog="h2live batch", description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="empty or new folder for this batch")
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--scale", type=int, choices=(2, 3, 4), default=3)
    parser.add_argument("--brightness", type=int, default=70)
    parser.add_argument("--album", default=f"H2 {date.today():%Y-%m-%d}")
    parser.add_argument("--no-import", action="store_true", help="build the files but skip Photos")
    parser.add_argument("--renderer", type=Path, default=REPO / "fheroes2", help="built by ios-livephoto/build.sh")
    parser.add_argument("--scout-cache", type=Path, default=SCOUT_CACHE, help="where scouted maps are kept between batches")
    return parser.parse_args(argv)


def render_good_views(args: argparse.Namespace, frames: Path) -> None:
    """Renders `args.count` views that pass the map rules and the still check into frames/NNN."""
    width, height = view_size(args.scale)
    window = window_tiles(width, height)
    env = {**os.environ, "FHEROES2_DATA": str(GAME_DATA)}
    maps = scout_maps(args.renderer, GAME_DATA, args.scout_cache)
    rng = random.Random()
    accepted, rejected = [], []
    candidates = args.out / "candidates"
    for round_number in range(MAX_ROUNDS):
        try:
            views = select_views(maps, args.count - len(accepted), *window, rng, exclude=[v for v, _ in accepted] + rejected)
        except NotEnoughViews as error:
            raise NotEnoughViews(f"Only {len(accepted)} of {args.count} views passed. {error}") from None
        views_file = candidates / f"round{round_number}.txt"
        views_file.parent.mkdir(parents=True, exist_ok=True)
        views_file.write_text("".join(f"{v.x} {v.y} {v.map}\n" for v in views))
        rendered = subprocess.run(
            [str(args.renderer), "--render-views", str(views_file), str(candidates / f"round{round_number}"),
             str(width), str(height), str(STEPS_PER_SECOND)],
            env=env,
        )
        if rendered.returncode != 0:
            raise RuntimeError(f"renderer failed with exit code {rendered.returncode}")
        for i, view in enumerate(views):
            view_dir = candidates / f"round{round_number}" / f"{i:03d}"
            share = duplicate_tile_share(bmp_pixels(view_dir / "f00.bmp"))
            if share > MAX_DUPLICATE_TILES:
                print(f"skipped {view.map} at {view.x} {view.y}: {share:.0%} of its tiles repeat")
                rejected.append(view)
                shutil.rmtree(view_dir)
            else:
                accepted.append((view, view_dir))
        if len(accepted) == args.count:
            break
    else:
        raise NotEnoughViews(f"Only {len(accepted)} of {args.count} views passed after {MAX_ROUNDS} rounds of rendering.")

    frames.mkdir(parents=True)
    for i, (_, view_dir) in enumerate(accepted):
        view_dir.rename(frames / f"{i:03d}")
    shutil.rmtree(candidates)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.out.exists() and any(args.out.iterdir()):
        print(f"{args.out} is not empty; choose a new folder", file=sys.stderr)
        return 1

    frames, clips, live = args.out / "frames", args.out / "clips", args.out / "live"
    try:
        render_good_views(args, frames)
    except (NotEnoughViews, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    clips.mkdir(parents=True)
    live.mkdir(parents=True)
    pairs = []
    for i, view in enumerate(sorted(p for p in frames.iterdir() if p.is_dir())):
        clip = clips / f"{view.name}.mov"
        direction = random.choice(DIRECTIONS)
        make_clip(view, clip, args.brightness, args.scale, direction, STEPS_PER_SECOND)
        pairs.append(make_live_photo(clip, live, f"H2_{view.name}", FIRST_CAPTURE + timedelta(minutes=i)))
        print(f"{i + 1}/{args.count} pan {direction} {(view / 'map.txt').read_text().strip()} at {(view / 'view.txt').read_text().strip()}")

    if args.no_import:
        print(f"Built {len(pairs)} Live Photos in {live}")
        return 0

    import_pairs(pairs, args.album)
    print(f"Imported {len(pairs)} Live Photos into the Photos album {args.album!r}.")
    print("Next: in Photos on the Mac, select the album's items → Share → AirDrop → your iPhone,")
    print("then on the iPhone add them to the H2 album.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
