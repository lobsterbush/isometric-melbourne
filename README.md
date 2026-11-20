# Isometric Melbourne

**Author:** Charles Crabtree, Associate Professor, School of Social Sciences, Monash University and Professor, University College, Korea University.

## Overview

A deep-zoom isometric pixel-art map of Greater Melbourne and its suburbs, in the spirit of
[Isometric NYC](https://cannoneyed.com/isometric-nyc/) by Andy Coenen. Where the NYC map was
painted by a fine-tuned image model, this one is drawn procedurally from open map data: every
building footprint is extruded to its height, given a roof and walls, shaded, and depth-sorted
with trees over a ground layer of land use, water, roads and rail.

- Coverage: 102.4 km x 108.5 km, from Sunbury and Whittlesea in the north to Portsea and Flinders
  in the south, Geelong in the west to Pakenham and Healesville in the east.
- Resolution: 1 pixel per metre (102,400 x 54,272 px), 9 zoom levels of 512 px tiles.
- Orientation: screen-up is bearing 25 degrees, so the Hoddle Grid lies on the isometric diagonals.
- Data: Overture Maps (OpenStreetMap-derived) buildings, building parts, transportation segments,
  land, land use, land cover and water.

## Requirements

- Python 3.10+ with `overturemaps`, `shapely`, `pyproj`, `pyarrow`, `numpy`, `pillow`
  (`uv venv .venv && uv pip install --python .venv/bin/python overturemaps shapely pyproj pyarrow numpy pillow`)
- About 2.5 GB of free disk; a full build takes a few minutes on a 12-core machine.

## Replication

Run from the project root:

```bash
.venv/bin/python scripts/01_download_data.py   # Overture layers -> data/*.parquet (~620 MB)
.venv/bin/python scripts/02_prepare.py         # project to screen space -> data/prep_*.npz
.venv/bin/python scripts/03_render.py          # full-resolution tiles -> docs/tiles/8/
.venv/bin/python scripts/04_pyramid.py         # lower zoom levels + docs/map.json
python3 -m http.server 8791 --directory docs   # then open http://localhost:8791
```

Preview a single 2 km chunk without rendering everything:

```bash
.venv/bin/python scripts/03_render.py --preview 144.9631 -37.8136 preview/cbd.png
```

Map extent, orientation and resolution are set in `scripts/config.py` (`SCALE` is pixels per
metre; doubling it quadruples tile count and disk use). Colours are in `scripts/palette.py`.

## Layout

- `scripts/` numbered pipeline scripts plus `config.py` and `palette.py`
- `data/` downloaded and prepared data (not in version control)
- `docs/` the static viewer (`index.html`, OpenSeadragon, `tiles/`), served by GitHub Pages

## Address search

The viewer geocodes typed addresses with the public OpenStreetMap Nominatim API, restricted to the
map extent, then converts longitude/latitude to map pixels with a cubic fit stored in
`docs/map.json` (error under 0.05 px). Searches go from the visitor's browser straight to Nominatim.

## Attribution

Map data (c) OpenStreetMap contributors (ODbL) and Overture Maps Foundation. Building heights
without a recorded value are estimated from footprint area; roof and wall colours are procedural.
