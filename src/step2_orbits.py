# step2_orbits.py

import os
import csv
import requests
from datetime import datetime
from dateutil import parser
import logging

def update_satellite_from_title(csv_file: str, output_file: str = None):
    """
    Updates the 'satellite' field in the CSV based on the 'title' field.
    """
    updated_rows = []

    with open(csv_file, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames

        if "title" not in fieldnames:
            raise ValueError("CSV must contain a 'title' column.")

        for row in reader:
            title = row.get("title", "")
            if "S1A" in title:
                row["satellite"] = "S1A"
            elif "S1B" in title:
                row["satellite"] = "S1B"
            updated_rows.append(row)

    # Write updated CSV
    out_path = output_file if output_file else csv_file
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated_rows)

    logging.info(f"Updated 'satellite' values written to {out_path}")

def list_remote_orbits(orbit_url):
    logging.info("Fetching orbit file list...")
    res = requests.get(orbit_url)
    if res.status_code != 200:
        logging.warning("Orbit server not reachable.")
        return []
    return [line[line.find("S1"):line.find(".EOF")+4] for line in res.text.splitlines() if ".EOF" in line]

def get_orbit_for_date(satellite, acq_date, orbit_files):
    try:
        acq_dt = parser.parse(acq_date)
        for orbit_file in [f for f in orbit_files if f.startswith(satellite)]:
            try:
                start = datetime.strptime(orbit_file.split("_V")[1].split("_")[0], "%Y%m%dT%H%M%S")
                end = datetime.strptime(orbit_file.split("_")[-1].replace(".EOF", ""), "%Y%m%dT%H%M%S")
                if start <= acq_dt <= end:
                    return orbit_file
            except:
                continue
    except:
        pass
    return None

def download_orbit_file(orbit_file, orbit_url, orbit_dir, username, password, dry_run=False):
    dest = os.path.join(orbit_dir, orbit_file)
    if os.path.exists(dest):
        logging.info(f"Orbit exists: {orbit_file}")
        return
    if dry_run:
        logging.info(f"[Dry-run] Would download orbit: {orbit_file}")
        return
    logging.info(f"Downloading orbit: {orbit_file}")
    wget_cmd = (f"wget -c --http-user={username} --http-password='{password}' " f"-O {dest} {orbit_url + orbit_file}")
    os.system(wget_cmd)

def run(config):
    logging.info("Step 2 - Downloading ASF Orbits")
    sentinel_cfg = config["sentinel"]
    username = sentinel_cfg.get("username")
    password = sentinel_cfg.get("password")
    orbit_url = "https://s1qc.asf.alaska.edu/aux_poeorb/"
    orbit_dir = "orbits"
    csv_file = "downloaded_metadata.csv"
    dry_run = config["runtime"].get("dry_run", False)

    os.makedirs(orbit_dir, exist_ok=True)

    # Update satellite column based on title
    update_satellite_from_title(csv_file)

    orbit_files = list_remote_orbits(orbit_url)
    if not orbit_files:
        logging.warning("No orbit files found.")
        return

    downloaded = set()

    with open(csv_file, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sat = row["satellite"]
            acq = row["acquisition_date"]
            if not sat or not acq or (sat, acq) in downloaded:
                continue

            orbit_file = get_orbit_for_date(sat, acq, orbit_files)
            if orbit_file:
                download_orbit_file(orbit_file, orbit_url, orbit_dir, username, password, dry_run)
                downloaded.add((sat, acq))
            else:
                logging.warning(f"No orbit found for {sat} at {acq}")

