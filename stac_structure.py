"""Utility to create a minimal STAC structure from geospatial data."""

from __future__ import annotations
from rasterio.warp import transform_bounds
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence, Tuple, Union, List
import numpy as np
from PIL import Image
import pystac
import rasterio

try:
    from osgeo import gdal, osr

    gdal.UseExceptions()  # clearer errors; avoids future warning about exceptions
except Exception:
    gdal = None
    osr = None

try:
    import xarray as xr
except Exception:
    xr = None


# Mapping of collection and item identifiers to their descriptions
# The first level keys are collection IDs and the nested
# ``items`` dictionaries contain the allowed item IDs for each collection.
COLLECTIONS = {
    "FS-FM": {
        "description": "Forest Types Mapping",
        "items": {
            "FS-FM-FC-A": "Forest Types Maps",
            "FS-FM-FC-B": "Forest Types Maps",
            "FS-FM-TC": "Tree Cover Density Maps",
            "FS-FM-FF-S1": "Forest Types Maps / Forest Fuel Maps",
            "FS-FM-FF-S2": "Forest Types Maps / Forest Fuel Maps",
            "FS-FM-FF-A2": "Forest Types Maps / Forest Fuel Maps",
            "FS-FM-FF-A1": "Forest Types Maps / Forest Fuel Maps",
        },
    },
    "FS-FT": {
        "description": "Fuel Type Mapping",
        "items": {"FS-FT-FT-00": "Fuel Type Maps"},
    },
    "FS-HA": {
        "description": "Forest and NATURA Areas Health Assessment",
        "items": {"FS-HA-HT-B-A2": "FNA Health trends"},
    },
    "FS-BI": {
        "description": "Biodiversity Mapping of Forest and NATURA Areas",
        "items": {
            "FS-BI-SI": "Biodiversity Indices",
            "FS-BI-HS": "Biodiversity Hot Spots Detection",
            "FS-BI-BT": "Biodiversity Trends",
            "FS-BI-TM": "Biodiversity Trend Maps in Disturbed Ecosystems",
        },
    },
    "FS-TM": {
        "description": "Forest and NATURA Areas Threat Monitoring",
        "items": {"FS-TM-TM-B-A2": "FNA Threat monitoring"},
    },
    "LS-LC": {
        "description": "Land Use/Land Cover",
        "items": {
            "LS-LC-CM-A": "Land Cover Classification for the period 2015-2024",
            "LS-LC-CM-B": "Land Cover Classification for the period 2025+",
            "LS-LC-CA-A": "Change Analysis for the period 2015-2024",
            "LS-LC-CA-B": "Change Analysis for the period 2025+",
        },
    },
    "LS-DF": {
        "description": "Deformation Monitoring",
        "items": {
            "LS-DF-PS-S1": "PSI displacement maps for Greece",
            "LS-DF-SB-S1": "SBAS (Distributed Scatterers) displacement maps for Greece",
            "LS-DF-IT-S1": "Co-seismic InSAR products for Greece",
            "LS-DF-LS-00": "On-demand LANDSLIDE tracking",
        },
    },
    "LS-UA": {
        "description": "Urban Analytics Services",
        "items": {
            "LS-UA-LST-BA1": "Land Surface Temperature Map (200m)",
            "LS-UA-AT-BA1": "Air Temperature Map (200m)",
            "LS-UA-SUHI-BA1": "SUHI/UHI Map (200m)",
            "LS-UA-UPHI-B": "Urban and Public Health",
            "LS-UA-AQM-B": "Urban Air Quality AI Model training",
            "LS-UA-AQ-B": "Urban Air Quality",
        },
    },
}

# ---- STAC extensions: projection, raster, processing ----
PROJ_EXT = "https://stac-extensions.github.io/projection/v1.0.0/schema.json"
RASTER_EXT = "https://stac-extensions.github.io/raster/v1.1.0/schema.json"
PROCESSING_EXT = "https://stac-extensions.github.io/processing/v1.2.0/schema.json"
# Axis-3 processing metadata
PROCESSING_FACILITY = "AXIS-3 LAND"
PROCESSING_LEVEL = "L3"
PROCESSING_VERSION = "1.1.0"
PROCESSING_SHORT_VERSION = "1.1"
PROCESSING_SOFTWARE_NAME = "Axis3LandSbas"
PROCESSING_SOFTWARE_REPO = "https://github.com/HellenicSpaceCenter/Axis3LandSbas"


