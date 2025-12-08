import os
import subprocess
import logging

def run(config):
    logging.info("Step 6 - MintPy Preparation and Execution")
    
    ref_lalo = config.get("mintpy", {}).get("reference_lalo", "auto")
    if isinstance(ref_lalo, list):
    	ref_lalo_str = f"{ref_lalo[0]},{ref_lalo[1]}"
    else:
    	ref_lalo_str = str(ref_lalo)

    env = config["environment"]
    mintpy_dir = os.path.join("topsStack", "mintpy")
    os.makedirs(mintpy_dir, exist_ok=True)

    config_filename = "mintpy_config.txt"
    config_path = os.path.join(mintpy_dir, config_filename)
    dry_run = config["runtime"].get("dry_run", False)

   
        # --- Write MintPy config --- #
    mintpy_config = f"""##-------------------------------- MintPy -----------------------------##
mintpy.load.processor        = isce
mintpy.load.metaFile         = ../reference/IW*.xml
mintpy.load.baselineDir      = ../baselines
mintpy.load.unwFile          = ../merged/interferograms/*/filt_*.unw
mintpy.load.corFile          = ../merged/interferograms/*/filt_*.cor
mintpy.load.connCompFile     = ../merged/interferograms/*/filt_*.unw.conncomp
mintpy.load.demFile          = ../merged/geom_reference/hgt.rdr
mintpy.load.lookupYFile      = ../merged/geom_reference/lat.rdr
mintpy.load.lookupXFile      = ../merged/geom_reference/lon.rdr
mintpy.load.incAngleFile     = ../merged/geom_reference/los.rdr
mintpy.load.azAngleFile      = ../merged/geom_reference/los.rdr
mintpy.load.shadowMaskFile   = ../merged/geom_reference/shadowMask.rdr
mintpy.load.waterMaskFile    = None

mintpy.reference.lalo        = {ref_lalo_str}

mintpy.unwrapError.method          = bridging
mintpy.unwrapError.waterMaskFile   = no
mintpy.unwrapError.connCompMinArea = auto

mintpy.networkInversion.weightFunc      = auto
mintpy.networkInversion.waterMaskFile   = no
mintpy.networkInversion.maskDataset     = coherence
mintpy.networkInversion.maskThreshold   = 0.1

mintpy.troposphericDelay.method = no

mintpy.topographicResidual                   = auto
mintpy.topographicResidual.polyOrder         = auto
mintpy.topographicResidual.phaseVelocity     = auto

mintpy.timeFunc.uncertaintyQuantification = auto
mintpy.timeFunc.timeSeriesCovFile         = auto
mintpy.timeFunc.bootstrapCount            = auto

mintpy.geocode              = auto
mintpy.geocode.laloStep     = -0.000555556,0.000555556
mintpy.geocode.interpMethod = auto
mintpy.geocode.fillValue    = auto

mintpy.save.kmz             = auto
"""

    with open(config_path, "w") as f:
        f.write(mintpy_config)
    logging.info(f"MintPy config created at: {config_path}")

    if dry_run:
        logging.info("[Dry-run] Would execute prep_isce.py + smallbaselineApp.py")
        return

    # --- Single-env execution (no conda.sh, no conda activate) ---
    # We are already running inside micromamba env 'base' (ENTRYPOINT handles that).
    bash_script = f"""
set -e

echo "=== Running prep_isce.py ==="
cd topsStack
prep_isce.py -f "./merged/interferograms/*/filt_*.unw" -m ./reference/IW1.xml -b ./baselines/ -g ./merged/geom_reference/

echo "=== Running smallbaselineApp.py ==="
cd mintpy
smallbaselineApp.py {config_filename}

echo "=== Save in GeoTIFF format ==="
save_gdal.py geo/geo_velocity.h5
"""

    try:
        subprocess.run(["bash", "-c", bash_script], check=True)
        logging.info("Step6 completed successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Step6 failed: {e}")
        raise

