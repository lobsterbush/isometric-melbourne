"""Render the isometric pixel-art map into 512px tiles at full resolution.

Reads data/prep_*.npz and writes docs/tiles/<max_level>/<x>_<y>.webp (lossless).
Run from the project root:
    .venv/bin/python scripts/03_render.py                 # whole map
    .venv/bin/python scripts/03_render.py --preview LON LAT out.png   # one chunk
"""

import argparse
import math
import multiprocessing as mp
import time
from pathlib import Path

import numpy as np
import shapely
from PIL import Image, ImageDraw

from config import DATA, HEIGHT, SCALE, TILE, TILES, WIDTH, Z_SCALE, lonlat_to_screen
from palette import G, M, N_GROUND, PALETTE, ROOF, ROOF_NAMES, SHADOW_LUT, TREE, TREE_NAMES, WALL, WALL_NAMES

C = 2048  # chunk size in pixels
PAD = 96  # extra border rendered around each chunk
S = C + 2 * PAD
NX, NY = math.ceil(WIDTH / C), math.ceil(HEIGHT / C)
MAX_LEVEL = math.ceil(math.log2(max(WIDTH, HEIGHT) / TILE))
K = Z_SCALE * SCALE

WALL_IDX = [WALL[n] for n in WALL_NAMES]
ROOF_IDX = [ROOF[n] for n in ROOF_NAMES]

# road rank -> (casing width, fill width, fill colour)
ROAD_STYLE: dict[int, tuple[int, int, int]] = {
    0: (0, 1, G["DIRT"]), 1: (0, 1, G["PATH"]), 2: (0, 1, G["PATH"]), 3: (0, 3, G["PAVE"]),
    4: (0, 2, G["ROAD"]), 5: (6, 4, G["ROAD"]), 6: (7, 5, G["ROAD"]), 7: (8, 6, G["ROAD"]),
    8: (9, 7, G["ROAD_MAJOR"]), 9: (10, 8, G["ROAD_MAJOR"]), 10: (11, 9, G["ROAD_MAJOR"]),
}

# probability of a procedural tree per 8m grid cell, by ground colour
TREE_PROB = np.zeros(256, np.float32)
for _name, _p in {"FOREST": 0.9, "SCRUB": 0.3, "WOODLAND": 0.5, "PARK": 0.16, "PARK_S": 0.16, "RESID": 0.11, "LAND": 0.006,
                  "LAND_S": 0.006, "GOLF": 0.04, "CEMETERY": 0.12, "INSTIT": 0.07, "WETLAND": 0.06,
                  "ORCHARD": 0.5, "FARM": 0.004, "FARM_S": 0.004, "COMM": 0.015}.items():
    TREE_PROB[G[_name]] = _p

L: dict[str, dict[str, np.ndarray]] = {}
INDEX: dict[str, dict[int, np.ndarray]] = {}
RAND = np.random.default_rng(7).integers(0, 256, (256, 256), dtype=np.uint8)


def make_waves() -> np.ndarray:
    """Tileable 128x64 mask of short horizontal wave dashes."""
    rng = np.random.default_rng(3)
    m = np.zeros((64, 128), bool)
    for _ in range(46):
        y, x, n = rng.integers(0, 64), rng.integers(0, 128), rng.integers(3, 7)
        m[y, np.arange(x, x + n) % 128] = True
    return m


WAVES = make_waves()