# Asset title as
# <Product Label> – <AOI> – <Logical Layer> – <Temporal Baseline>
# "SBAS (Distributed Scatterers) displacement maps for Greece – Greece – Line-of-sight displacement velocity – 2025-12-16T07:35:09Z",
def GEO_VELOCITY_TITLE(t=datetime.now(timezone.utc)):
    return f"SBAS displacement maps for Greece - Greece - LOS displacement velocity - {t.isoformat()}"


def parse_hub_ts(ts: str) -> datetime:
    """
    Parse 'YYYYMMDDTHHMMSSdmmm' to UTC datetime.
    Example: '20251217T144338d086' -> 2025-12-17 14:43:38.086000+00:00
    """
    ts = ts.strip()
    if len(ts) != 19 or ts[15] != "d":
        raise ValueError(f"Not a valid Hub timestamp: {ts!r}")

    base = ts[:15]  # 'YYYYMMDDTHHMMSS'
    ms_str = ts[16:]  # 'mmm'

    dt = datetime.strptime(base, "%Y%m%dT%H%M%S")
    ms = int(ms_str)
    return dt.replace(microsecond=ms * 1000, tzinfo=timezone.utc)


# --- STAC Item ID validation for LS-DF per PDF spec ---

# Ad-hoc / On-demand:
# <Service_UID>_<YYYYMMDDTHHMMSSmmm>_<NNNNNN>
# _ADHOC_RE = re.compile(
#    r"^(?P<svc>[A-Z0-9\-]+)_(?P<ts>\d{8}T\d{6}d\d{3})_(?P<ctr>\d{6})$"
# )
_ADHOC_RE = re.compile(r"^(?P<svc>[A-Z0-9\-]+)_(?P<ts>\d{8}T\d{6}d\d{3})$")
# _ADHOC_RE = re.compile(
#    r"^(?P<svc>[A-Z0-9\-]+)_(?P<ts>\d{8}T\d{6}\d{3})(?:_(?P<ctr>\d{6}))?$"
# )

# Systematic (day-level example):
# <Service_UID>_<YYYYMMDD>
_SYSTEMATIC_DAY_RE = re.compile(r"^(?P<svc>[A-Z0-9\-]+)_(?P<date>\d{8})$")


def _id_ok_for_ls_df(item_id: str) -> bool:
    """
    Allow both Systematic and Ad-hoc IDs for LS-DF collection:
      - Systematic: <Service_UID>_<YYYYMMDD>
      - Ad-hoc:     <Service_UID>_<YYYYMMDDTHHMMSSmmm>_<NNNNNN>
    And Service_UID must start with 'LS-DF' (e.g., 'LS-DF-SB-S1').
    """
    if not item_id:
        return False
    m = _ADHOC_RE.match(item_id)
    if m and m.group("svc").startswith("LS-DF"):
        return True
    m = _SYSTEMATIC_DAY_RE.match(item_id)
    if m and m.group("svc").startswith("LS-DF"):
        return True
    return False


def _item_uid_from_id(item_id: str) -> str:
    """
    Derive Item_UID (= <ServiceUID>_<YYYYMMDDTHHMMSSmmm>)
    from an LS-DF ad-hoc item id:
        <ServiceUID>_<YYYYMMDDTHHMMSSmmm>_<NNNNNN>
    If it doesn't match, just return the full id.
    """
    m = _ADHOC_RE.match(item_id)
    if m:
        return f"{m.group('svc')}_{m.group('ts')}"
    return item_id


def _is_cog(path: Path) -> bool:
    """Return True if the file is a Cloud Optimized GeoTIFF."""
    if gdal is None:
        return False
    ds = gdal.Open(str(path))
    if ds is None:
        return False
    meta = ds.GetMetadata("IMAGE_STRUCTURE")
    return meta.get("LAYOUT") == "COG"


def _is_subdataset_string(s: str) -> bool:
    """Detect GDAL subdataset strings like HDF5:\"file.h5\"://name or NETCDF:\"file.nc\"://var."""
    s = str(s)
    return (
        (('HDF5:"' in s or 'NETCDF:"' in s) and '"://' in s)
        or s.startswith("HDF5:")
        or s.startswith("NETCDF:")
    )


