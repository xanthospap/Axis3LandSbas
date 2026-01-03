# SBAS Sentinel-1 Deformation Service (LS-DF-SB-00)

This repository contains the source code for the **SBAS Sentinel-1 deformation monitoring service** used in the governmental HUB.  
It implements a full Small Baseline Subset (SBAS) InSAR chain using **ISCE2 (topsStack)** and **MintPy**, and packages the output as **STAC** items.

---

## Repository structure overview

High-level layout:

- `src/` – Python modules implementing the individual processing steps  
  - `step1_downloader.py` – Sentinel-1 data discovery & download (ASF Search, metadata CSV)  
  - `step2_orbits.py` – Sentinel-1 orbit download  
  - `step3_dem.py` – DEM download & preparation  
  - `step4_stack.py` – ISCE2/topsStack interferogram stack setup  
  - `step5_run_stack.py` – topsStack interferogram processing  
  - `step6_mintpy.py` – MintPy configuration & execution, GeoTIFF export

- Top-level Python entrypoints:
  - `SBAS.py` – Orchestrates steps 1–6 based on `config.yaml`  
  - `run_pipeline.py` – High-level wrapper to:
    - initialise/update `config.yaml` via `config_manager.py`
    - run `SBAS.py`
    - optionally run `stac_products.py` for STAC output
  - `config_manager.py` – Quote-preserving YAML config manager (`init`, `set`, `get`, `wizard`)  
  - `stac_products.py` – Generates STAC Collections/Items/Assets from the SBAS/MintPy outputs  
  - `stac_structure.py` – Helper functions for building the STAC JSON structure  
  - `ASF_availability.py` – Helper for ASF data availability checks

- Configuration:
  - `configs/config.yaml` – Main configuration template used in production  
  - `configs/config_test.yaml` – Example/test configuration

- Workflow & Hub integration:
  - `LS-DF-SB-00.cwl` – Main CWL workflow used by the governmental HUB  
  - `LS-DF-SB-00.yaml` – Example CWL job file / parameterisation  
  - `sbas.cwl`, `sbas_new.cwl` – Alternative / earlier CWL wrappers

- Containerisation:
  - `Dockerfile` – Micromamba-based image for running the service (used by the HUB)  

- Other:
  - `requirements.txt` – Python package dependencies (pip layer on top of conda/mamba)
  - `src/__init__.py` – Makes `src` a Python package

---

## Quickstart

### Run via Docker (recommended, aligns with HUB deployment)

1. **Build the image**

   From the repository root:

   ```bash
   docker build -t sbas-mamba .
   ```

2. **Run the container**

   Create a working directory on the host for data:

   ```bash
   mkdir -p /path/to/workdir
   docker run --rm -it -v /path/to/workdir:/work sbas-mamba bash
   ```

   Inside the container you will see the `base` environment:

   ```bash
   (base) root@container:/work#
   ```

3. **Initialise and customise the configuration**

   Inside the container:

   ```bash
   cd /work

   # Initialise config.yaml with defaults
   python /home/sbas/config_manager.py init

   # Set key parameters (examples – replace with your values)
   python /home/sbas/config_manager.py set working_dir "./"
   python /home/sbas/config_manager.py set sentinel.aoi "24.07,35.37,24.22,35.27"
   python /home/sbas/config_manager.py set sentinel.orbit "DESCENDING"
   python /home/sbas/config_manager.py set sentinel.start_date "20250101"
   python /home/sbas/config_manager.py set sentinel.end_date "20250401"
   python /home/sbas/config_manager.py set sentinel.username "<your_scihub_username>"
   python /home/sbas/config_manager.py set sentinel.password "<your_scihub_password>"
   ```

4. **Run the full SBAS + MintPy pipeline (without STAC)**

   ```bash
   python /home/sbas/SBAS.py --config config.yaml
   ```

