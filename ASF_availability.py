#!/usr/bin/env python3
"""
ASF (LS-DF-SB-00) service availability.

Arguments (aligned with your workflow):
  --start_date YYYYMMDD
  --end_date   YYYYMMDD
  --bbox       "<WKT POLYGON>" OR "lon_min,lat_min,lon_max,lat_max"

Exit codes:
  0 -> success (service available)
  1 -> failure (service unavailable or invalid inputs)
"""
import os, sys, subprocess

#
# !!! No CONDA stuff neede anymore !!!
#
#CONDA_ENV = "sbas"
#Detect if we are already inside the env
#if os.environ.get("CONDA_DEFAULT_ENV") != CONDA_ENV:
#    # Relaunch this script inside the env
#    cmd = ["conda", "run", "-n", CONDA_ENV, "python"] + sys.argv
#    sys.exit(subprocess.call(cmd))

import logging
import sys
import argparse
from typing import Dict, Any
from datetime import datetime
from shapely.geometry import Polygon
from shapely.wkt import loads as wkt_loads

try:
    import asf_search as asf
except Exception:
    asf = None

LOG_FILE = "execution_data_analysis.log"
LOG_FORMAT = "%(asctime)s %(levelname)s: %(message)s"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format=LOG_FORMAT, force=True)


def validate_and_convert_aoi(aoi: str) -> str:
    """Accept WKT or 'lon_min,lat_min,lon_max,lat_max' and return WKT."""
    try:
        wkt_loads(aoi)
        return aoi
    except Exception:
        parts = [p.strip() for p in aoi.split(",")]
        if len(parts) == 4:
            lon_min, lat_min, lon_max, lat_max = map(float, parts)
            polygon = Polygon([
                (lon_min, lat_min), (lon_max, lat_min),
                (lon_max, lat_max), (lon_min, lat_max),
                (lon_min, lat_min)
            ])
            return polygon.wkt
        raise ValueError("Invalid AOI format: provide WKT or 'lon_min,lat_min,lon_max,lat_max'")


def yyyymmdd_to_iso(dt_str: str) -> str:
    """Convert 'YYYYMMDD' to 'YYYY-MM-DDTHH:MM:SS'."""
    dt = datetime.strptime(dt_str, "%Y%m%d")
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# LS-DF-SB-00 check
# ---------------------------------------------------------------------------

def check_ls_df_sb_00(config: Dict[str, Any]) -> bool:
    """Perform ASF availability check (LS-DF-SB-00). Return True/False."""
    setup_logging()

    if asf is None:
        logging.error("asf_search is not installed")
        return False

    sentinel_cfg = config.get("sentinel", {})
    if not sentinel_cfg:
        logging.error("Missing 'sentinel' section in config")
        return False

    try:
        aoi_wkt = validate_and_convert_aoi(sentinel_cfg["aoi"])
    except Exception as exc:
        logging.error("AOI validation failed: %s", exc)
        return False

    try:
        start_iso = yyyymmdd_to_iso(sentinel_cfg["start_date"])
        end_origin = datetime.strptime(sentinel_cfg["end_date"], "%Y%m%d")
        end_iso = end_origin.replace(hour=23, minute=59, second=59).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception as exc:
        logging.error("Date parsing failed: %s", exc)
        return False

    params = {
        "platform": asf.PLATFORM.SENTINEL1,
        "processingLevel": "SLC",
        "start": start_iso,
        "end": end_iso,
        "intersectsWith": aoi_wkt,
        "maxResults": 1,
    }

    logging.info("ASF LS-DF-SB-00 probe query: %s", params)

    try:
        _ = asf.geo_search(**params)
        logging.info("ASF service responded – availability check passed.")
        return True
    except Exception as exc:
        logging.error("ASF availability check failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Main wrapper
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="ASF LS-DF-SB-00 availability probe")
    parser.add_argument("--start_date", required=True, help="Start date (YYYYMMDD)")
    parser.add_argument("--end_date", required=True, help="End date (YYYYMMDD)")
    parser.add_argument("--bbox", required=True, help="AOI (WKT polygon or lon_min,lat_min,lon_max,lat_max)")

    args = parser.parse_args()

    # Wrap into same config structure as step1_downloader
    config = {
        "sentinel": {
            "aoi": args.bbox,       
            "start_date": args.start_date,
            "end_date": args.end_date,
        }
    }

    ok = check_ls_df_sb_00(config)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

