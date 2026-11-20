"""Convert downloaded Overture layers into compact screen-space arrays.

Reads data/*.parquet and writes data/prep_*.npz: flat coordinate arrays in
screen pixels, ring/part offsets, bounding boxes and per-feature style codes.
Run from the project root: .venv/bin/python scripts/02_prepare.py
"""

import numpy as np
import pyarrow.parquet as pq
import shapely

from config import DATA, HEIGHT, SCALE, WIDTH, Z_SCALE, lonlat_to_screen
from palette import G, ROOF_NAMES, WALL_NAMES

K = Z_SCALE * SCALE


def read(layer: str, columns: list[str]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Read a layer's geometries and selected attribute columns."""
    t = pq.read_table(DATA / f"{layer}.parquet", columns=columns + ["geometry"])
    geoms = shapely.from_wkb(t["geometry"].to_numpy(zero_copy_only=False))
    attrs = {c: np.array(t[c].to_pylist(), dtype=object) for c in columns}
    return geoms, attrs


def project(coords: np.ndarray) -> np.ndarray:
    """Project lon/lat coordinate pairs to float32 screen pixels."""
    sx, sy = lonlat_to_screen(coords[:, 0], coords[:, 1])
    return np.column_stack([sx, sy]).astype(np.float32)


def ring_bbox(xy: np.ndarray, starts: np.ndarray) -> np.ndarray:
    """Per-group bounding boxes (minx, miny, maxx, maxy) for coordinate groups."""
    lo = np.minimum.reduceat(xy, starts, axis=0)
    hi = np.maximum.reduceat(xy, starts, axis=0)
    return np.hstack([lo, hi]).astype(np.float32)


def on_map(bbox: np.ndarray, pad: float = 400.0) -> np.ndarray:
    """Mask of features whose bounding box touches the map canvas."""
    return (bbox[:, 2] > -pad) & (bbox[:, 0] < WIDTH + pad) & (bbox[:, 3] > -pad) & (bbox[:, 1] < HEIGHT + pad)


def polygons(geoms: np.ndarray, code: np.ndarray, holes: bool) -> dict[str, np.ndarray]:
    """Explode (multi)polygons into parts with ring offsets and style codes."""
    parts, src = shapely.get_parts(geoms, return_index=True)
    keep = shapely.get_type_id(parts) == 3
    parts, src = parts[keep], src[keep]
    if holes:
        rings, pidx = shapely.get_rings(parts, return_index=True)
    else:
        rings, pidx = shapely.get_exterior_ring(parts), np.arange(len(parts))
    coords, ridx = shapely.get_coordinates(rings, return_index=True)
    xy = project(coords)
    ring_off = np.searchsorted(ridx, np.arange(len(rings) + 1)).astype(np.int64)
    part_off = np.searchsorted(pidx, np.arange(len(parts) + 1)).astype(np.int64)
    bbox = ring_bbox(xy, ring_off[part_off[:-1]])
    return {"xy": xy, "ring_off": ring_off, "part_off": part_off, "bbox": bbox, "code": code[src].astype(np.uint8)}


def subset_polys(p: dict[str, np.ndarray], order: np.ndarray) -> dict[str, np.ndarray]:
    """Reorder/filter polygon parts, rebuilding the flat coordinate arrays."""
    ro, po, xy = p["ring_off"], p["part_off"], p["xy"]
    new_xy, new_ro, new_po = [], [0], [0]
    for i in order:
        for r in range(po[i], po[i + 1]):
            seg = xy[ro[r] : ro[r + 1]]
            new_xy.append(seg)
            new_ro.append(new_ro[-1] + len(seg))
        new_po.append(len(new_ro) - 1)
    out = {
        "xy": np.concatenate(new_xy) if new_xy else np.zeros((0, 2), np.float32),
        "ring_off": np.array(new_ro, np.int64),
        "part_off": np.array(new_po, np.int64),
    }
    for k, v in p.items():
        if k not in out:
            out[k] = v[order]
    return out


def lines(geoms: np.ndarray, code: np.ndarray) -> dict[str, np.ndarray]:
    """Explode (multi)linestrings into parts with offsets and style codes."""
    parts, src = shapely.get_parts(geoms, return_index=True)
    keep = shapely.get_type_id(parts) == 1
    parts, src = parts[keep], src[keep]
    coords, idx = shapely.get_coordinates(parts, return_index=True)
    xy = project(coords)
    off = np.searchsorted(idx, np.arange(len(parts) + 1)).astype(np.int64)
    bbox = ring_bbox(xy, off[:-1])
    code = code[src].astype(np.uint8)
    keep = on_map(bbox)
    order = np.flatnonzero(keep)
    order = order[np.argsort(code[order], kind="stable")]
    new_xy = np.concatenate([xy[off[i] : off[i + 1]] for i in order])
    new_off = np.concatenate([[0], np.cumsum(off[order + 1] - off[order])]).astype(np.int64)
    return {"xy": new_xy, "off": new_off, "bbox": bbox[order], "code": code[order]}


def codes(values: np.ndarray, mapping: dict[str, int], default: int = 255) -> np.ndarray:
    """Map string attribute values to uint8 codes; 255 means drop."""
    return np.array([mapping.get(v, default) for v in values], dtype=np.uint8)


def hash01(a: np.ndarray, b: np.ndarray, seed: int) -> np.ndarray:
    """Deterministic uniform [0, 1) hash of two integer arrays."""
    h = (a.astype(np.int64) + (1 << 24)).astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)
    h ^= ((b.astype(np.int64) + (1 << 24)).astype(np.uint64) + np.uint64(seed)) * np.uint64(0xC2B2AE3D27D4EB4F)
    h ^= h >> np.uint64(29)
    h *= np.uint64(0xBF58476D1CE4E5B9)
    h ^= h >> np.uint64(32)
    return (h >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def prep_ground() -> None:
    """Prepare land, land cover, land use, natural areas, water and trees."""
    geoms, a = read("land", ["subtype", "class"])
    sub, cls = a["subtype"], a["class"]

    base = polygons(geoms[sub == "land"], np.full((sub == "land").sum(), G["LAND"]), holes=True)
    np.savez(DATA / "prep_land.npz", **base)

    nat_map = {"forest": G["FOREST"], "shrub": G["SCRUB"], "grass": G["PARK"], "sand": G["SAND"],
               "rock": G["ROCK"], "wetland": G["WETLAND"]}
    nat_code = codes(sub, nat_map)
    m = nat_code != 255
    natural = polygons(geoms[m], nat_code[m], holes=True)

    is_tree = (sub == "tree") & (shapely.get_type_id(geoms) == 0)
    tree_xy = project(shapely.get_coordinates(geoms[is_tree]))
    rows = geoms[(cls == "tree_row") & (shapely.get_type_id(geoms) == 1)]
    row_len = shapely.length(rows) * 100000  # rough metres
    row_pts = [shapely.line_interpolate_point(r, np.linspace(0, 1, max(2, int(n / 9))), normalized=True)
               for r, n in zip(rows, row_len)]
    if row_pts:
        tree_xy = np.vstack([tree_xy, project(shapely.get_coordinates(np.concatenate(row_pts)))])
    keep = (tree_xy[:, 0] > 0) & (tree_xy[:, 0] < WIDTH) & (tree_xy[:, 1] > 0) & (tree_xy[:, 1] < HEIGHT)
    np.savez(DATA / "prep_trees.npz", xy=tree_xy[keep])
    print("trees", keep.sum())

    geoms, a = read("land_cover", ["subtype", "cartography"])
    detail = np.array([c["max_zoom"] >= 15 for c in a["cartography"]])
    lc_map = {"forest": G["WOODLAND"], "shrub": G["LAND"], "crop": G["FARM"], "urban": G["RESID"],
              "barren": G["FARM"], "wetland": G["WETLAND"], "mangrove": G["WETLAND"], "grass": G["LAND"]}
    lc_code = codes(a["subtype"], lc_map)
    m = detail & (lc_code != 255)
    cover = polygons(geoms[m], lc_code[m], holes=True)
    cover = subset_polys(cover, np.flatnonzero(on_map(cover["bbox"])))
    np.savez(DATA / "prep_land_cover.npz", **cover)
    print("land_cover", len(cover["code"]))

    geoms, a = read("land_use", ["subtype", "class"])
    lu_cls = {
        "pitch": G["PITCH"], "tee": G["GOLF"], "green": G["GOLF"], "fairway": G["GOLF"], "bunker": G["SAND"],
        "golf_course": G["PARK"], "rough": G["PARK"], "driving_range": G["GOLF"],
        "grass": G["PARK"], "meadow": G["PARK"], "park": G["PARK"], "garden": G["PARK"], "playground": G["PARK"],
        "recreation_ground": G["PARK"], "dog_park": G["PARK"], "village_green": G["PARK"], "flowerbed": G["PARK"],
        "nature_reserve": G["SCRUB"], "residential": G["RESID"], "retail": G["COMM"], "commercial": G["COMM"],
        "industrial": G["INDUS"], "works": G["INDUS"], "railway": G["INDUS"], "construction": G["DIRT"],
        "brownfield": G["DIRT"], "quarry": G["DIRT"], "landfill": G["DIRT"], "school": G["INSTIT"],
        "kindergarten": G["INSTIT"], "college": G["INSTIT"], "university": G["INSTIT"], "hospital": G["INSTIT"],
        "religious": G["INSTIT"], "farmland": G["FARM"], "farmyard": G["FARM"], "vineyard": G["ORCHARD"],
        "orchard": G["ORCHARD"], "plant_nursery": G["ORCHARD"], "cemetery": G["CEMETERY"],
        "pedestrian": G["PAVE"], "track": G["TRACK"], "water_hazard": G["WATER"],
        "lateral_water_hazard": G["WATER"], "salt_pond": G["WATER"], "camp_site": G["PARK"],
    }
    lu_sub = {"park": G["PARK"], "recreation": G["PARK"], "agriculture": G["FARM"], "horticulture": G["ORCHARD"],
              "education": G["INSTIT"], "medical": G["INSTIT"], "cemetery": G["CEMETERY"],
              "military": G["INSTIT"], "developed": G["COMM"], "golf": G["PARK"]}
    lu_code = codes(a["class"], lu_cls)
    fallback = codes(a["subtype"], lu_sub)
    lu_code = np.where(lu_code == 255, fallback, lu_code)
    m = lu_code != 255
    use = polygons(geoms[m], lu_code[m], holes=True)

    # Land use and natural areas share one layer: big polygons first, natural cover on top.
    for name, layer in (("land_use", use), ("natural", natural)):
        w = layer["bbox"][:, 2] - layer["bbox"][:, 0]
        h = layer["bbox"][:, 3] - layer["bbox"][:, 1]
        order = np.flatnonzero(on_map(layer["bbox"]))
        order = order[np.argsort(-(w * h)[order], kind="stable")]
        layer = subset_polys(layer, order)
        np.savez(DATA / f"prep_{name}.npz", **layer)
        print(name, len(layer["code"]))

    geoms, a = read("water", ["subtype", "class", "is_intermittent"])
    sub, cls = a["subtype"], a["class"]
    w_code = np.where(cls == "swimming_pool", G["POOL"], G["WATER"]).astype(np.uint8)
    w_code[np.isin(sub, ["physical", "spring"]) | np.isin(cls, ["wastewater", "cape", "bay", "strait"])] = 255
    w_code[sub == "ocean"] = 255  # the base canvas is already sea
    m = w_code != 255
    water = polygons(geoms[m], w_code[m], holes=True)
    water = subset_polys(water, np.flatnonzero(on_map(water["bbox"])))
    np.savez(DATA / "prep_water.npz", **water)
    width = {"river": 4, "canal": 3, "stream": 2, "drain": 1, "ditch": 1, "tidal_channel": 2}
    l_code = np.array([width.get(c, 255) for c in cls], dtype=np.uint8)
    l_code[(a["is_intermittent"] == True) & (l_code != 255)] = 1  # noqa: E712
    m = l_code != 255
    wl = lines(geoms[m], l_code[m])
    np.savez(DATA / "prep_water_lines.npz", **wl)
    print("water", len(water["code"]), "water lines", len(wl["code"]))


ROAD_RANK: dict[str, int] = {
    "track": 0, "bridleway": 0, "path": 1, "footway": 1, "steps": 1, "cycleway": 2, "pedestrian": 3,
    "service": 4, "unknown": 4, "living_street": 5, "residential": 5, "unclassified": 5, "tertiary": 6,
    "secondary": 7, "primary": 8, "trunk": 9, "motorway": 10,
    "standard_gauge": 20, "narrow_gauge": 20, "light_rail": 20, "tram": 21,
}


def prep_segments() -> None:
    """Prepare roads, railways and tram lines, dropping tunnels."""
    geoms, a = read("segment", ["subtype", "class", "road_flags", "rail_flags"])
    code = codes(a["class"], ROAD_RANK)
    for i, (rf, lf) in enumerate(zip(a["road_flags"], a["rail_flags"])):
        for flag in (rf or []) + (lf or []):
            whole = flag["between"] is None or (flag["between"][1] - flag["between"][0]) > 0.6
            if whole and any(v in ("is_tunnel", "is_abandoned", "is_disused") for v in flag["values"]):
                code[i] = 255
    code[a["subtype"] == "water"] = 255
    m = code != 255
    seg = lines(geoms[m], code[m])
    np.savez(DATA / "prep_segments.npz", **seg)
    print("segments", len(seg["code"]))


HOUSE_ROOFS = ["terracotta", "greytile", "charcoal", "bluegrey", "red", "green", "brown"]
HOUSE_ROOF_P = [0.30, 0.27, 0.22, 0.07, 0.05, 0.04, 0.05]
HOUSE_WALLS = ["brick", "cream", "white", "brown", "sandstone"]
HOUSE_WALL_P = [0.34, 0.26, 0.2, 0.12, 0.08]
TALL_WALLS = ["concrete", "glass", "darkglass", "sandstone", "cream", "teal", "white", "brick"]
TALL_WALL_P = [0.22, 0.22, 0.16, 0.1, 0.1, 0.06, 0.08, 0.06]
FLAT_ROOFS = ["lightmetal", "creammetal", "white", "charcoal", "greytile", "bluegrey"]
FLAT_ROOF_P = [0.38, 0.2, 0.14, 0.1, 0.12, 0.06]


def pick(r: np.ndarray, names: list[str], probs: list[float], table: list[str]) -> np.ndarray:
    """Choose a palette family index per feature from a uniform random array."""
    edges = np.cumsum(probs)
    choice = np.minimum(np.searchsorted(edges, r), len(names) - 1)
    lookup = np.array([table.index(n) for n in names], dtype=np.uint8)
    return lookup[choice]


def building_arrays(layer: str, is_part: bool) -> dict[str, np.ndarray]:
    """Build footprint rings and style attributes for buildings or building parts."""
    cols = ["height", "num_floors", "min_height"] + ([] if is_part else ["subtype", "class", "has_parts", "is_underground"])
    geoms, a = read(layer, cols)
    parts, src = shapely.get_parts(geoms, return_index=True)
    keep = shapely.get_type_id(parts) == 3
    parts, src = parts[keep], src[keep]
    rings = shapely.get_exterior_ring(parts)
    coords, ridx = shapely.get_coordinates(rings, return_index=True)
    xy = project(coords)
    off = np.searchsorted(ridx, np.arange(len(rings) + 1)).astype(np.int64)
    bbox = ring_bbox(xy, off[:-1])

    ground = shapely.polygons(shapely.linearrings(np.column_stack([xy[:, 0], xy[:, 1] * 2.0]).astype(np.float64), indices=ridx))
    area = shapely.area(ground) / (SCALE * SCALE)
    x, y = xy[:, 0].astype(np.float64), xy[:, 1].astype(np.float64)
    cross = x * np.roll(y, -1) - np.roll(x, -1) * y
    cross[off[1:] - 1] = 0.0
    sgn = np.sign(np.add.reduceat(cross, off[:-1])).astype(np.int8)
    sgn[sgn == 0] = 1

    env = shapely.oriented_envelope(ground)
    env_xy = np.zeros((len(parts), 8), np.float32)
    ok = shapely.get_type_id(env) == 3
    ec = shapely.get_coordinates(shapely.get_exterior_ring(env[ok])).reshape(-1, 5, 2)[:, :4, :]
    ec[:, :, 1] *= 0.5
    env_xy[ok] = ec.reshape(-1, 8).astype(np.float32)
    env_area = np.where(ok, shapely.area(env), 0.0) / (SCALE * SCALE)
    fill = np.where(env_area > 0, area / np.maximum(env_area, 1e-6), 0.0)

    def num(col: str) -> np.ndarray:
        return np.array([np.nan if v is None else v for v in a[col][src]], dtype=np.float64)

    bx, by = np.floor(bbox[:, 0]).astype(np.int64), np.floor(bbox[:, 1]).astype(np.int64)
    r1, r2, r3 = hash01(bx, by, 1), hash01(bx, by, 2), hash01(bx, by, 3)
    hood = hash01(bx // 700, by // 350, 4)

    h = num("height")
    floors = num("num_floors")
    h = np.where(np.isnan(h), floors * 3.3, h)
    default = np.select([area < 45, area < 420, area < 1500], [2.5, np.where(r1 < 0.22, 5.6, 3.0), 4 + r1 * 4], 7 + r1 * 4)
    h = np.where(np.isnan(h) | (h < 2.2), default, h)
    base = np.nan_to_num(num("min_height"), nan=0.0)
    base = np.where(base >= h, 0.0, base)

    if is_part:
        sub = cls = np.full(len(parts), None, dtype=object)
        drop = np.zeros(len(parts), bool)
    else:
        sub, cls = a["subtype"][src], a["class"][src]
        drop = (a["has_parts"][src] == True) | (a["is_underground"][src] == True)  # noqa: E712

    small_cls = np.isin(cls, ["garage", "shed", "carport", "shelter", "roof", "garages", "beach_hut", "toilets"])
    res_like = np.isin(sub, [None, "residential"]) & ~small_cls
    kind = np.full(len(parts), 2, np.uint8)  # 0 shed, 1 hip-roof house, 2 flat mid-size, 3 large/industrial, 4 tall
    kind[(area >= 1500) | np.isin(sub, ["industrial"]) | np.isin(cls, ["warehouse", "hangar", "industrial"])] = 3
    kind[(area >= 45) & (area < 420) & (h <= 8.5) & (fill >= 0.62) & res_like & ok] = 1
    kind[(area < 45) | (small_cls & (h < 6))] = 0
    kind[h >= 10.5] = 4
    if is_part:
        kind[:] = 4

    r_roof = (r2 * 0.55 + hood * 0.45)
    r_roof = (r_roof - 0.0) % 1.0
    roof = pick(r2, FLAT_ROOFS, FLAT_ROOF_P, ROOF_NAMES)
    roof = np.where(kind == 1, pick(r_roof, HOUSE_ROOFS, HOUSE_ROOF_P, ROOF_NAMES), roof)
    roof = np.where(kind == 4, pick(r2, ["greytile", "lightmetal", "charcoal", "white"], [0.4, 0.3, 0.15, 0.15], ROOF_NAMES), roof)
    wall = pick(r3, HOUSE_WALLS, HOUSE_WALL_P, WALL_NAMES)
    wall = np.where(kind == 3, pick(r3, ["metal", "cream", "concrete", "brick"], [0.4, 0.3, 0.2, 0.1], WALL_NAMES), wall)
    wall = np.where(kind == 2, pick(r3, ["cream", "brick", "concrete", "white", "brown"], [0.3, 0.25, 0.2, 0.15, 0.1], WALL_NAMES), wall)
    wall = np.where(kind == 4, pick(r3, TALL_WALLS, TALL_WALL_P, WALL_NAMES), wall)
    tall_glass = (kind == 4) & (h > 60) & (r1 < 0.75)
    wall = np.where(tall_glass, pick(r3, ["glass", "darkglass", "teal", "concrete"], [0.4, 0.35, 0.15, 0.1], WALL_NAMES), wall)

    keep = on_map(bbox, 600.0) & ~drop
    order = np.flatnonzero(keep)
    new_xy = np.concatenate([xy[off[i] : off[i + 1]] for i in order])
    new_off = np.concatenate([[0], np.cumsum(off[order + 1] - off[order])]).astype(np.int64)
    return {
        "xy": new_xy, "off": new_off, "bbox": bbox[order], "h": (h[order] * K).astype(np.float32),
        "base": (base[order] * K).astype(np.float32), "kind": kind[order], "roof": roof[order].astype(np.uint8),
        "wall": wall[order].astype(np.uint8), "sgn": sgn[order], "env": env_xy[order],
        "area": area[order].astype(np.float32), "style": (r1[order] * 255).astype(np.uint8),
    }


def prep_buildings() -> None:
    """Prepare buildings plus detailed building parts as one layer."""
    b = building_arrays("building", is_part=False)
    p = building_arrays("building_part", is_part=True)
    out = {}
    for k in b:
        if k == "off":
            out[k] = np.concatenate([b[k], p[k][1:] + b[k][-1]])
        else:
            out[k] = np.concatenate([b[k], p[k]])
    np.savez(DATA / "prep_buildings.npz", **out)
    print("buildings", len(b["kind"]), "parts", len(p["kind"]), "kinds", np.bincount(out["kind"]))


if __name__ == "__main__":
    prep_ground()
    prep_segments()
    prep_buildings()
