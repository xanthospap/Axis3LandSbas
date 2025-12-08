# step5_run_stack.py

import os
import subprocess
import logging

def run(config):
    logging.info("Step 5 - Running topsStack Steps")

    env = config["environment"]

    runfiles_dir = os.path.join("topsStack", "run_files")
    log_dir = "logs"
    dry_run = config["runtime"].get("dry_run", False)

    os.makedirs(log_dir, exist_ok=True)
    
    isce_run = os.path.join(config["environment"]["topsStack_dir"], "run.py")

    step_files = [
        "run_01_unpack_topo_reference",
        "run_02_unpack_secondary_slc",
        "run_03_average_baseline",
        "run_04_fullBurst_geo2rdr",
        "run_05_fullBurst_resample",
        "run_06_extract_stack_valid_region",
        "run_07_merge_reference_secondary_slc",
        "run_08_generate_burst_igram",
        "run_09_merge_burst_igram",
        "run_10_filter_coherence",
        "run_11_unwrap"
    ]

    for step in step_files:
        run_path = os.path.join(runfiles_dir, step)
        log_path = os.path.join(log_dir, f"{step}.log")

        if dry_run:
            logging.info(f"[Dry-run] Would run: {step}")
            continue

        logging.info(f"Running: {step}")
        # Prepare the full bash command with environment exports
        bash_script = f"""
        source ~/.bashrc
        export PATH=$PATH:{env['topsStack_dir']}
        export ISCE_STACK={env['isce_stack_dir']}
        export PYTHONPATH=$PYTHONPATH:{os.path.dirname(env['topsStack_dir'])}:$ISCE_STACK
        {isce_run} -i {run_path}
        """

        try:
            with open(log_path, "w") as log_file:
                subprocess.run(["bash", "-c", bash_script], stdout=log_file, stderr=subprocess.STDOUT, check=True)
            logging.info(f"Completed: {step}")
        except subprocess.CalledProcessError:
            logging.error(f"Failed: {step} (see {log_path})")
            raise

    logging.info("All topsStack steps finished.")

