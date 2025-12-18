"""Example script demonstrating create_stac_structure usage.

This script copies an input geospatial file and gdal translate it to geotiff GOG into an ``assets`` folder and
creates minimal STAC metadata for it. The resulting structure will be created
relative to the output directory (default: current working directory).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from stac_structure import create_stac_structure
from datetime import datetime, timezone
import re
import os

# PDF spec — On-Demand / Ad-Hoc:
# <Service_UID>_<YYYYMMDDTHHMMSSmmm>_<NNNNNN>
ADHOC_RE = re.compile(r"^(?P<svc>[A-Z0-9\-]+)_(?P<ts>\d{8}T\d{6}\d{3})_(?P<ctr>\d{6})$")

# PDF spec — Systematic:
# <Service_UID>_<YYYYMMDD>   (other frequencies exist, but day-level is the base)
SYSTEMATIC_DAY_RE = re.compile(r"^(?P<svc>[A-Z0-9\-]+)_(?P<date>\d{8})$")


def _id_ok_for_ls_df(item_id: str) -> bool:
    """
    LS-DF collection accepts:
      - Systematic IDs:   <Service_UID>_<YYYYMMDD>
      - Ad-hoc IDs:       <Service_UID>_<YYYYMMDDTHHMMSSmmm>_<NNNNNN>
    where Service_UID itself starts with 'LS-DF' (e.g., 'LS-DF-SB-S1').
    """
    m = ADHOC_RE.match(item_id)
    if m and m.group("svc").startswith("LS-DF"):
        return True
    m = SYSTEMATIC_DAY_RE.match(item_id)
    if m and m.group("svc").startswith("LS-DF"):
        return True
    return False


ID_COUNTER_PATTERN = re.compile(
    r"^(?P<svc>[A-Z0-9\-]+)_(?P<ts>\d{8}T\d{6}\d{3})_(?P<ctr>\d{6})$"
)


def utc_timestamp_millis_version03() -> str:
    """Return UTC timestamp as YYYYMMDDTHHMMSSmmm."""
    now = datetime.now(timezone.utc)
    # microseconds -> milliseconds (3 digits)
    mmm = f"{now.microsecond // 1000:03d}"
    return now.strftime("%Y%m%dT%H%M%S") + mmm


def utc_timestamp_millis(dt: datetime | None = None) -> str:
    """
    Return UTC timestamp in the *validator* format:

        YYYYMMDDTHHMMSSdmmm

    where:
      - YYYYMMDDTHHMMSS is UTC time
      - 'd' is a literal character
      - mmm are milliseconds (000–999)
    """
    now = dt or datetime.utcnow()
    ts_prefix = now.strftime("%Y%m%dT%H%M%S")  # YYYYMMDDTHHMMSS
    millis = int(now.microsecond / 1000)  # 0–999

    # IMPORTANT: literal 'd' between seconds and millis
    return f"{ts_prefix}d{millis:03d}"


def next_counter_for_service(output_dir: str, service_uid: str) -> int:
    """
    Local fallback: scan existing STAC Item JSON files and directories under output_dir
    to find the max NNNNNN for this Service_UID, then return +1.
    Replace this with a STAC API search if you have one.
    """
    max_ctr = 0
    # Look into common places: item directories or JSON filenames
    for root, _dirs, files in os.walk(output_dir):
        for name in files:
            base, ext = os.path.splitext(name)
            if ext.lower() not in {".json", ".geojson"}:
                continue
            m = ID_COUNTER_PATTERN.match(base)
            if not m:
                continue
            if m.group("svc") != service_uid:
                continue
            try:
                ctr = int(m.group("ctr"))
                if ctr > max_ctr:
                    max_ctr = ctr
            except ValueError:
                pass
    # Also check directory names (some pipelines name item folders by item-id)
    for root, dirs, _files in os.walk(output_dir):
        for d in dirs:
            m = ID_COUNTER_PATTERN.match(d)
            if m and m.group("svc") == service_uid:
                try:
                    ctr = int(m.group("ctr"))
                    if ctr > max_ctr:
                        max_ctr = ctr
                except ValueError:
                    pass
    return max_ctr + 1


def format_counter(n: int) -> str:
    return f"{n:06d}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a simple STAC structure for the provided image file."
    )
    parser.add_argument(
        "images",
        nargs="+",
        help="Path(s) to GDAL readable image files (comma-separated or space-separated)",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory where the STAC structure will be written (default: '.')",
    )
    parser.add_argument(
        "--collection-id",
        default="example-collection",
        help="Identifier for the STAC collection",
    )
    parser.add_argument(
        "--item-id",
        default=None,
        help="Optional identifier for the STAC item (defaults to input file name)",
    )
    parser.add_argument(
        "--service-uid",
        help="Service UID to use in the STAC Item ID (e.g., SS-WS-BS). Required if --auto-item-id is set.",
    )
    parser.add_argument(
        "--auto-item-id",
        action="store_true",
        help="Generate STAC Item ID for ad-hoc products per convention <Service_UID>_<YYYYMMDDTHHMMSSmmm>_<NNNNNN>.",
    )

    args = parser.parse_args()
    if args.auto_item_id:
        if not args.service_uid:
            raise SystemExit("--service-uid is required when using --auto-item-id")
        ts = utc_timestamp_millis()
        ctr = format_counter(
            next_counter_for_service(args.output_dir, args.service_uid)
        )
        # auto_item_id = f"{args.service_uid}_{ts}_{ctr}"  # <Service_UID>_<YYYYMMDDTHHMMSSmmm>_<NNNNNN>
        auto_item_id = f"{args.service_uid}_{ts}"  # <Service_UID>_<YYYYMMDDTHHMMSSmmm>
        item_id = auto_item_id
    else:
        item_id = args.item_id
    print(
        f"--> [stac_products] Creating item with service_uid={args.service_uid}, timestamp={ts} and ctr={ctr}"
    )
    print(f"--> [stac_products] Creating item_id={item_id}")

    # Support both comma-separated and space-separated inputs
    image_paths: list[str] = []
    for img in args.images:
        image_paths.extend([p for p in img.split(",") if p])

    data_input = image_paths[0] if len(image_paths) == 1 else image_paths

    create_stac_structure(
        data=data_input,
        output_dir=args.output_dir,
        collection_id=args.collection_id,
        item_id=item_id,
    )

    assets_path = Path(args.output_dir) / "assets"
    print(f"STAC structure created under: {assets_path.resolve()}")


if __name__ == "__main__":
    main()
