"""Build the lower zoom levels and viewer metadata from the full-resolution tiles.

Each level halves the one above it (box filter) and is saved as WebP.
Also writes docs/map.json with the map dimensions, jump-to places and the
lon/lat-to-pixel fit used by address search.
Run from the project root: .venv/bin/python scripts/04_pyramid.py
"""

import argparse
import json
import math
import multiprocessing as mp

import numpy as np
from PIL import Image

from config import DATA, HEIGHT, ORIGIN_LONLAT, SITE, TILE, TILES, UP_BEARING_DEG, WIDTH, geographic_bbox, lonlat_to_screen

MAX_LEVEL = math.ceil(math.log2(max(WIDTH, HEIGHT) / TILE))
WATER_RGB = (72, 132, 176)

PLACES: list[tuple[str, float, float]] = [
    ("Melbourne CBD", 144.9631, -37.8136), ("Southbank", 144.9590, -37.8230), ("Docklands", 144.9460, -37.8170),
    ("MCG & Richmond", 144.9834, -37.8200), ("Carlton", 144.9670, -37.7980), ("St Kilda", 144.9750, -37.8640),
    ("Port Melbourne", 144.9320, -37.8400), ("Williamstown", 144.8990, -37.8640), ("Footscray", 144.8990, -37.8000),
    ("Brighton", 144.9870, -37.9170), ("Monash Clayton", 145.1340, -37.9110), ("Chadstone", 145.0830, -37.8860),
    ("Box Hill", 145.1220, -37.8190), ("Ringwood", 145.2290, -37.8140), ("Dandenong", 145.2150, -37.9870),
    ("Dandenong Ranges", 145.3500, -37.8700), ("Frankston", 145.1260, -38.1440), ("Sorrento", 144.7410, -38.3430),
    ("Werribee", 144.6600, -37.9000), ("Melbourne Airport", 144.8430, -37.6700), ("Sunbury", 144.7280, -37.5780),
    ("Craigieburn", 144.9400, -37.6000), ("Lilydale", 145.3540, -37.7570), ("Pakenham", 145.4860, -38.0710),
    ("Geelong", 144.3600, -38.1470),
]


def level_size(level: int) -> tuple[int, int]:
    """Pixel dimensions of a pyramid level."""
    f = 2 ** (MAX_LEVEL - level)
    return math.ceil(WIDTH / f), math.ceil(HEIGHT / f)


def build_tile(job: tuple[int, int, int]) -> None:
    """Compose one tile from its four children on the level above."""
    level, x, y = job
    canvas = Image.new("RGB", (TILE * 2, TILE * 2), WATER_RGB)
    for dy in (0, 1):
        for dx in (0, 1):
            child = TILES / str(level + 1) / f"{2 * x + dx}_{2 * y + dy}.webp"
            if child.exists():
                canvas.paste(Image.open(child).convert("RGB"), (dx * TILE, dy * TILE))
    w, h = level_size(level)
    tw, th = min(TILE, w - x * TILE), min(TILE, h - y * TILE)
    small = canvas.resize((TILE, TILE), Image.BOX).crop((0, 0, tw, th))
    small.save(TILES / str(level) / f"{x}_{y}.webp", quality=72, method=4)


def fit_projection() -> dict:
    """Fit cubic polynomials mapping lon/lat to map pixels, for address search in the viewer."""
    w, s, e, n = geographic_bbox()
    lon, lat = np.meshgrid(np.linspace(w, e, 60), np.linspace(s, n, 60))
    lon, lat = lon.ravel(), lat.ravel()
    sx, sy = lonlat_to_screen(lon, lat)
    u, v = lon - ORIGIN_LONLAT[0], lat - ORIGIN_LONLAT[1]
    terms = [(i, j) for i in range(4) for j in range(4 - i)]
    a = np.column_stack([u**i * v**j for i, j in terms])
    cx = np.linalg.lstsq(a, sx, rcond=None)[0]
    cy = np.linalg.lstsq(a, sy, rcond=None)[0]
    return {"lon0": ORIGIN_LONLAT[0], "lat0": ORIGIN_LONLAT[1], "terms": terms, "cx": cx.tolist(), "cy": cy.tolist()}


MASK_CELL_X, MASK_CELL_Y = 100, 50  # screen pixels per mask cell: 100 m x 100 m on the ground


def write_built_mask() -> dict:
    """Write a coarse built-up mask (cells with several buildings) used to place nearby sites on streets."""
    bbox = np.load(DATA / "prep_buildings.npz")["bbox"]
    cx, cy = (bbox[:, 0] + bbox[:, 2]) / 2, (bbox[:, 1] + bbox[:, 3]) / 2
    w, h = math.ceil(WIDTH / MASK_CELL_X), math.ceil(HEIGHT / MASK_CELL_Y)
    counts, _, _ = np.histogram2d(cy, cx, bins=[h, w], range=[[0, h * MASK_CELL_Y], [0, w * MASK_CELL_X]])
    Image.fromarray(((counts >= 6) * 255).astype(np.uint8), "L").save(SITE / "built_mask.png", optimize=True)
    return {"file": "built_mask.png", "cellX": MASK_CELL_X, "cellY": MASK_CELL_Y}


def main() -> None:
    """Build all lower levels, then write viewer metadata (--meta-only skips the tiles)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta-only", action="store_true")
    if ap.parse_args().meta_only:
        write_meta()
        return
    with mp.get_context("fork").Pool(10) as pool:
        for level in range(MAX_LEVEL - 1, -1, -1):
            (TILES / str(level)).mkdir(parents=True, exist_ok=True)
            w, h = level_size(level)
            jobs = [(level, x, y) for y in range(math.ceil(h / TILE)) for x in range(math.ceil(w / TILE))]
            pool.map(build_tile, jobs, chunksize=8)
            print(f"level {level}: {len(jobs)} tiles ({w}x{h})", flush=True)
    write_meta()


def write_meta() -> None:
    """Write docs/map.json and the built-up mask."""
    places = []
    for name, lon, lat in PLACES:
        sx, sy = lonlat_to_screen(np.array([lon]), np.array([lat]))
        if 0 <= sx[0] < WIDTH and 0 <= sy[0] < HEIGHT:
            places.append({"name": name, "x": round(float(sx[0])), "y": round(float(sy[0]))})
    meta = {"width": WIDTH, "height": HEIGHT, "tile": TILE, "maxLevel": MAX_LEVEL,
            "upBearing": UP_BEARING_DEG, "places": places, "proj": fit_projection(), "mask": write_built_mask(),
            "bbox": [round(v, 4) for v in geographic_bbox()]}
    (SITE / "map.json").write_text(json.dumps(meta))
    print("wrote map.json with", len(places), "places")


if __name__ == "__main__":
    main()
