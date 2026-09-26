"""Builds a contact sheet of views just either side of each rule's threshold, for checking the rules by eye.

    uv run python -m h2live.calibrate <out dir> [--per-side 3]

Writes <out dir>/contact-sheet.png, <out dir>/candidates.json and full-size stills in <out dir>/stills.
"""

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from h2live.batch import GAME_DATA, RENDERER, scout_cache
from h2live.clip import view_size
from h2live.select import (FREQUENT_COPIES, MAX_DUPLICATE_TILES, MIN_ANIMATED_TERRAIN, RULES, TILE, View, Window, bmp_pixels, check,
                           duplicate_tile_share, empty_square, passing_windows, regular_patterns, scout_maps, window_tiles)

# Per rule, the value it judges and the (low, high) band counted as near its threshold: passing, failing.
NEAR = {
    "empty": (lambda v: v["empty"], (5, 5), (6, 6)),
    "clumped": (lambda v: v["blank patches"], (0.37, 0.45), (0.4501, 0.53)),
    "sparse": (lambda v: v["occupied"], (0.22, 0.27), (0.16, 0.2199)),
    # Near the line: a sprite with enough copies holding a large share of the objects' area.
    "frequency": (lambda v: v["top sprite share"] if v["top sprite copies"] >= FREQUENT_COPIES else -1,
                  (0.5, 0.65), (0.6501, 0.8)),
    # Passing views near the line hold three or more touching identical objects that form no row or block.
    "repetition": (lambda v: v["repetition"] or -v["identical touching"], (-99, -3), (1, 1)),
    "monoculture": (lambda v: v["share"], (0.55, 0.65), (0.6501, 0.72)),
    "few types": (lambda v: v["types"], (3, 3), (2, 2)),
}
THUMB = (280, 467)


def _near(rule: str, values: dict, passes: bool) -> bool:
    if rule == "no animation":
        # Just enough is two animated objects, just short is one; either way with too little water or lava to count.
        return values["animated objects"] == (2 if passes else 1) and values["animated terrain"] < MIN_ANIMATED_TERRAIN
    value_of, passing, failing = NEAR[rule]
    low, high = passing if passes else failing
    return low <= value_of(values) <= high


def _label(rule: str, values: dict) -> str:
    if rule == "no animation":
        return f"animated={values['animated objects']} objects, {values['animated terrain']} water/lava tiles"
    if rule == "monoculture":
        return f"top type share={values['share']:.0%}"
    if rule == "few types":
        return f"types={values['types']}"
    if rule == "empty":
        return f"largest empty square={values['empty']}"
    if rule == "clumped":
        return f"in blank 2x2 patches={values['blank patches']:.0%}"
    if rule == "frequency":
        return f"top sprite: {values['top sprite copies']} copies, {values['top sprite share']:.0%} of object area"
    if rule == "sparse":
        return f"tiles with objects={values['occupied']:.0%}"
    if values["repetition"]:
        return f"rows/blocks of identical objects={values['repetition']}"
    return f"no row/block; {values['identical touching']} identical objects touch"


def identical_touching(m, win: Window) -> int:
    """Objects in the window that touch an identical object."""
    present = np.flatnonzero((m.x0 < win.x + win.w) & (m.x1 >= win.x) & (m.y0 < win.y + win.h) & (m.y1 >= win.y)
                             & (m.signature >= 0))
    x0, y0, x1, y1, sig = (a[present].astype(np.int32) for a in (m.x0, m.y0, m.x1, m.y1, m.signature))
    touch = ((x0[:, None] <= x1[None, :] + 1) & (x0[None, :] <= x1[:, None] + 1) & (y0[:, None] <= y1[None, :] + 1)
             & (y0[None, :] <= y1[:, None] + 1) & (sig[:, None] == sig[None, :]))
    np.fill_diagonal(touch, False)
    return int(touch.any(axis=1).sum())


