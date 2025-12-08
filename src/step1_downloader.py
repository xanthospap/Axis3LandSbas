# step1_downloader.py

import os
import csv
import xml.etree.ElementTree as ET
import zipfile
import asf_search as asf
from shapely.geometry import Polygon
from shapely.wkt import loads as wkt_loads
import logging

def setup_metadata_csv(csv_file):
    if not os.path.exists(csv_file):
        with open(csv_file, "w", newline="") as f:
            csv.writer(f).writerow([
                "id", "title", "acquisition_date", "satellite", "orbit_number",
                "polarization", "beam_mode", "orbit_direction", "relative_orbit",
                "frame_id", "path", "slice_number", "total_slices", "aoi", "download_url", "status"
            ])

def setup_download_dir(download_dir):
    os.makedirs(download_dir, exist_ok=True)

def validate_and_convert_aoi(aoi):
    try:
        wkt_loads(aoi)
        return aoi
    except:
        coords = list(map(float, aoi.split(",")))
        if len(coords) == 4:
            lon_min, lat_min, lon_max, lat_max = coords
            polygon = Polygon([
                (lon_min, lat_min), (lon_max, lat_min),
                (lon_max, lat_max), (lon_min, lat_max),
                (lon_min, lat_min)
            ])
            return polygon.wkt
        raise ValueError("Invalid AOI format")

def extract_metadata_from_manifest(zip_file):
    metadata = {k: "N/A" for k in [
        "acquisition_date", "satellite", "orbit_number", "polarization",
        "beam_mode", "orbit_direction", "relative_orbit", "frame_id",
        "path", "slice_number", "total_slices"
    ]}
    try:
        with zipfile.ZipFile(zip_file, "r") as z:
            mfile = next((f for f in z.namelist() if "manifest.safe" in f), None)
            if not mfile:
                return metadata
            with z.open(mfile) as mf:
                tree = ET.parse(mf)
                root = tree.getroot()
                ns = {
                    "s1": "http://www.esa.int/safe/sentinel-1.0",
                    "s1sar": "http://www.esa.int/safe/sentinel-1.0/sentinel-1/sar/level-1",
                    "s1meta": "http://www.esa.int/safe/sentinel-1.0/sentinel-1"
                }

                metadata["acquisition_date"] = root.findtext(".//s1:acquisitionPeriod/s1:startTime", namespaces=ns)
                platform = root.find(".//s1:platform", ns)
                metadata["satellite"] = f"S1{platform.findtext('s1:number', default='')}" if platform is not None else "N/A"

                orbit = root.find(".//s1:orbitReference", ns)
                if orbit is not None:
                    metadata["orbit_number"] = orbit.findtext("s1:orbitNumber", default="", namespaces=ns)
                    metadata["relative_orbit"] = orbit.findtext("s1:relativeOrbitNumber", default="", namespaces=ns)
                    metadata["path"] = metadata["relative_orbit"]

                orbit_prop = root.find(".//s1meta:orbitProperties", ns)
                if orbit_prop is not None:
                    metadata["orbit_direction"] = orbit_prop.findtext("s1meta:pass", default="", namespaces=ns)

                instr = root.find(".//s1:instrument", ns)
                if instr is not None:
                    metadata["beam_mode"] = instr.findtext(".//s1sar:mode", default="", namespaces=ns)

                gp = root.find(".//s1sar:standAloneProductInformation", ns)
                if gp is not None:
                    pols = gp.findall("s1sar:transmitterReceiverPolarisation", ns)
                    metadata["polarization"] = ", ".join([p.text for p in pols if p is not None])
                    metadata["slice_number"] = gp.findtext("s1sar:sliceNumber", default="", namespaces=ns)
                    metadata["total_slices"] = gp.findtext("s1sar:totalSlices", default="", namespaces=ns)
    except Exception as e:
        logging.error(f"Metadata extraction error: {e}")

    return metadata

def save_metadata(csv_file, product_id, title, metadata, aoi, download_url, status):
    with open(csv_file, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            product_id, title, metadata["acquisition_date"],
            metadata["satellite"], metadata["orbit_number"],
            metadata["polarization"], metadata["beam_mode"],
            metadata["orbit_direction"], metadata["relative_orbit"],
            metadata["frame_id"], metadata["path"],
            metadata["slice_number"], metadata["total_slices"],
            aoi, download_url, status
        ])

def run(config):
    logging.info("Step 1 - Sentinel-1 Downloader")
    sentinel_cfg = config["sentinel"]
    download_dir = "SLC"
    csv_file = "downloaded_metadata.csv"

    setup_metadata_csv(csv_file)
    setup_download_dir(download_dir)

    aoi = validate_and_convert_aoi(sentinel_cfg["aoi"])
    start_date = f"{sentinel_cfg['start_date'][:4]}-{sentinel_cfg['start_date'][4:6]}-{sentinel_cfg['start_date'][6:]}"
    end_date = f"{sentinel_cfg['end_date'][:4]}-{sentinel_cfg['end_date'][4:6]}-{sentinel_cfg['end_date'][6:]}"
    dry_run = config["runtime"].get("dry_run", False)

    params = {
        "platform": asf.PLATFORM.SENTINEL1,
        "processingLevel": "SLC",
        "start": start_date,
        "end": end_date,
        "intersectsWith": aoi,
        "flightDirection": sentinel_cfg["orbit"]
    }
    if sentinel_cfg["path"]:
        params["relativeOrbit"] = sentinel_cfg["path"]
    if sentinel_cfg["frame_id"]:
        params["frame"] = sentinel_cfg["frame_id"]

    logging.info("Searching ASF for products...")
    results = asf.search(**params)
    logging.info(f"Found {len(results)} images.")

    for item in results:
        title = item.properties["sceneName"]
        download_url = item.properties["url"]
        zip_file = os.path.join(download_dir, f"{title}.zip")

        if dry_run:
            logging.info(f"[Dry-run] Would download: {title} → {zip_file}")
            continue

        if os.path.exists(zip_file):
            logging.info(f"Skipping {title} (already downloaded)")
            continue

        logging.info(f"Downloading {title}...")
        username = sentinel_cfg.get("username")
        password = sentinel_cfg.get("password")

        if not username or not password:
            raise ValueError("Missing 'username' or 'password' in config['sentinel']")
        wget_cmd = (f"wget -c --http-user={username} --http-password='{password}' " f"-O {zip_file} {download_url}")
        exit_code = os.system(wget_cmd)
        logging.info(f"wget exit code: {exit_code}")
        metadata = extract_metadata_from_manifest(zip_file)
        save_metadata(csv_file, title, title, metadata, aoi, download_url, "Downloaded")
        
