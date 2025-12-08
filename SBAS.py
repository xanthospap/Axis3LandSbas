# run.py

import argparse
import yaml
import logging
import os
import sys

# Step modules
from src import step1_downloader, step2_orbits, step3_dem, step4_stack, step5_run_stack, step6_mintpy

STEPS = [
    ("step1_download_sentinel", step1_downloader),
    ("step2_download_orbits", step2_orbits),
    ("step3_dem_creation", step3_dem),
    ("step4_stack_interferograms", step4_stack),
    ("step5_run_stack", step5_run_stack),
    ("step6_run_mintpy", step6_mintpy)
]

def setup_logger(log_dir, level="INFO"):
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(log_dir, "pipeline.log")),
            logging.StreamHandler(sys.stdout)
        ]
    )

def load_config(config_path):
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def run_pipeline(config, specific_step=None, resume=False, dry_run=False):
    steps_config = config.get("steps", {})
    start_from_step = config.get("runtime", {}).get("start_from_step", None)

    logging.info("Pipeline started.")
    started = not start_from_step

    for step_name, module in STEPS:
        if not steps_config.get(step_name, False):
            logging.info(f"Skipping {step_name} (disabled in config)")
            continue

        if specific_step and step_name != specific_step:
            continue

        if resume and start_from_step and step_name != start_from_step and not started:
            logging.info(f"Resuming: skipping {step_name}")
            continue

        started = True

        logging.info(f"=== Running {step_name} ===")
        if dry_run:
            logging.info(f"[Dry-Run] Would execute {step_name}")
            continue

        try:
            module.run(config)
            logging.info(f"Completed {step_name}")
        except Exception as e:
            logging.exception(f"Step {step_name} failed: {e}")
            sys.exit(1)

    logging.info("Pipeline finished.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SBAS_SAT4GAIA Pipeline Runner")
    parser.add_argument("--config", type=str, required=True, help="Path to config.yaml")
    parser.add_argument("--step", type=str, help="Run a single step only (step name)")
    parser.add_argument("--resume", action="store_true", help="Resume from step specified in config")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (simulate only)")

    args = parser.parse_args()
    config = load_config(args.config)

    setup_logger(config["logging"]["log_dir"], config["logging"].get("log_level", "INFO"))

    run_pipeline(
        config,
        specific_step=args.step,
        resume=args.resume,
        dry_run=args.dry_run
    )