def _safe_name_from_sds(s: str) -> str:
    """Create a safe filename stem from a GDAL subdataset string."""
    # Prefer the part after ://
    if '"://' in s:
        stem = s.split('"://', 1)[-1]
    else:
        stem = s
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_")
    return stem or "asset"


def _translate_to_cog(src: str, dest_tif: Path) -> Path:
    """Write a Cloud-Optimized GeoTIFF (tiled + overviews)."""
    if gdal is None:
        raise RuntimeError("gdal is required to translate inputs to COG")
    dest_tif.parent.mkdir(parents=True, exist_ok=True)

    # sanity: ensure COG driver exists
    if gdal.GetDriverByName("COG") is None:
        raise RuntimeError("GDAL COG driver not available; upgrade GDAL (>= 3.1).")

    gdal.Translate(
        str(dest_tif),
        src,
        format="COG",
        creationOptions=[
            # tiling + compression
            "BLOCKSIZE=512",  # forces tiling
            "COMPRESS=LZW",
            "LEVEL=9",
            "BIGTIFF=IF_SAFER",
            # overviews
            "OVERVIEWS=AUTO",
            "SPARSE_OK=YES",
            # perf
            "NUM_THREADS=ALL_CPUS",
        ],
    )
    return dest_tif


def _expand_input_to_cogs(entry: Union[str, Path], asset_dir: Path) -> List[Path]:
    """
    Given an input entry (Path or GDAL SDS string), return one or more COG GeoTIFFs.
    - SDS string -> 1 COG
    - .tif/.tiff -> ensure COG (convert if needed)
    - .nc/.netcdf -> 1 COG
    - .h5/.hdf5 (raw file) -> expand ALL subdatasets to individual COGs
    - other existing files -> copy as-is (but these will fail later if not raster)
    """

    # If it's a plain string path (not a GDAL SDS string), treat it as a Path
    if isinstance(entry, str) and not _is_subdataset_string(entry):
        entry = Path(entry)

    out: List[Path] = []

    # SDS string case
    if isinstance(entry, str) and _is_subdataset_string(entry):
        safe = _safe_name_from_sds(entry)
        cog_path = asset_dir / f"{safe}.tif"
        _translate_to_cog(entry, cog_path)
        out.append(cog_path)
        return out

    # Path case
    if isinstance(entry, Path):
        if not entry.exists():
            raise FileNotFoundError(f"Input path does not exist: {entry}")

        suffix = entry.suffix.lower()
        # GeoTIFF: ensure COG
        if suffix in {".tif", ".tiff"}:
            dest = asset_dir / entry.with_suffix(".tif").name
            if not _is_cog(entry):
                tmp = dest if dest == entry else dest
                if dest == entry:
                    tmp = dest.with_suffix(".tmp.tif")
                _translate_to_cog(str(entry), tmp)
                if tmp != dest:
                    shutil.move(tmp, dest)
            elif dest != entry:
                shutil.copy2(entry, dest)
            out.append(dest)
            return out

        # NetCDF -> COG
        if suffix in {".nc", ".netcdf"}:
            dest = asset_dir / f"{entry.stem}.tif"
            _translate_to_cog(str(entry), dest)
            out.append(dest)
            return out

        # Raw HDF5 container: expand all subdatasets
        if suffix in {".h5", ".hdf5"}:
            if gdal is None:
                raise RuntimeError("gdal is required to read HDF5 subdatasets")
            ds = gdal.Open(f'HDF5:"{entry}"')
            if ds is None:
                raise RuntimeError(f"Could not open {entry} as HDF5")
            sds_list = ds.GetSubDatasets() or []
            if not sds_list:
                raise RuntimeError(f"No subdatasets found in {entry}")
            for i, (sds_name, _desc) in enumerate(sds_list, start=1):
                cog_path = asset_dir / f"{entry.stem}_sds{i}.tif"
                _translate_to_cog(sds_name, cog_path)
                out.append(cog_path)
            return out

        # Default: copy as-is (may fail later if not rasterio-readable)
        dest = asset_dir / entry.name if entry.parent != asset_dir else entry
        if dest != entry:
            shutil.copy2(entry, dest)
        out.append(dest)
        return out

    # Unknown type
    raise RuntimeError(f"Unsupported input: {entry}")


