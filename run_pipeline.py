#!/usr/bin/env python3
"""
Run pipeline:
- init config (optional)
- apply overrides (repeatable --set key=value)
- run SBAS.py (optional) with: --config <config.yaml> (by default)
- run stac_products.py (optional)
- pass through extra args to SBAS after a "--" separator

Examples:

# 1) Config + SBAS + STAC (all-in-one)
python run_pipeline.py \
  --sbas SBAS.py \
  --stac stac_products.py \
  --set sentinel.username=vtsironi \
  --set sentinel.password="My$ecret!" \
  --set sentinel.start_date=20250115 \
  -- --resume

# 2) Config only (init + set, no SBAS, no STAC)
python run_pipeline.py --init --force-init \
  --set working_dir=./work \
  --set logging.log_level=DEBUG

# 3) STAC only (skip SBAS)
python run_pipeline.py --stac stac_products.py

# 4) SBAS only (with flags after "--")
python run_pipeline.py --sbas SBAS.py -- --dry-run --step step4_stack_interferograms

# 5) Use different config path and python
python run_pipeline.py \
  --config-path myconfig.yaml \
  --python /opt/miniconda/envs/isce2/bin/python \
  --sbas SBAS.py
"""

import os, sys, subprocess

#CONDA_ENV = "sbas"

# Detect if we are already inside the env
#if os.environ.get("CONDA_DEFAULT_ENV") != CONDA_ENV:
    # Relaunch this script inside the env
#    cmd = ["conda", "run", "-n", CONDA_ENV, "python"] + sys.argv
#    sys.exit(subprocess.call(cmd))

import argparse
import os
import shlex
import sys
import subprocess
from pathlib import Path

# ---------- helpers ----------
def run(cmd, env=None, dry=False):
    print(f"$ {' '.join(shlex.quote(c) for c in cmd)}")
    if dry:
        return 0
    return subprocess.call(cmd, env=env)

def parse_kv(arg: str):
    if "=" not in arg:
        raise argparse.ArgumentTypeError(f"must be key=value, got: {arg}")
    key, value = arg.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        raise argparse.ArgumentTypeError(f"empty key in: {arg}")
    return key, value
# -----------------------------

