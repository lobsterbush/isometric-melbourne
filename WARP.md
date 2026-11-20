# Isometric Melbourne

**Status:** Active

**Description:** Deep-zoom isometric pixel-art map of Greater Melbourne rendered procedurally from Overture/OpenStreetMap data.

**Authors:** Charles Crabtree

## Notes

- Pipeline: `scripts/01_download_data.py` -> `02_prepare.py` -> `03_render.py` -> `04_pyramid.py`; viewer in `docs/`.
- Geometry and resolution live in `scripts/config.py`; palette in `scripts/palette.py`.
- `data/` is generated and stays out of git; `docs/` (viewer and tiles) is committed and served by GitHub Pages.
- Address search calls the public Nominatim API from the browser; no key or server.