def make_tree_sprites() -> list[tuple[Image.Image, Image.Image, int, int]]:
    """Build tree sprites as (image, mask, width, height) for each family and size."""
    sprites = []
    for name in TREE_NAMES:
        dark, mid, light = TREE[name]
        for w in (5, 7, 9):
            h = w + 2
            im = Image.new("P", (w, h), 0)
            mk = Image.new("L", (w, h), 0)
            for target, on in ((im, None), (mk, 255)):
                d = ImageDraw.Draw(target)
                d.point((w // 2, h - 1), fill=on or M["TRUNK"])
                d.point((w // 2, h - 2), fill=on or M["TRUNK"])
                d.ellipse((0, 0, w - 1, w - 1), fill=on or dark)
                if on is None:
                    d.ellipse((0, 0, w - 2, w - 2), fill=mid)
                    d.ellipse((1, 1, max(2, w // 2), max(2, w // 2)), fill=light)
            sprites.append((im, mk, w, h))
    return sprites


TREE_SPRITES = make_tree_sprites()
TREE_SHADOW = Image.new("L", (7, 4), 0)
ImageDraw.Draw(TREE_SHADOW).ellipse((0, 0, 6, 3), fill=255)


def load() -> None:
    """Load prepared layers and build per-chunk spatial indexes."""
    for name in ("land", "land_cover", "land_use", "natural", "water", "water_lines", "segments", "buildings", "trees"):
        L[name] = dict(np.load(DATA / f"prep_{name}.npz"))
    for name, layer in L.items():
        if name == "trees":
            xy = layer["xy"]
            bbox = np.hstack([xy, xy])
        elif name == "buildings":
            bbox = layer["bbox"].copy()
            reach = np.minimum(layer["h"], 90.0)
            bbox[:, 1] -= layer["h"] + 4
            bbox[:, 2] += reach + 4
        else:
            bbox = layer["bbox"]
        INDEX[name] = build_index(bbox)


def build_index(bbox: np.ndarray) -> dict[int, np.ndarray]:
    """Map chunk id -> indices of features whose bbox touches the padded chunk."""
    cx0 = np.floor((bbox[:, 0] - PAD) / C).astype(np.int64)
    cx1 = np.floor((bbox[:, 2] + PAD) / C).astype(np.int64)
    cy0 = np.floor((bbox[:, 1] - PAD) / C).astype(np.int64)
    cy1 = np.floor((bbox[:, 3] + PAD) / C).astype(np.int64)
    cx0, cy0 = np.maximum(cx0, 0), np.maximum(cy0, 0)
    cx1, cy1 = np.minimum(cx1, NX - 1), np.minimum(cy1, NY - 1)
    valid = (cx0 <= cx1) & (cy0 <= cy1)
    single = valid & (cx0 == cx1) & (cy0 == cy1)
    buckets: dict[int, list] = {}
    ids = np.flatnonzero(single)
    keys = cy0[ids] * NX + cx0[ids]
    order = np.argsort(keys, kind="stable")
    ids, keys = ids[order], keys[order]
    cuts = np.flatnonzero(np.diff(keys)) + 1
    for grp in np.split(ids, cuts):
        if len(grp):
            buckets[int(cy0[grp[0]] * NX + cx0[grp[0]])] = [grp]
    for i in np.flatnonzero(valid & ~single):
        for cy in range(cy0[i], cy1[i] + 1):
            for cx in range(cx0[i], cx1[i] + 1):
                buckets.setdefault(cy * NX + cx, []).append(np.array([i]))
    return {k: np.sort(np.concatenate(v)) for k, v in buckets.items()}


def draw_polys(img: Image.Image, d: ImageDraw.ImageDraw, name: str, key: int, x0: int, y0: int) -> None:
    """Draw a polygon layer's parts for one chunk, honouring holes."""
    layer = L[name]
    xy, ro, po, code = layer["xy"], layer["ring_off"], layer["part_off"], layer["code"]
    off = np.array([x0, y0], np.float32)
    for i in INDEX[name].get(key, ()):
        r0, r1 = po[i], po[i + 1]
        col = int(code[i])
        a, b = ro[r0], ro[r0 + 1]
        if r1 - r0 == 1 and b - a < 300:
            if b - a >= 3:
                d.polygon((xy[a:b] - off).ravel().tolist(), fill=col)
            continue
        try:
            poly = shapely.Polygon(xy[a:b] - off, [xy[ro[r] : ro[r + 1]] - off for r in range(r0 + 1, r1) if ro[r + 1] - ro[r] >= 4])
            clipped = shapely.clip_by_rect(poly, -4, -4, S + 4, S + 4)
        except Exception:
            d.polygon((xy[a:b] - off).ravel().tolist(), fill=col)
            continue
        for part in shapely.get_parts(clipped):
            if part.geom_type != "Polygon" or part.is_empty:
                continue
            ext = np.asarray(part.exterior.coords).ravel().tolist()
            if not part.interiors:
                d.polygon(ext, fill=col)
            else:
                mask = Image.new("L", (S, S), 0)
                md = ImageDraw.Draw(mask)
                md.polygon(ext, fill=255)
                for hole in part.interiors:
                    md.polygon(np.asarray(hole.coords).ravel().tolist(), fill=0)
                img.paste(col, (0, 0), mask)


def texture(arr: np.ndarray, x0: int, y0: int) -> None:
    """Add shoreline foam, wave dashes and grass speckle in place."""
    ys = (np.arange(S) + y0) % 256
    xs = (np.arange(S) + x0) % 256
    rnd = RAND[np.ix_(ys, xs)]
    water = arr == G["WATER"]
    land = ~water & (arr != G["POOL"])
    near = np.zeros_like(water)
    near[1:, :] |= land[:-1, :]
    near[:-1, :] |= land[1:, :]
    near[:, 1:] |= land[:, :-1]
    near[:, :-1] |= land[:, 1:]
    waves = WAVES[np.ix_((np.arange(S) + y0) % 64, (np.arange(S) + x0) % 128)]
    arr[water & waves] = G["WATER_L"]
    arr[water & near] = G["WATER_SHORE"]
    for base, speck, thresh in (("LAND", "LAND_S", 34), ("PARK", "PARK_S", 40), ("FARM", "FARM_S", 30)):
        arr[(arr == G[base]) & (rnd < thresh)] = G[speck]
    rows = ((np.arange(S) + y0) % 4 == 0)[:, None]
    arr[(arr == G["ORCHARD"]) & rows] = G["PARK_S"]


def draw_lines(d: ImageDraw.ImageDraw, key: int, x0: int, y0: int) -> None:
    """Draw waterways, roads, railways and tram tracks."""
    off = np.array([x0, y0], np.float32)
    wl = L["water_lines"]
    for i in INDEX["water_lines"].get(key, ()):
        pts = (wl["xy"][wl["off"][i] : wl["off"][i + 1]] - off).ravel().tolist()
        d.line(pts, fill=G["WATER"], width=int(wl["code"][i]))
    seg = L["segments"]
    ids = INDEX["segments"].get(key, np.zeros(0, np.int64))
    code = seg["code"][ids]
    paths = [(seg["xy"][seg["off"][i] : seg["off"][i + 1]] - off).ravel().tolist() for i in ids]
    for pts, c in zip(paths, code):
        if c <= 10 and ROAD_STYLE[int(c)][0]:
            d.line(pts, fill=G["CASING"], width=ROAD_STYLE[int(c)][0], joint="curve")
    for pts, c in zip(paths, code):
        c = int(c)
        if c <= 10:
            d.line(pts, fill=ROAD_STYLE[c][2], width=ROAD_STYLE[c][1], joint="curve")
            if c >= 9:
                d.line(pts, fill=G["ROAD_LINE"], width=1)
        elif c == 20:
            d.line(pts, fill=G["RAIL_BED"], width=4, joint="curve")
            d.line(pts, fill=G["RAIL"], width=2)
        else:
            d.line(pts, fill=G["TRAM"], width=1)


def cell_hash(a: np.ndarray, b: np.ndarray, seed: int) -> np.ndarray:
    """Deterministic uniform [0, 1) hash for integer grid cells."""
    h = (a.astype(np.int64) + (1 << 24)).astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)
    h ^= ((b.astype(np.int64) + (1 << 24)).astype(np.uint64) + np.uint64(seed)) * np.uint64(0xC2B2AE3D27D4EB4F)
    h ^= h >> np.uint64(29)
    h *= np.uint64(0xBF58476D1CE4E5B9)
    h ^= h >> np.uint64(32)
    return (h >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def place_trees(ground: np.ndarray, blocked: np.ndarray, key: int, x0: int, y0: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return tree (x, y, sprite index) arrays in chunk pixel coordinates."""
    gx = np.arange(x0 // 8, (x0 + S) // 8 + 1)
    gy = np.arange(y0 // 4, (y0 + S) // 4 + 1)
    cx, cy = np.meshgrid(gx, gy)
    cx, cy = cx.ravel(), cy.ravel()
    px = ((cx + cell_hash(cx, cy, 11)) * 8).astype(np.int64) - x0
    py = ((cy + cell_hash(cx, cy, 12)) * 4).astype(np.int64) - y0
    inside = (px >= 0) & (px < S) & (py >= 0) & (py < S)
    px, py, cx, cy = px[inside], py[inside], cx[inside], cy[inside]
    g = ground[py, px]
    keep = (cell_hash(cx, cy, 13) < TREE_PROB[g]) & ~blocked[py, px]
    px, py, cx, cy, g = px[keep], py[keep], cx[keep], cy[keep], g[keep]
    r = cell_hash(cx, cy, 14)
    forest = (g == G["FOREST"]) | (g == G["WOODLAND"]) | (g == G["SCRUB"]) | (g == G["WETLAND"])
    fam = np.where(forest, np.where(r < 0.7, 0, 1), np.where(r < 0.3, 0, np.where(r < 0.62, 1, 2)))
    size = np.where(forest, np.where(r * 7 % 1 < 0.5, 1, 2), np.where(r * 7 % 1 < 0.35, 0, np.where(r * 7 % 1 < 0.8, 1, 2)))
    size = np.where(g == G["ORCHARD"], 0, size)
    sprite = fam * 3 + size

    real = L["trees"]["xy"][INDEX["trees"].get(key, np.zeros(0, np.int64))]
    rx = real[:, 0].astype(np.int64) - x0
    ry = real[:, 1].astype(np.int64) - y0
    ok = (rx >= 0) & (rx < S) & (ry >= 0) & (ry < S)
    rx, ry = rx[ok], ry[ok]
    ok = ~blocked[ry, rx] & (ground[ry, rx] != G["WATER"])
    rx, ry = rx[ok], ry[ok]
    rr = cell_hash(rx + x0, ry + y0, 15)
    rsprite = np.where(rr < 0.4, 2, np.where(rr < 0.7, 1, 0)) * 3 + np.where(rr * 5 % 1 < 0.5, 1, 2)
    return np.concatenate([px, rx]), np.concatenate([py, ry]), np.concatenate([sprite, rsprite])


def draw_building(d: ImageDraw.ImageDraw, i: int, x0: int, y0: int) -> None:
    """Draw one extruded building: camera-facing walls, windows, then roof."""
    b = L["buildings"]
    pts = b["xy"][b["off"][i] : b["off"][i + 1]]
    xs = (pts[:, 0] - x0).tolist()
    ys = (pts[:, 1] - y0).tolist()
    n = len(xs) - 1
    if n < 3:
        return
    top, base, kind, sgn = float(b["h"][i]), float(b["base"][i]), int(b["kind"][i]), int(b["sgn"][i])
    wl, wm, wd = WALL_IDX[int(b["wall"][i])]
    roof = ROOF_IDX[int(b["roof"][i])]
    style = int(b["style"][i])
    hip = kind == 1
    eave = max(2.2, top * 0.72) if hip else top

    visible = []
    for j in range(n):
        if sgn * (xs[j + 1] - xs[j]) < 0:
            visible.append((ys[j] + ys[j + 1], j))
    visible.sort()
    windows = kind == 4 or (kind in (2, 3) and top - base >= 7)
    floor_px = 3.3 * K
    for _, j in visible:
        x1, y1, x2, y2 = xs[j], ys[j], xs[j + 1], ys[j + 1]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, 2 * dy)
        if length < 0.5:
            continue
        nx = sgn * 2 * dy / length
        shade = 0 if nx < -0.3 else (2 if nx > 0.3 else 1)
        d.polygon((x1, y1 - base, x2, y2 - base, x2, y2 - eave, x1, y1 - eave), fill=(wl, wm, wd)[shade])
        if windows and length >= 4:
            win = M["WIN_D"] if shade == 2 else M["WIN_L"]
            floors = int((eave - base) / floor_px)
            for f in range(1 if base == 0 else 0, floors):
                yo = base + (f + 0.6) * floor_px
                d.line((x1, y1 - yo, x2, y2 - yo), fill=win, width=1)
            if style % 3 != 0 and floors > 1:
                bay = 4 if style % 2 else 5
                steps = int(math.hypot(dx, dy) / bay)
                for m in range(steps + 1):
                    t = (m * bay) / max(1e-6, math.hypot(dx, dy))
                    mx, my = x1 + dx * t, y1 + dy * t
                    d.line((mx, my - base, mx, my - eave), fill=(wl, wm, wd)[shade], width=1)

    if hip:
        e = b["env"][i]
        cx = [float(e[0]) - x0, float(e[2]) - x0, float(e[4]) - x0, float(e[6]) - x0]
        cy = [float(e[1]) - y0, float(e[3]) - y0, float(e[5]) - y0, float(e[7]) - y0]
        l01 = math.hypot(cx[1] - cx[0], 2 * (cy[1] - cy[0]))
        l12 = math.hypot(cx[2] - cx[1], 2 * (cy[2] - cy[1]))
        if l01 < l12:
            cx, cy = cx[1:] + cx[:1], cy[1:] + cy[:1]
            l01, l12 = l12, l01
        width = l12 / SCALE
        rise = eave + 0.24 * width * K
        t = min(0.5, 0.5 * l12 / max(l01, 1e-6))
        ax, ay = (cx[3] + cx[0]) / 2, (cy[3] + cy[0]) / 2
        bx, by = (cx[1] + cx[2]) / 2, (cy[1] + cy[2]) / 2
        r0 = (ax + (bx - ax) * t, ay + (by - ay) * t - rise)
        r1 = (bx - (bx - ax) * t, by - (by - ay) * t - rise)
        c = [(cx[k], cy[k] - eave) for k in range(4)]
        mx, my = sum(cx) / 4, sum(cy) / 4
        faces = [((0, 1), (c[0], c[1], r1, r0)), ((2, 3), (c[2], c[3], r0, r1)),
                 ((3, 0), (c[3], c[0], r0)), ((1, 2), (c[1], c[2], r1))]
        ordered = []
        for (p, q), poly in faces:
            ex, ey = (cx[p] + cx[q]) / 2 - mx, ((cy[p] + cy[q]) / 2 - my) * 2
            ln = math.hypot(ex, ey) or 1.0
            v = -ex / ln * 0.8 + ey / ln * 0.45
            shade = 0 if v > 0.3 else (2 if v < -0.3 else 1)
            ordered.append((ey, shade, poly))
        ordered.sort(key=lambda f: f[0])
        for _, shade, poly in ordered:
            d.polygon([v for p in poly for v in p], fill=roof[shade])
        return

    top_pts = [v for k in range(n) for v in (xs[k], ys[k] - top)]
    d.polygon(top_pts, fill=roof[0] if kind != 0 else roof[1], outline=roof[3] if kind >= 2 else None)
    area = float(b["area"][i])
    if kind == 3 and area > 900:
        e = b["env"][i]
        ex = [float(e[2 * k]) - x0 for k in range(4)]
        ey = [float(e[2 * k + 1]) - y0 - top for k in range(4)]
        if math.hypot(ex[1] - ex[0], 2 * (ey[1] - ey[0])) < math.hypot(ex[2] - ex[1], 2 * (ey[2] - ey[1])):
            ex, ey = ex[1:] + ex[:1], ey[1:] + ey[:1]
        ribs = max(2, int(math.hypot(ex[2] - ex[1], 2 * (ey[2] - ey[1])) / 14))
        mask_poly = shapely.Polygon(list(zip(top_pts[0::2], top_pts[1::2])))
        for m in range(1, ribs):
            t = m / ribs
            seg = shapely.LineString([(ex[0] + (ex[3] - ex[0]) * t, ey[0] + (ey[3] - ey[0]) * t),
                                      (ex[1] + (ex[2] - ex[1]) * t, ey[1] + (ey[2] - ey[1]) * t)])
            try:
                cut = seg.intersection(mask_poly)
            except Exception:
                continue
            for piece in shapely.get_parts(cut):
                if piece.geom_type == "LineString":
                    d.line(np.asarray(piece.coords).ravel().tolist(), fill=roof[1], width=1)
    elif kind == 4 and area > 250:
        px = sum(xs[:n]) / n
        py = sum(ys[:n]) / n - top
        w = min(9.0, max(3.0, math.sqrt(area) / 5))
        ph = 3 + (style % 3)
        d.polygon((px - w, py, px, py + w / 2, px, py + w / 2 - ph, px - w, py - ph), fill=M["PLANT"])
        d.polygon((px, py + w / 2, px + w, py, px + w, py - ph, px, py + w / 2 - ph), fill=M["PLANT_D"])
        d.polygon((px - w, py - ph, px, py - w / 2 - ph, px + w, py - ph, px, py + w / 2 - ph), fill=roof[0], outline=roof[3])


def render_chunk(key: int) -> Image.Image:
    """Render one chunk and return the cropped C x C paletted image."""
    cx, cy = key % NX, key // NX
    x0, y0 = cx * C - PAD, cy * C - PAD
    img = Image.new("P", (S, S), G["WATER"])
    img.putpalette(PALETTE)
    d = ImageDraw.Draw(img)
    for name in ("land", "land_cover", "land_use", "natural", "water"):
        draw_polys(img, d, name, key, x0, y0)
    arr = np.array(img)
    texture(arr, x0, y0)
    img = Image.fromarray(arr, "P")
    img.putpalette(PALETTE)
    d = ImageDraw.Draw(img)
    draw_lines(d, key, x0, y0)

    b = L["buildings"]
    ids = INDEX["buildings"].get(key, np.zeros(0, np.int64))
    foot = Image.new("L", (S, S), 0)
    shadow = Image.new("L", (S, S), 0)
    fd, sd = ImageDraw.Draw(foot), ImageDraw.Draw(shadow)
    off = np.array([x0, y0], np.float32)
    for i in ids:
        pts = b["xy"][b["off"][i] : b["off"][i + 1]] - off
        flat = pts.ravel().tolist()
        if len(flat) < 8:
            continue
        fd.polygon(flat, fill=255)
        if b["base"][i] > 0:
            continue
        reach = min(float(b["h"][i]), 90.0)
        sx, sy = reach * 0.85, -reach * 0.22
        if reach < 7:
            sd.polygon((pts + np.array([sx, sy], np.float32)).ravel().tolist(), fill=255)
            sd.polygon((pts + np.array([sx / 2, sy / 2], np.float32)).ravel().tolist(), fill=255)
        else:
            xs, ys = pts[:, 0].tolist(), pts[:, 1].tolist()
            for j in range(len(xs) - 1):
                sd.polygon((xs[j], ys[j], xs[j + 1], ys[j + 1], xs[j + 1] + sx, ys[j + 1] + sy, xs[j] + sx, ys[j] + sy), fill=255)
            sd.polygon((pts + np.array([sx, sy], np.float32)).ravel().tolist(), fill=255)

    ground = np.asarray(img)
    tx, ty, ts = place_trees(ground, np.asarray(foot) > 0, key, x0, y0)
    for x, y in zip(tx.tolist(), ty.tolist()):
        shadow.paste(255, (x, y - 2), TREE_SHADOW)
    arr = np.array(img)
    sm = np.asarray(shadow) > 0
    arr[sm] = SHADOW_LUT[arr[sm]]
    img = Image.fromarray(arr, "P")
    img.putpalette(PALETTE)
    d = ImageDraw.Draw(img)

    depth = np.concatenate([b["bbox"][ids, 3] - y0 + b["base"][ids] * 0.01, ty.astype(np.float32)])
    nb = len(ids)
    txl, tyl, tsl = tx.tolist(), ty.tolist(), ts.tolist()
    for j in np.argsort(depth, kind="stable").tolist():
        if j < nb:
            draw_building(d, int(ids[j]), x0, y0)
        else:
            t = j - nb
            sprite, mask, w, h = TREE_SPRITES[tsl[t]]
            img.paste(sprite, (txl[t] - w // 2, tyl[t] - h + 1), mask)
    return img.crop((PAD, PAD, PAD + C, PAD + C))


def render_and_save(key: int) -> int:
    """Render a chunk and write its tiles; returns number of tiles written."""
    img = render_chunk(key)
    cx, cy = key % NX, key // NX
    out = TILES / str(MAX_LEVEL)
    count = 0
    for j in range(C // TILE):
        for i in range(C // TILE):
            px, py = cx * C + i * TILE, cy * C + j * TILE
            if px >= WIDTH or py >= HEIGHT:
                continue
            w, h = min(TILE, WIDTH - px), min(TILE, HEIGHT - py)
            tile = img.crop((i * TILE, j * TILE, i * TILE + w, j * TILE + h))
            tile.save(out / f"{px // TILE}_{py // TILE}.webp", lossless=True, method=4)
            count += 1
    return count


def main() -> None:
    """Render a preview chunk or the whole map."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", nargs=3, metavar=("LON", "LAT", "OUT"))
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()
    t0 = time.time()
    load()
    print(f"loaded in {time.time() - t0:.1f}s; {NX}x{NY} chunks; max level {MAX_LEVEL}", flush=True)
    if args.preview:
        sx, sy = lonlat_to_screen(np.array([float(args.preview[0])]), np.array([float(args.preview[1])]))
        key = int(sy[0] // C) * NX + int(sx[0] // C)
        t1 = time.time()
        img = render_chunk(key)
        print(f"chunk {key} rendered in {time.time() - t1:.1f}s")
        img.save(Path(args.preview[2]))
        return
    (TILES / str(MAX_LEVEL)).mkdir(parents=True, exist_ok=True)
    keys = list(range(NX * NY))
    done = 0
    with mp.get_context("fork").Pool(args.workers) as pool:
        for n, _ in enumerate(pool.imap_unordered(render_and_save, keys, chunksize=2), 1):
            done += _
            if n % 50 == 0:
                print(f"{n}/{len(keys)} chunks, {done} tiles, {time.time() - t0:.0f}s", flush=True)
    print(f"done: {done} tiles in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