def main(argv=None):
    argv = argv or sys.argv[1:]

    # Split passthrough args for SBAS after "--"
    passthrough = []
    if "--" in argv:
        idx = argv.index("--")
        passthrough = argv[idx + 1 :]
        argv = argv[:idx]

    ap = argparse.ArgumentParser(description="Configure and run SBAS pipeline (SBAS and/or STAC)")
    ap.add_argument("--config-manager", default="config_manager.py",
                    help="Path to config_manager.py (default: config_manager.py)")
    ap.add_argument("--config-path", default="config.yaml",
                    help="Path to config.yaml (default: config.yaml)")
    ap.add_argument("--python", default=sys.executable,
                    help="Python executable to run SBAS/STAC (default: current Python)")

    # SBAS is now OPTIONAL
    ap.add_argument("--sbas", required=False,
                    help="Path to SBAS.py (omit to skip SBAS step)")

    ap.add_argument("--init", action="store_true",
                    help="Run `init` to (re)create config from defaults")
    ap.add_argument("--force-init", action="store_true",
                    help="Use with --init to overwrite an existing config")
    ap.add_argument("--wizard", action="store_true",
                    help="Open interactive wizard before running SBAS")

    ap.add_argument("--set", dest="sets", action="append", default=[], type=parse_kv,
                    help="Override config value (repeatable). key=value (e.g., sentinel.start_date=20250115)")
    ap.add_argument("--env", dest="envs", action="append", default=[], type=parse_kv,
                    help="Environment variable for subprocesses (repeatable). NAME=value")

    ap.add_argument("--dry-run", action="store_true",
                    help="Print commands without executing")
    ap.add_argument("--no-config-flag", action="store_true",
                    help="Do NOT append '--config <config-path>' when running SBAS")

    # ---------- STAC (CLI-only; not in YAML) ----------
    #ap.add_argument("--stac", help="Path to stac_products.py (omit to skip STAC step)")
    #ap.add_argument("--stac-raster", help="STAC positional #1 (raster .tif); default topsStack/mintpy/geo_velocity.tif")
    #ap.add_argument("--stac-hdf5", help="STAC positional #2 (HDF5 dataset path); default HDF5:\"topsStack/mintpy/geo/geo_velocity.h5\"://velocityStd")
    #ap.add_argument("--stac-collection-id", help="--collection-id value (default LS-DF)")
    #ap.add_argument("--stac-item-id", help="--item-id value (default LS-DF-SB-S1)")
    # --------------------------------------------------
    # ---------- STAC (CLI-only; not in YAML) ----------
    ap.add_argument("--stac", help="Path to stac_products.py (omit to skip STAC step)")
    ap.add_argument("--stac-raster", help="STAC positional #1 (raster .tif); default topsStack/mintpy/geo_velocity.tif")
    ap.add_argument("--stac-hdf5", help='STAC positional #2 (HDF5 dataset path); default HDF5:"topsStack/mintpy/geo/geo_velocity.h5"://velocityStd')
    ap.add_argument("--stac-collection-id", help="--collection-id value (default LS-DF)")

    # old behavior was fixed item-id default; now it’s optional (only if you’re NOT using auto)
    ap.add_argument("--stac-item-id", help="--item-id value (omit if you use --stac-auto-item-id)")

    # NEW: ad-hoc generator wiring
    ap.add_argument("--stac-service-uid", help="--service-uid value (required if --stac-auto-item-id)")
    ap.add_argument("--stac-auto-item-id", action="store_true", help="Pass --auto-item-id to stac_products.py (ad-hoc ID)")
    # --------------------------------------------------

    args = ap.parse_args(argv)

    cfgmgr = Path(args.config_manager)
    cfg = Path(args.config_path)

    if not cfgmgr.exists():
        ap.error(f"config_manager not found: {cfgmgr}")

    # 1) init (optional or auto if missing)
    if args.init:
        cmd = [sys.executable, str(cfgmgr), "--path", str(cfg), "init"]
        if args.force_init:
            cmd.append("--force")
        rc = run(cmd, dry=args.dry_run)
        if rc != 0:
            sys.exit(rc)
    else:
        # If config missing entirely, create once (non-forced)
        if not cfg.exists():
            cmd = [sys.executable, str(cfgmgr), "--path", str(cfg), "init"]
            rc = run(cmd, dry=args.dry_run)
            if rc != 0:
                sys.exit(rc)

    # 2) apply overrides
    for key, value in args.sets:
        rc = run([sys.executable, str(cfgmgr), "--path", str(cfg), "set", key, value],
                 dry=args.dry_run)
        if rc != 0:
            sys.exit(rc)

    # 3) wizard (optional)
    if args.wizard:
        rc = run([sys.executable, str(cfgmgr), "--path", str(cfg), "wizard"],
                 dry=args.dry_run)
        if rc != 0:
            sys.exit(rc)

    # Prepare environment for subprocesses
    env = os.environ.copy()
    for name, val in args.envs:
        env[name] = val

    # Track final exit code (0 if nothing ran)
    final_rc = 0

    # 4) run SBAS.py (optional)
    if args.sbas:
        sbas = Path(args.sbas)
        if not sbas.exists():
            ap.error(f"SBAS.py not found: {sbas}")

        sbas_cmd = [args.python, str(sbas)]
        if not args.no_config_flag:
            sbas_cmd += ["--config", str(cfg)]
        if passthrough:
            sbas_cmd += passthrough

        rc = run(sbas_cmd, env=env, dry=args.dry_run)
        if rc != 0:
            sys.exit(rc)  # if SBAS fails, stop here
        final_rc = rc  # likely 0


    # 5) run STAC (optional; independent of SBAS)
    if args.stac:
        stac = Path(args.stac)
        if not stac.exists():
            ap.error(f"stac_products.py not found: {stac}")

        raster = args.stac_raster or "topsStack/mintpy/geo_velocity.tif"
        hdf5 = args.stac_hdf5 or 'HDF5:"topsStack/mintpy/geo/geo_velocity.h5"://velocityStd'
        collection_id = args.stac_collection_id or "LS-DF"

        # Build base command
        stac_cmd = [
            args.python, str(stac),
            raster, hdf5,
            "--collection-id", collection_id,
        ]

        # Choose ID mode
        if args.stac_auto_item_id:
            service_uid = args.stac_service_uid or "LS-DF-SB-S1"
            stac_cmd += ["--service-uid", service_uid, "--auto-item-id"]
        else:
            # manual item-id path (optional)
            if args.stac_item_id:
                stac_cmd += ["--item-id", args.stac_item_id]

        rc = run(stac_cmd, env=env, dry=args.dry_run)
        final_rc = rc


    sys.exit(final_rc)

if __name__ == "__main__":
    main()