def find_candidates(maps, w: int, h: int, per_side: int, rng: random.Random) -> list[dict]:
    """Windows that fail exactly one rule by a little, and windows that pass with that rule at its edge."""
    # Fewer for the rules that rarely decide.
    wanted = {(rule, passes): per_side - 2 * (rule in ("monoculture", "few types", "no animation"))
              for rule in RULES for passes in (True, False)}
    found: dict = {key: [] for key in wanted}
    used_maps = set()
    order = list(maps)
    rng.shuffle(order)
    for m in order:
        if all(len(found[k]) >= n for k, n in wanted.items()):
            break
        grids = passing_windows(m, w, h)
        if grids["all"].size == 0:
            continue
        others_pass = {rule: np.logical_and.reduce([grids[r] for r in RULES if r != rule]) for rule in RULES}
        for rule in RULES:
            for passes in (True, False):
                key = (rule, passes)
                if len(found[key]) >= wanted[key] or m.path in used_maps:
                    continue
                mask = others_pass[rule] & (grids[rule] if passes else ~grids[rule])
                ys, xs = np.nonzero(mask)
                for i in rng.sample(range(len(xs)), min(len(xs), 60)):
                    win = Window(int(xs[i]), int(ys[i]), w, h)
                    verdict = check(m, win)
                    verdict.values["identical touching"] = identical_touching(m, win)
                    if _near(rule, verdict.values, passes):
                        found[key].append({"map": m.path, "x": win.x, "y": win.y, "rule": rule,
                                           "verdict": "PASS" if passes else "FAIL", "label": _label(rule, verdict.values),
                                           "values": verdict.values})
                        used_maps.add(m.path)
                        break
    return [c for key in wanted for c in found[key]]


def render_stills(renderer: Path, views: list[View], width: int, height: int, out: Path) -> list[Path]:
    views_file = out / "views.txt"
    views_file.write_text("".join(f"{v.x} {v.y} {v.map}\n" for v in views))
    subprocess.run([str(renderer), "--render-views", str(views_file), str(out / "stills"), str(width), str(height), "1"],
                   check=True, capture_output=True, env={**os.environ, "FHEROES2_DATA": str(GAME_DATA)})
    return [out / "stills" / f"{i:03d}" / "f00.bmp" for i in range(len(views))]