def _write_thumbnail_from_raster(
    src_path: Path, thumb_path: Path, size: int = 255
) -> Path:
    """Create a small JPEG quicklook from the first raster asset."""
    with rasterio.open(src_path) as src:
        data = src.read()  # shape: (bands, height, width)
        nodata = src.nodata

    # Ensure we have 3 bands (RGB) – replicate or pad if needed
    if data.shape[0] == 0:
        raise RuntimeError("No bands found to build thumbnail")
    if data.shape[0] == 1:
        data = np.repeat(data, 3, axis=0)
    elif data.shape[0] >= 3:
        data = data[:3]
    else:
        # e.g. 2 bands -> pad a third
        data = np.vstack([data, data[0:1]])

    # Normalize each band to 0–255 range
    out = []
    for band in data:
        b = band.astype("float32")
        if nodata is not None:
            mask = b == nodata
        else:
            mask = np.zeros_like(b, dtype=bool)

        valid = b[~mask]
        if valid.size == 0:
            scaled = np.zeros_like(b, dtype="uint8")
        else:
            vmin = np.percentile(valid, 2)
            vmax = np.percentile(valid, 98)
            if vmax <= vmin:
                vmax = vmin + 1.0
            scaled = ((np.clip(b, vmin, vmax) - vmin) / (vmax - vmin) * 255.0).astype(
                "uint8"
            )
            scaled[mask] = 0
        out.append(scaled)

    rgb = np.dstack(out)  # (H, W, 3)
    img = Image.fromarray(rgb)
    img = img.resize((size, size))
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(thumb_path, format="JPEG", quality=85, optimize=True)
    return thumb_path


def _apply_georef_via_vrt(src_tif: Path, ref_transform, ref_crs) -> Path:
    """
    Assign geotransform + CRS WITHOUT in-place COG edits:
    VRT (with GT+SRS) -> new COG -> replace original.
    """
    if gdal is None:
        raise RuntimeError("gdal is required to assign georeferencing")

    ds = gdal.Open(str(src_tif))
    if ds is None:
        raise RuntimeError(f"Unable to open {src_tif}")

    # Build VRT
    vrt_path = src_tif.with_suffix(".tmp.vrt")
    drv_vrt = gdal.GetDriverByName("VRT")
    vrt_ds = drv_vrt.CreateCopy(str(vrt_path), ds, strict=0)

    # Set GeoTransform (Affine: a,b,c; d,e,f) -> (c,a,b; f,d,e)
    vrt_ds.SetGeoTransform(
        (
            ref_transform.c,
            ref_transform.a,
            ref_transform.b,
            ref_transform.f,
            ref_transform.d,
            ref_transform.e,
        )
    )
    srs = osr.SpatialReference()
    srs.ImportFromWkt(ref_crs.to_wkt())
    vrt_ds.SetProjection(srs.ExportToWkt())
    vrt_ds = None
    ds = None

    # VRT -> fresh COG
    tmp_cog = src_tif.with_suffix(".tmp.cog.tif")
    gdal.Translate(
        str(tmp_cog),
        str(vrt_path),
        format="COG",
        creationOptions=[
            "COMPRESS=LZW",
            "LEVEL=9",
            "BLOCKSIZE=512",
            "OVERVIEWS=AUTO",
            "SPARSE_OK=YES",
            "BIGTIFF=IF_SAFER",
            "NUM_THREADS=ALL_CPUS",
        ],
    )
    os.remove(vrt_path)
    shutil.move(tmp_cog, src_tif)
    return src_tif


