"""Download Overture Maps layers (OpenStreetMap-derived) for Greater Melbourne.

Writes one GeoParquet file per layer to data/. Existing files are skipped.
Run from the project root: .venv/bin/python scripts/01_download_data.py
"""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from config import DATA, geographic_bbox

LAYERS: list[str] = ["building", "building_part", "segment", "water", "land", "land_use", "land_cover"]


def download(layer: str) -> str:
    """Download one Overture layer for the map bounding box."""
    out = DATA / f"{layer}.parquet"
    if out.exists():
        return f"{layer}: exists"
    tmp = out.with_suffix(".part")
    bbox = ",".join(f"{v:.4f}" for v in geographic_bbox())
    cli = Path(sys.executable).parent / "overturemaps"
    subprocess.run(
        [str(cli), "download", f"--bbox={bbox}", "-f", "geoparquet", "-t", layer, "-o", str(tmp)],
        check=True,
    )
    tmp.rename(out)
    return f"{layer}: {out.stat().st_size / 1e6:.0f} MB"


def main() -> None:
    """Download all layers in parallel."""
    DATA.mkdir(exist_ok=True)
    print("bbox", geographic_bbox())
    with ThreadPoolExecutor(4) as pool:
        for msg in pool.map(download, LAYERS):
            print(msg, flush=True)


if __name__ == "__main__":
    main()