5. **Run the pipeline with configuration + SBAS + STAC (via `run_pipeline.py`)**

   ```bash
   python /home/sbas/run_pipeline.py      --config-manager /home/sbas/config_manager.py      --config-path config.yaml      --init --force-init      --set working_dir=./      --set sentinel.aoi="24.07,35.37,24.22,35.27"      --set sentinel.orbit=DESCENDING      --set sentinel.start_date=20250101      --set sentinel.end_date=20250401      --set sentinel.username=<your_scihub_username>      --set sentinel.password=<your_scihub_password>      --sbas /home/sbas/SBAS.py      --stac /home/sbas/stac_products.py      --stac-collection-id LS-DF      --stac-service-uid LS-DF-SB-S1      --stac-auto-item-id
   ```

   This will:

   - ensure `config.yaml` exists and is updated,
   - run the SBAS pipeline,
   - generate STAC Collection/Items/Assets for the outputs.

---

## Libraries & frameworks

The service is built primarily on:

- **Python**
  - Target version: **3.10**

- **InSAR & SAR processing**
  - **ISCE2** (including **topsStack**) – Sentinel-1 interferogram generation and stack processing  
  - **MintPy** – Time-series InSAR (SBAS) processing, geocoding, velocity/time-series estimation

- **Geospatial stack**
  - **GDAL** – raster IO & CRS handling  
  - **rasterio** – raster access / convenience  
  - **shapely** – AOI geometry handling  
  - **pyresample** (via MintPy) – geocoding / resampling  

- **Data discovery / downloads**
  - **asf_search** – ASF Sentinel-1 data search and download

- **Configuration & workflow**
  - **ruamel.yaml** – quote-preserving YAML config manager  
  - **pystac** – STAC data model implementation

- **General Python deps**
  - `tqdm`, `requests`, `python-dateutil`, `h5py`, `dask`, `joblib`, etc. (see `requirements.txt`)

---

## How to run in the HUB environment

In the governmental HUB, this service is executed via the **CWL workflow**:

- `LS-DF-SB-00.cwl` (service ID: **LS-DF-SB-00**)

### Inputs (conceptual)

The CWL workflow exposes, among others:

- **Spatial extent**: `spatial_extent` – `[minLon, minLat, maxLon, maxLat]`  
- **Temporal range**: `start_date`, `end_date` – Sentinel-1 acquisition dates (`YYYYMMDD`)  
- **Orbit direction**: `orbit_direction` – `ASCENDING` or `DESCENDING`  
- **DEM & stack extents**: `dem_bbox`, `stack_bbox`  
- **Reference information**:
  - `reference_date` – SBAS reference date
  - `mintpy_reference_lalo` – reference point in lat/lon
- **Credentials**: `sentinel_username`, `sentinel_password` – for Sentinel-1 data download

### Execution (simplified)

Internally, the CWL `CommandLineTool`:

1. Calls `run_pipeline.py` inside the Docker image.
2. Uses `config_manager.py` with multiple `--set key=value` overrides to derive `config.yaml` from HUB inputs.
3. Runs `SBAS.py` to execute steps 1–6 (Sentinel download → orbits → DEM → topsStack → MintPy).
4. Runs `stac_products.py` to create:
   - a STAC **Collection** (e.g. `items/LS-DF/collection.json`),
   - STAC **Items** and **Assets** in the `items/` and `assets/` directories.

### HUB Outputs

According to `LS-DF-SB-00.cwl`, the main outputs are:

- `collection` – `items/LS-DF/collection.json` (STAC Collection)  
- `assets` – `assets/` directory containing produced rasters (e.g. `geo_velocity.tif`) and other files  
- `items` – `items/` directory containing STAC Items (one per product)  
- `log` – `execution_run.log` with the pipeline log

---

This README is intended as a concise overview; for more details on specific parameters or step-level behaviour, please refer to the source files in `src/` and the comments in `configs/config.yaml`, `run_pipeline.py`, and `LS-DF-SB-00.cwl`.
