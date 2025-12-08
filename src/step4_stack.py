# step4_stack.py

import os
import subprocess
import logging
import glob

# Automatically detect DEM file
def find_dem_file(dem_dir):
    dem_files = glob.glob(os.path.join(dem_dir, "*.dem.wgs84"))
    if not dem_files:
        raise FileNotFoundError("No DEM .wgs84 file found in DEM directory")
    if len(dem_files) > 1:
        logging.warning("Multiple DEM files found, using the first one.")
    return os.path.basename(dem_files[0])
    
def run(config):
    logging.info("Step 4 - Stack Interferograms")

    stack_cfg = config["stack"]
    bbox = " ".join(map(str, stack_cfg["bbox"]))
    dem_dir = "DEM"  # folder where your .wgs84 DEM is saved
    dem_path = find_dem_file(dem_dir)   # <--- AUTOMATICALLY GET THE DEM NAME
    reference_date = stack_cfg["reference_date"]
    aux_cal_path = stack_cfg["aux_cal_path"]
    tops_cfg = stack_cfg.get("config", None)
    dry_run = config["runtime"].get("dry_run", False)
    
    env = config["environment"]

    bash_script = f"""
    source ~/.bashrc
    export PATH=$PATH:{env['topsStack_dir']}
    export ISCE_STACK={env['isce_stack_dir']}
    export PYTHONPATH=$PYTHONPATH:{os.path.dirname(env['topsStack_dir'])}:$ISCE_STACK
    mkdir -p topsStack
    cd topsStack
    stackSentinel.py \\
        --bbox '{bbox}' \\
        --dem ../DEM/{dem_path} \\
        --swath_num '1 2 3' \\
        --reference_date {reference_date} \\
        --coregistration geometry \\
        -W interferogram \\
        --num_connections 3 \\
        --azimuth_looks 5 \\
        --range_looks 15 \\
        -s ../SLC \\
        -a {aux_cal_path} \\
        -o ../orbits \\
        {"--config ../" + tops_cfg if tops_cfg else ""}
    """

    if dry_run:
        logging.info(f"[Dry-run] Would execute stackSentinel.py with reference date {reference_date}")
        return

    logging.info("Running stackSentinel.py...")
    subprocess.run(["bash", "-c", bash_script], check=True)
    logging.info("Stacking completed.")

