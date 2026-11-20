"""Shared geometry and path configuration for the isometric Melbourne map.

The map is a 2:1 dimetric ("pixel isometric") view. Screen-up points along
bearing 25 degrees so that the Hoddle Grid sits on the two isometric diagonals.
"""

from pathlib import Path

import numpy as np
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "docs"  # served by GitHub Pages
TILES = SITE / "tiles"

ORIGIN_LONLAT: tuple[float, float] = (144.9671, -37.8183)  # Flinders Street Station
UP_BEARING_DEG: float = 25.0
SCALE: float = 1.0  # screen pixels per metre along the screen-x axis
Z_SCALE: float = 0.866  # screen pixels per metre of height (30 degree camera)
TILE: int = 512

# Map extent in km relative to the origin, in rotated (right, up) coordinates.
RIGHT_MIN_KM, RIGHT_MAX_KM = -42.4, 60.0
UP_MIN_KM, UP_MAX_KM = -66.272, 42.272

WIDTH: int = int(round((RIGHT_MAX_KM - RIGHT_MIN_KM) * 1000 * SCALE))
HEIGHT: int = int(round((UP_MAX_KM - UP_MIN_KM) * 1000 * SCALE * 0.5))

_TO_MGA = Transformer.from_crs(4326, 7855, always_xy=True)
_TO_LL = Transformer.from_crs(7855, 4326, always_xy=True)
_OX, _OY = _TO_MGA.transform(*ORIGIN_LONLAT)
_B = np.radians(UP_BEARING_DEG)
_UP = (np.sin(_B), np.cos(_B))
_RT = (np.cos(_B), -np.sin(_B))


def lonlat_to_screen(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project lon/lat to ground-level screen pixel coordinates."""
    x, y = _TO_MGA.transform(lon, lat)
    dx, dy = np.asarray(x) - _OX, np.asarray(y) - _OY
    right = dx * _RT[0] + dy * _RT[1]
    up = dx * _UP[0] + dy * _UP[1]
    sx = (right - RIGHT_MIN_KM * 1000) * SCALE
    sy = (UP_MAX_KM * 1000 - up) * SCALE * 0.5
    return sx, sy


def screen_to_lonlat(sx: float, sy: float) -> tuple[float, float]:
    """Invert lonlat_to_screen for a ground-level screen point."""
    right = sx / SCALE + RIGHT_MIN_KM * 1000
    up = UP_MAX_KM * 1000 - sy / (SCALE * 0.5)
    dx = right * _RT[0] + up * _UP[0]
    dy = right * _RT[1] + up * _UP[1]
    return _TO_LL.transform(dx + _OX, dy + _OY)


def geographic_bbox(pad_deg: float = 0.01) -> tuple[float, float, float, float]:
    """Return (west, south, east, north) covering the whole rotated map extent."""
    corners = [screen_to_lonlat(x, y) for x in (0, WIDTH) for y in (0, HEIGHT)]
    lons, lats = zip(*corners)
    return (min(lons) - pad_deg, min(lats) - pad_deg, max(lons) + pad_deg, max(lats) + pad_deg)
