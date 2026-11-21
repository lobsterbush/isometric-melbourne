# Isometric Melbourne

Deep-zoom isometric pixel-art map of Greater Melbourne, rendered procedurally from Overture/OpenStreetMap data, with an address search and an experiment engine for lab and survey studies.

- Repo: https://github.com/lobsterbush/isometric-melbourne (public, branch `main`)
- Live site: https://lobsterbush.github.io/isometric-melbourne/ (GitHub Pages from `main` `/docs`)

## Layout

- `scripts/01_download_data.py` → `02_prepare.py` → `03_render.py` → `04_pyramid.py`: the render pipeline. Geometry lives in `scripts/config.py`, colours in `scripts/palette.py`.
- `data/`: downloaded and prepared layers (about 620 MB). Generated, not in git.
- `docs/`: everything Pages serves. `index.html` is the map viewer, `experiment.html` + `experiment.js` the experiment engine, `lab.html` the lab console, `studies/*.json` the study configs, `tiles/` the image pyramid, `map.json` the projection and place list, `built_mask.png` the built-up mask.
- `docs/qualtrics_snippet.js`: iframe embed for a Qualtrics question.

## Commands

- Full rebuild (about five minutes): run the four scripts in order from the repo root with the `.venv` Python.
- Metadata only (`map.json`, built mask), no tiles: `python scripts/04_pyramid.py --meta-only`.
- One preview tile: `python scripts/03_render.py --preview LON LAT OUT`.
- Local preview: serve `docs/` on port 8791 (`.claude/launch.json`, name `isometric-melbourne`).

## Constraints

- `docs/` must stay under GitHub Pages' 1 GB limit. It is 929 MB. Level 8 tiles are lossless WebP and lower levels WebP quality 72; don't switch tile formats or add a zoom level without checking the size.
- Pages needs the repo to be public on the current plan.
- No GitHub Actions workflows. Push to `main` after any change under `docs/`.
- Address search calls the public Nominatim API from the browser. No key, no server.

## Experiments

- A study is one JSON file in `docs/studies/`, opened with `experiment.html?study=<name>`. URL parameters: `pid`, `arm`, `set`, `seed`, `mode=survey|lab`.
- `arms` are between-subject treatments, picked at random by `weight` (default 1). An arm with `"weight": 0` is never assigned at random but can be forced with `&arm=<id>`.
- `design: "conjoint"` randomises attribute levels; `design: "sets"` shows fixed `options` in named `choiceSets`.
- A `home` block asks for the participant's address. A `"type": "place"` attribute then puts options on their own street, a set distance away, or at a pooled location elsewhere. Home-derived coordinates are saved rounded to `recordDecimals` (default 2) so the data never holds an exact address.
- `street-changes` is the transport study for the collaboration with Ben Beck and Lauren Pearson (Monash Public Health, Healthy Active Cities). Its content is placeholder. The `generic_place` control arm has weight 0 so the shared link always shows the address version.
- Survey mode posts rows to the parent page with `postMessage` (`source: 'isometric-melbourne'`); lab mode stores them in `localStorage` under `isomelb:<study>`.
- Qualtrics test survey: `SV_eQm3ULUW5RZVwqO`, unpublished, still pointing at `neighbourhood-choice`.
