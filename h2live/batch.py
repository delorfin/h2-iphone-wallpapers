"""Renders a batch of HoMM2 map views and turns them into iPhone Live Photo wallpapers."""

import argparse
import os
import random
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from h2live.clip import DIRECTIONS, make_clip, view_size
from h2live.livephoto import make_live_photo
from h2live.photos import import_pairs

REPO = Path(__file__).resolve().parents[2]
# Non-bundle macOS builds only look in ~/.fheroes2 unless told otherwise.
GAME_DATA = Path.home() / "Library/Application Support/fheroes2"
# iOS plays about 0.2 s of the clip over about 2 s on the lock screen; at 40 steps per second
# that looks like the game's own speed (one step per 250 ms).
STEPS_PER_SECOND = 40
# Keeps every batch together on one day of the Photos and Google Photos timelines, away from real photos.
# Noon keeps all items on that day in any timezone.
FIRST_CAPTURE = datetime(1996, 1, 1, 12)


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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.out.exists() and any(args.out.iterdir()):
        print(f"{args.out} is not empty; choose a new folder", file=sys.stderr)
        return 1

    frames, clips, live = args.out / "frames", args.out / "clips", args.out / "live"
    width, height = view_size(args.scale)
    rendered = subprocess.run(
        [str(args.renderer), "--render-wallpapers", str(frames), str(args.count), str(width), str(height),
         str(STEPS_PER_SECOND)],
        env={**os.environ, "FHEROES2_DATA": str(GAME_DATA)},
    )
    if rendered.returncode != 0:
        print(f"renderer failed with exit code {rendered.returncode}", file=sys.stderr)
        return 1

    clips.mkdir(parents=True)
    live.mkdir(parents=True)
    pairs = []
    for i, view in enumerate(sorted(p for p in frames.iterdir() if p.is_dir())):
        clip = clips / f"{view.name}.mov"
        direction = random.choice(DIRECTIONS)
        make_clip(view, clip, args.brightness, args.scale, direction, STEPS_PER_SECOND)
        pairs.append(make_live_photo(clip, live, f"H2_{view.name}", FIRST_CAPTURE + timedelta(minutes=i)))
        print(f"{i + 1}/{args.count} pan {direction} {(view / 'map.txt').read_text().strip()}")

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