def bmp_image(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def outlines(m, win: Window, rule: str) -> list[tuple[int, int, int, int]]:
    """Tile boxes (x0, y0, x1, y1 inclusive, relative to the window) that show why a rule decided."""
    if rule == "empty":
        side, x, y = empty_square(m, win)
        return [(x, y, x + side - 1, y + side - 1)] if side else []
    if rule == "repetition":
        return [(int(m.x0[i]) - win.x, int(m.y0[i]) - win.y, int(m.x1[i]) - win.x, int(m.y1[i]) - win.y)
                for pattern in regular_patterns(m, win) for i in pattern]
    if rule == "frequency":
        present = np.flatnonzero((m.x0 < win.x + win.w) & (m.x1 >= win.x) & (m.y0 < win.y + win.h) & (m.y1 >= win.y)
                                 & (m.signature >= 0))
        areas = (m.x1[present].astype(int) - m.x0[present] + 1) * (m.y1[present].astype(int) - m.y0[present] + 1)
        signatures, inverse = np.unique(m.signature[present], return_inverse=True)
        top = signatures[np.argmax(np.bincount(inverse, weights=areas))]
        return [(int(m.x0[i]) - win.x, int(m.y0[i]) - win.y, int(m.x1[i]) - win.x, int(m.y1[i]) - win.y)
                for i in present if m.signature[i] == top]
    if rule == "clumped":
        ys, xs = np.nonzero(m.in_blank_patch[win.y:win.y + win.h, win.x:win.x + win.w])
        return [(int(x), int(y), int(x), int(y)) for x, y in zip(xs, ys)]
    return []


def contact_sheet(items: list[dict], out: Path, columns: int = 8) -> None:
    font_path = "/System/Library/Fonts/Helvetica.ttc"
    big = ImageFont.truetype(font_path, 22) if Path(font_path).exists() else ImageFont.load_default()
    small = ImageFont.truetype(font_path, 14) if Path(font_path).exists() else ImageFont.load_default()
    label_h, gap = 64, 12
    rows = (len(items) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * (THUMB[0] + gap) + gap, rows * (THUMB[1] + label_h + gap) + gap), "white")
    draw = ImageDraw.Draw(sheet)
    for n, item in enumerate(items):
        left = gap + (n % columns) * (THUMB[0] + gap)
        top = gap + (n // columns) * (THUMB[1] + label_h + gap)
        thumb = item["image"].resize(THUMB, Image.LANCZOS)
        sx, sy = THUMB[0] / item["image"].width * TILE, THUMB[1] / item["image"].height * TILE
        # Blank-patch tiles are shaded; squares and repeated objects are outlined.
        shade = Image.new("RGBA", THUMB, (0, 0, 0, 0))
        boxes = ImageDraw.Draw(shade)
        for x0, y0, x1, y1 in item["outlines"]:
            box = (x0 * sx, y0 * sy, (x1 + 1) * sx - 1, (y1 + 1) * sy - 1)
            if item["rule"] == "clumped":
                boxes.rectangle(box, fill=(255, 0, 255, 90))
            else:
                boxes.rectangle(box, outline=(255, 0, 255, 255), width=2)
        thumb = Image.alpha_composite(thumb.convert("RGBA"), shade).convert("RGB")
        sheet.paste(thumb, (left, top + label_h))
        colour = (0, 120, 0) if item["verdict"] == "PASS" else (190, 0, 0)
        draw.text((left, top), f"{item['id']:02d} {item['verdict']} {item['rule']}", fill=colour, font=big)
        draw.text((left, top + 26), item["label"], fill="black", font=small)
        draw.text((left, top + 44), f"{Path(item['map']).name[:18]} @ {item['x']},{item['y']}  dup tiles {item['duplicate_tiles']:.0%}",
                  fill=(90, 90, 90), font=small)
    sheet.save(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m h2live.calibrate", description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("--per-side", type=int, default=3)
    parser.add_argument("--renderer", type=Path, default=RENDERER)
    parser.add_argument("--scout-cache", type=Path, default=scout_cache())
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    width, height = view_size(3)
    w, h = window_tiles(width, height)
    maps = scout_maps(args.renderer, GAME_DATA, args.scout_cache)
    candidates = find_candidates(maps, w, h, args.per_side, rng)

    # The still check: render views that pass every map rule and keep those near its threshold.
    pool = []
    for m in rng.sample(maps, len(maps)):
        ys, xs = np.nonzero(passing_windows(m, w, h)["all"])
        if len(xs):
            i = rng.randrange(len(xs))
            pool.append(View(m.path, int(xs[i]), int(ys[i])))
        if len(pool) == 300:
            break

    (args.out / "stills").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        (scratch / "pool").mkdir()
        shares = [duplicate_tile_share(bmp_pixels(p)) for p in render_stills(args.renderer, pool, width, height, scratch / "pool")]
        by_map = {m.path: m for m in maps}
        near_pass = [(v, s) for v, s in zip(pool, shares) if MAX_DUPLICATE_TILES - 0.07 < s <= MAX_DUPLICATE_TILES]
        near_fail = [(v, s) for v, s in zip(pool, shares) if MAX_DUPLICATE_TILES < s <= MAX_DUPLICATE_TILES + 0.1]
        for group, verdict in ((near_pass, "PASS"), (near_fail, "FAIL")):
            for view, share in group[:args.per_side - 1]:
                values = check(by_map[view.map], Window(view.x, view.y, w, h)).values
                candidates.append({"map": view.map, "x": view.x, "y": view.y, "rule": "repeated tiles", "verdict": verdict,
                                   "label": f"duplicate 32px tiles={share:.0%} (still check)", "values": values})

        views = [View(c["map"], c["x"], c["y"]) for c in candidates]
        (scratch / "sheet").mkdir()
        stills = render_stills(args.renderer, views, width, height, scratch / "sheet")
        for n, (candidate, still) in enumerate(zip(candidates, stills), start=1):
            candidate["id"] = n
            candidate["duplicate_tiles"] = round(duplicate_tile_share(bmp_pixels(still)), 3)
            candidate["image"] = bmp_image(still)
            candidate["image"].save(args.out / "stills" / f"{n:02d}.png")
            win = Window(candidate["x"], candidate["y"], w, h)
            candidate["outlines"] = outlines(by_map[candidate["map"]], win, candidate["rule"])
        contact_sheet(candidates, args.out / "contact-sheet.png")

    for candidate in candidates:
        del candidate["image"]
        candidate["outlines"] = [list(box) for box in candidate["outlines"]]
    (args.out / "candidates.json").write_text(json.dumps(candidates, indent=1))
    pool_stats = {"rendered": len(shares), "median duplicate share": float(np.median(shares)),
                  "over threshold": float(np.mean(np.array(shares) > MAX_DUPLICATE_TILES))}
    print(json.dumps(pool_stats))
    print(f"{len(candidates)} candidates in {args.out / 'contact-sheet.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
