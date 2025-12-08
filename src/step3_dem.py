# step3_dem.py

import os
import subprocess
import logging
import stat

def write_netrc(username, password):
    netrc_path = os.path.expanduser("~/.netrc")
    content = f"""machine urs.earthdata.nasa.gov
login {username}
password {password}
"""
    with open(netrc_path, "w") as f:
        f.write(content)
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    logging.info(".netrc file written for Earthdata access.")

def run(config):
    logging.info("Step 3 - DEM Generation")

    dem_cfg = config["dem"]
    bbox = dem_cfg["bbox"]
    dem_dir = dem_cfg.get("output_dir", "DEM")
    dry_run = config["runtime"].get("dry_run", False)

    env = config["environment"]
    sentinel_cfg = config.get("sentinel", {})
    username = sentinel_cfg.get("username")
    password = sentinel_cfg.get("password")

    if username and password:
        write_netrc(username, password)
    else:
        logging.warning("No username/password found for DEM download – skipping .netrc creation")

    bash_command = f"""
    source ~/.bashrc
    export PATH=$PATH:{env['topsStack_dir']}
    export ISCE_STACK={env['isce_stack_dir']}
    export PYTHONPATH=$PYTHONPATH:{os.path.dirname(env['topsStack_dir'])}:$ISCE_STACK
    mkdir -p {dem_dir}
    cd {dem_dir}
    dem.py -a stitch -r -s 1 -c --filling --filling_value 0 --bbox {bbox}
    """

    if dry_run:
        logging.info(f"[Dry-run] Would execute DEM generation with bbox: {bbox}")
        return

    logging.info("Executing DEM generation with dem.py...")
    subprocess.run(["bash", "-c", bash_command], check=True)
    logging.info("DEM generation completed.")

