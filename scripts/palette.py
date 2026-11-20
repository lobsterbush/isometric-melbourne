"""Fixed pixel-art palette for the isometric Melbourne map.

Ground colours occupy indices [0, N_GROUND) and each has a shadowed twin at
index + N_GROUND. Object colours (walls, roofs, trees) follow.
"""

import numpy as np

GROUND_RGB: dict[str, tuple[int, int, int]] = {
    "WATER": (72, 132, 176),
    "WATER_L": (100, 158, 196),
    "WATER_SHORE": (140, 190, 212),
    "POOL": (92, 200, 220),
    "LAND": (160, 176, 110),
    "LAND_S": (148, 166, 100),
    "RESID": (174, 182, 132),
    "PARK": (120, 172, 86),
    "PARK_S": (106, 158, 76),
    "PITCH": (104, 186, 86),
    "GOLF": (132, 194, 98),
    "FOREST": (76, 128, 68),
    "SCRUB": (124, 148, 90),
    "WOODLAND": (100, 148, 80),
    "FARM": (192, 186, 118),
    "FARM_S": (182, 174, 106),
    "ORCHARD": (150, 172, 96),
    "SAND": (228, 210, 158),
    "ROCK": (152, 148, 138),
    "WETLAND": (112, 152, 132),
    "INDUS": (178, 172, 162),
    "COMM": (198, 192, 180),
    "INSTIT": (200, 192, 162),
    "PAVE": (206, 202, 192),
    "CEMETERY": (152, 172, 132),
    "TRACK": (192, 112, 92),
    "DIRT": (186, 162, 122),
    "ROAD": (100, 102, 110),
    "ROAD_MAJOR": (84, 86, 96),
    "CASING": (204, 200, 188),
    "ROAD_LINE": (238, 216, 122),
    "RAIL": (66, 62, 68),
    "RAIL_BED": (152, 142, 132),
    "PATH": (216, 206, 172),
    "TRAM": (58, 60, 70),
}

WALL_RGB: dict[str, tuple[int, int, int]] = {
    "brick": (184, 100, 76),
    "cream": (230, 216, 184),
    "white": (236, 234, 226),
    "concrete": (176, 178, 182),
    "brown": (156, 114, 86),
    "glass": (124, 172, 204),
    "darkglass": (74, 102, 132),
    "sandstone": (210, 184, 134),
    "teal": (100, 164, 164),
    "metal": (202, 204, 206),
}

ROOF_RGB: dict[str, tuple[int, int, int]] = {
    "terracotta": (200, 106, 72),
    "greytile": (134, 136, 142),
    "charcoal": (88, 92, 102),
    "bluegrey": (112, 132, 152),
    "red": (170, 72, 62),
    "green": (98, 130, 106),
    "creammetal": (216, 210, 192),
    "lightmetal": (192, 196, 200),
    "white": (228, 230, 232),
    "brown": (142, 102, 78),
}

TREE_RGB: dict[str, tuple[int, int, int]] = {
    "eucalypt": (98, 136, 80),
    "deep": (68, 130, 72),
    "plane": (98, 162, 64),
}

MISC_RGB: dict[str, tuple[int, int, int]] = {
    "WIN_L": (62, 88, 116),
    "WIN_D": (42, 60, 84),
    "TRUNK": (92, 70, 50),
    "PLANT": (150, 152, 158),
    "PLANT_D": (112, 114, 122),
}


def _shade(rgb: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    """Scale a colour's brightness, clamping to 0-255."""
    return tuple(int(max(0, min(255, round(c * f)))) for c in rgb)


def _shadow(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Return the shadowed version of a ground colour."""
    r, g, b = rgb
    return (int(r * 0.66), int(g * 0.68), int(b * 0.76))


_colours: list[tuple[int, int, int]] = []
G: dict[str, int] = {}
for _name, _rgb in GROUND_RGB.items():
    G[_name] = len(_colours)
    _colours.append(_rgb)
N_GROUND: int = len(_colours)
_colours += [_shadow(c) for c in _colours[:N_GROUND]]

# Walls: (light, mid, dark). Roofs: (light, mid, dark, outline). Trees: (dark, mid, light).
WALL: dict[str, tuple[int, int, int]] = {}
for _name, _rgb in WALL_RGB.items():
    WALL[_name] = (len(_colours), len(_colours) + 1, len(_colours) + 2)
    _colours += [_shade(_rgb, 1.0), _shade(_rgb, 0.84), _shade(_rgb, 0.66)]
ROOF: dict[str, tuple[int, int, int, int]] = {}
for _name, _rgb in ROOF_RGB.items():
    ROOF[_name] = tuple(len(_colours) + k for k in range(4))
    _colours += [_shade(_rgb, 1.1), _shade(_rgb, 0.94), _shade(_rgb, 0.76), _shade(_rgb, 0.58)]
TREE: dict[str, tuple[int, int, int]] = {}
for _name, _rgb in TREE_RGB.items():
    TREE[_name] = tuple(len(_colours) + k for k in range(3))
    _colours += [_shade(_rgb, 0.72), _rgb, _shade(_rgb, 1.25)]
M: dict[str, int] = {}
for _name, _rgb in MISC_RGB.items():
    M[_name] = len(_colours)
    _colours.append(_rgb)

WALL_NAMES: list[str] = list(WALL_RGB)
ROOF_NAMES: list[str] = list(ROOF_RGB)
TREE_NAMES: list[str] = list(TREE_RGB)

PALETTE: list[int] = [v for c in _colours for v in c] + [0] * (768 - 3 * len(_colours))

SHADOW_LUT: np.ndarray = np.arange(256, dtype=np.uint8)
SHADOW_LUT[:N_GROUND] += N_GROUND
