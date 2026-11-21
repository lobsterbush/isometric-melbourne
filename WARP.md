# Isometric Melbourne

**Status:** Active

**Description:** Deep-zoom isometric pixel-art map of Greater Melbourne rendered procedurally from Overture/OpenStreetMap data, with address search and an experiment engine for lab and survey studies.

**Authors:** Charles Crabtree

## Notes

- Pipeline: `scripts/01_download_data.py` -> `02_prepare.py` -> `03_render.py` -> `04_pyramid.py`; viewer in `docs/`.
- Geometry and resolution live in `scripts/config.py`; palette in `scripts/palette.py`.
- `data/` is generated and stays out of git; `docs/` (viewer and tiles) is committed and served by GitHub Pages.
- Address search calls the public Nominatim API from the browser; no key or server.
- Experiment engine: `docs/experiment.html` + `docs/experiment.js`, study configs in `docs/studies/`, lab console at `docs/lab.html`, Qualtrics embed in `docs/qualtrics_snippet.js`.
- `street-changes` is the transport study for the collaboration with Ben Beck and Lauren Pearson (Monash Public Health); content is placeholder.
- Repo: https://github.com/lobsterbush/isometric-melbourne; live at https://lobsterbush.github.io/isometric-melbourne/. `docs/` must stay under the 1 GB Pages limit.