def create_stac_structure(
    data: Union["xr.Dataset", str, Path, Sequence[Union[str, Path]]],
    output_dir: Union[str, Path],
    collection_id: str,
    item_id: str,
    asset_name: str | None = None,
) -> Tuple[pystac.Collection, pystac.Item]:

    print(f"--> [create_stac_structure] Creating structure from item_id={item_id}")

    """Create a STAC collection and item for the provided data."""
    out_dir = Path(output_dir)

    print(f"--> [create_stac_structure] matching regex against item_id={item_id}")
    m = _ADHOC_RE.match(item_id)
    try:
        svc, ts, ctr = m.group("svc", "ts", "ctr")
        ictr = int(ctr)
        tstmp = parse_hub_ts(ts)
    except:
        svc, ts = m.group("svc", "ts")
        ictr = 1
        tstmp = parse_hub_ts(ts)

    collection_info = COLLECTIONS.get(collection_id)
    if collection_info is None:
        raise ValueError(f"Unknown collection id: {collection_id}")
    if item_id not in collection_info["items"]:
        if collection_id == "LS-DF":
            # Accept both systematic and ad-hoc IDs per the PDF
            if not _id_ok_for_ls_df(item_id):
                raise ValueError(
                    f"Item id '{item_id}' is not valid for collection '{collection_id}'"
                )
        else:
            # keep existing validation for other collections (or your original check)
            if not item_id:
                raise ValueError(
                    f"Item id '{item_id}' is not valid for collection '{collection_id}'"
                )

    # Prepare directory paths
    items_dir = out_dir / "items" / collection_id / item_id
    asset_dir = out_dir / "assets" / collection_id / item_id
    asset_dir.mkdir(parents=True, exist_ok=True)

    # Build entries list: keep SDS strings as str, convert plain file strings to Path
    raw_entries: List[Union[str, Path]] = []
    if isinstance(data, (str, Path)):
        raw_entries = [data]
    elif xr is not None and isinstance(data, xr.Dataset):
        if asset_name is None:
            asset_name = "data"
        asset_path = asset_dir / f"{asset_name}.nc"
        data.to_netcdf(asset_path)
        raw_entries = [asset_path]
    else:
        raw_entries = list(data)  # type: ignore[arg-type]

    entries: List[Union[str, Path]] = []
    for e in raw_entries:
        if isinstance(e, str) and not _is_subdataset_string(e):
            entries.append(Path(e))
        else:
            entries.append(e)

    asset_paths: List[Path] = []
    bbox: List[float] | None = None

    # Remember the first georeferenced raster as reference
    ref_transform = None
    ref_crs = None
    ref_size = None  # (width, height)

    # Expand each entry to one or more COGs, ensure georef (inherit if missing), reproject if needed, build bbox
    for entry in entries:
        expanded = _expand_input_to_cogs(entry, asset_dir)
        for dest in expanded:
            # --- Inspect read-only first ---
            with rasterio.open(dest, "r") as src:
                has_crs = bool(src.crs)
                has_transform = not src.transform.is_identity
                width, height = src.width, src.height
                current_crs = src.crs
                current_transform = src.transform

            # --- If missing georef, inherit from first good one (same size) via VRT -> fresh COG (no in-place edit) ---
            if not (has_crs and has_transform):
                if (
                    ref_transform is not None
                    and ref_crs is not None
                    and ref_size is not None
                ):
                    if (width, height) == ref_size:
                        _apply_georef_via_vrt(dest, ref_transform, ref_crs)
                        # refresh metadata after rewrite
                        with rasterio.open(dest) as src2:
                            has_crs = bool(src2.crs)
                            has_transform = not src2.transform.is_identity
                            current_crs = src2.crs
                            current_transform = src2.transform
                    else:
                        raise RuntimeError(
                            f"{dest} has no CRS/geotransform and does not match reference size "
                            f"{ref_size}; got {(width, height)}."
                        )

            # Enforce georeferencing present now
            if not (has_crs and has_transform):
                raise RuntimeError(
                    f"{dest} has no CRS/geotransform. Provide a georeferenced raster in the same call "
                    f"(first), or pre-assign georeferencing."
                )

            # Save as reference if first good one
            if ref_transform is None and has_crs and has_transform:
                ref_transform = current_transform
                ref_crs = current_crs
                ref_size = (width, height)

            target_epsg = 2100
            epsg_code = current_crs.to_epsg() if current_crs else None
            if epsg_code != target_epsg:
                if gdal is None:
                    raise RuntimeError(
                        "gdal is required to reproject data to EPSG:2100"
                    )

                # 1) Warp -> VRT (cheap, no tiling yet)
                tmp_vrt = dest.with_suffix(".tmp.vrt")
                gdal.Warp(
                    str(tmp_vrt),
                    str(dest),
                    format="VRT",
                    options=gdal.WarpOptions(
                        dstSRS=f"EPSG:{target_epsg}",
                        multithread=True,
                        resampleAlg="bilinear",
                    ),
                )

                # 2) VRT -> COG with tiling + overviews
                tmp_cog = dest.with_suffix(".tmp.tif")
                _translate_to_cog(str(tmp_vrt), tmp_cog)
                os.remove(tmp_vrt)
                shutil.move(tmp_cog, dest)

                # refresh metadata after rewrite
                with rasterio.open(dest) as src2:
                    current_crs = src2.crs
                    current_transform = src2.transform
                    width, height = src2.width, src2.height
                    has_crs = bool(src2.crs)
                    has_transform = not src2.transform.is_identity

                # If we just reprojected and reference wasn't set yet, refresh reference from reprojected file
                if ref_size is None:
                    with rasterio.open(dest) as src2:
                        ref_transform = src2.transform
                        ref_crs = src2.crs
                        ref_size = (src2.width, src2.height)

            asset_paths.append(dest)

            with rasterio.open(dest) as src:
                # Transform asset bounds (likely in EPSG:2100) to EPSG:4326 for STAC
                left, bottom, right, top = transform_bounds(
                    src.crs,
                    "EPSG:4326",
                    src.bounds.left,
                    src.bounds.bottom,
                    src.bounds.right,
                    src.bounds.top,
                    densify_pts=21,
                )

            wgs84_bounds = (left, bottom, right, top)
            if bbox is None:
                bbox = [
                    wgs84_bounds[0],
                    wgs84_bounds[1],
                    wgs84_bounds[2],
                    wgs84_bounds[3],
                ]
            else:
                bbox = [
                    min(bbox[0], wgs84_bounds[0]),
                    min(bbox[1], wgs84_bounds[1]),
                    max(bbox[2], wgs84_bounds[2]),
                    max(bbox[3], wgs84_bounds[3]),
                ]

    if bbox is None:
        raise ValueError("No input data provided")

    geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [bbox[0], bbox[1]],
                [bbox[0], bbox[3]],
                [bbox[2], bbox[3]],
                [bbox[2], bbox[1]],
                [bbox[0], bbox[1]],
            ]
        ],
    }

    product_label = "SBAS (Distributed Scatterers) displacement maps for Greece"
    area_name = "Greece"
    title = f"{product_label} - {area_name} - {tstmp.strftime('%Y-%m-%dT%H:%M:%SZ')}"

    item = pystac.Item(
        id=item_id,
        geometry=geometry,
        bbox=bbox,
        datetime=tstmp,
        properties={
            "processing:datetime": tstmp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "processing:facility": PROCESSING_FACILITY,
            "processing:version": PROCESSING_VERSION,
            "processing:software": {
                PROCESSING_SOFTWARE_NAME: PROCESSING_VERSION,
                "repo": PROCESSING_SOFTWARE_REPO,
            },
            "processing:level": PROCESSING_LEVEL,
            "title": title,
        },
    )

    # proj:centroid (used by CentroidValidator)
    item.properties["proj:centroid"] = {
        "lat": (bbox[1] + bbox[3]) / 2.0,
        "lon": (bbox[0] + bbox[2]) / 2.0,
    }

    # item title -> DOES NOT WORK
    item.title = GEO_VELOCITY_TITLE(tstmp)

    # Projection info from the first asset
    if gdal is None:
        raise RuntimeError("gdal is required to read projection information")
    ds0 = gdal.Open(str(asset_paths[0]))
    if ds0 is not None:
        wkt = ds0.GetProjection()
        srs = osr.SpatialReference()
        if wkt:
            srs.ImportFromWkt(wkt)
            epsg = srs.GetAttrValue("AUTHORITY", 1)
            for ext in (PROJ_EXT, RASTER_EXT, PROCESSING_EXT):
                if ext not in item.stac_extensions:
                    item.stac_extensions.append(ext)
            item.properties["proj:wkt2"] = srs.ExportToWkt()
            if epsg:
                try:
                    item.properties["proj:epsg"] = int(epsg)
                except Exception:
                    item.properties["proj:epsg"] = epsg

    # --- INSERT THUMBNAIL CREATION HERE ---
    first_raster = next(
        (p for p in asset_paths if p.suffix.lower() in {".tif", ".tiff"}), None
    )
    if first_raster is not None:
        thumb_path = out_dir / "assets" / collection_id / item_id / "thumbnail.jpg"
        _write_thumbnail_from_raster(first_raster, thumb_path, size=255)

        rel_thumb = Path(os.path.relpath(thumb_path, start=out_dir)).as_posix()
        item.add_asset(
            "thumbnail",
            pystac.Asset(
                href=rel_thumb,
                media_type=pystac.MediaType.JPEG,
                roles=["thumbnail"],
            ),
        )
        # Optional preview link
        item.add_link(
            pystac.Link(
                rel="preview",
                target=rel_thumb,
                media_type=pystac.MediaType.JPEG,
                title="Thumbnail preview",
            )
        )

    # Add assets
    for path in asset_paths:
        rel_href = Path(os.path.relpath(path, start=out_dir)).as_posix()
        suffix = path.suffix.lower()
        media_type = None
        if suffix in {".tif", ".tiff"}:
            media_type = pystac.MediaType.GEOTIFF
        elif suffix in {".nc", ".netcdf"}:
            media_type = "application/x-netcdf"

        key = asset_name if asset_name and len(asset_paths) == 1 else path.stem

        # Base object asset
        asset = pystac.Asset(href=rel_href, media_type=media_type, roles=["data"])

        # 1) Asset title / name (you already added something like this;
        # processing_dt_str = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        # product_label = COLLECTIONS["LS-DF"]["items"].get("LS-DF-SB-S1", "LS-DF-SB-S1")
        # area_name = "Greece"
        # asset_title = f"{product_label} – {area_name} – {processing_dt_str}"
        asset.extra_fields["title"] = GEO_VELOCITY_TITLE(tstmp)
        asset.extra_fields["description"] = GEO_VELOCITY_TITLE(tstmp)
        asset.extra_fields["name"] = GEO_VELOCITY_TITLE(tstmp)

        # 2) product:id in the new format:
        #    <Item_UID>_(RAS-CLA|RAS-CNT|VEC-PNT|VEC-LIN|VEC-POL|NON-GEO)_<NNNN>
        # with Item_UID = <ServiceUID>_<YYYYMMDDTHHMMSSdmmm>
        item_uid = _item_uid_from_id(item.id)
        if suffix in {".tif", ".tiff"} and key != "thumbnail":
            asset_code = "RAS-CNT"  # continuous raster
        else:
            asset_code = "NON-GEO"  # safe fallback for non-rasters
        product_id = f"{svc}_{ts}_{asset_code}_{ictr:04d}"
        asset.extra_fields["product:id"] = product_id

        if suffix in {".tif", ".tiff"} and key != "thumbnail":
            with rasterio.open(path) as src:
                transform = src.transform
                width = src.width
                height = src.height
                bounds = src.bounds
                dtype = src.dtypes[0]
                xres = abs(src.transform.a)
                yres = abs(src.transform.e)
                spatial_res = float((xres + yres) / 2.0)

                # proj:* at asset level
                asset.extra_fields["proj:shape"] = [height, width]
                asset.extra_fields["proj:bbox"] = [
                    bounds.left,
                    bounds.bottom,
                    bounds.right,
                    bounds.top,
                ]
                asset.extra_fields["proj:transform"] = [
                    transform.a,
                    transform.b,
                    transform.c,
                    transform.d,
                    transform.e,
                    transform.f,
                ]
                asset_bands = [
                    {
                        "data_type": dtype,
                        "sampling": "area",  # per spec
                        "spatial_resolution": spatial_res,
                    }
                ]
                asset.extra_fields["raster:bands"] = asset_bands
                # Everything should be in EPSG:2100 by this point
                asset.extra_fields["proj:code"] = "EPSG:2100"

        item.add_asset(key, asset)

    collection = pystac.Collection(
        id=collection_id,
        description=collection_info["description"],
        extent=pystac.Extent(
            spatial=pystac.SpatialExtent([bbox]),
            temporal=pystac.TemporalExtent([[None, None]]),
        ),
    )

    # Ensure valid relative STAC links
    collection_dir = out_dir / "items" / collection_id
    collection_path = collection_dir / "collection.json"
    item_path = items_dir / f"{item_id}.json"

    collection.set_self_href(str(collection_path))
    item.set_self_href(str(item_path))
    collection.add_item(item)

    items_dir.mkdir(parents=True, exist_ok=True)

    collection_dict = collection.to_dict()
    for link in collection_dict.get("links", []):
        link["href"] = Path(
            os.path.relpath(link["href"], start=collection_dir)
        ).as_posix()

    item_dict = item.to_dict()
    # Make absolutely sure the title is there
    if not item_dict.get("title"):
        item_dict["title"] = title
    for link in item_dict.get("links", []):
        link["href"] = Path(os.path.relpath(link["href"], start=items_dir)).as_posix()

    collection_path.write_text(json.dumps(collection_dict, indent=2))
    item_path.write_text(json.dumps(item_dict, indent=2))

    return collection, item
