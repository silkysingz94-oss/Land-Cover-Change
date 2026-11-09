
import os
import io
import json
import time
import subprocess
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import ee
import pandas as pd

from google.cloud import storage
from google.oauth2 import service_account


# ============================================================
# GBoS GEOAI | GAMBIA LAND-COVER CHANGE INTELLIGENCE
# Produced by Ansu Singhateh
# GIS Analyst | GIS / Cartography Unit | Gambia Bureau of Statistics
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TILES_DIR = ROOT / "tiles"

DATA_DIR.mkdir(exist_ok=True)
TILES_DIR.mkdir(exist_ok=True)

PROJECT_ID = os.environ["EE_PROJECT_ID"]
SERVICE_ACCOUNT_JSON = os.environ["EE_SERVICE_ACCOUNT_JSON"]
BUCKET_NAME = os.environ["GCS_BUCKET"].strip()
EA_ASSET = os.environ["GEE_EA_ASSET"].strip()

START_2017 = "2017-01-01"
END_2017 = "2018-01-01"

TODAY = date.today()
START_2026 = "2026-01-01"
END_2026 = TODAY.isoformat()

SCALE = 20
MAX_PIXELS = 1e13
POLL_SECONDS = 30
TASK_TIMEOUT_SECONDS = 5 * 60 * 60

YEARS = {
    "2017": (START_2017, END_2017),
    "2026": (START_2026, END_2026),
}

CLASS_NAMES = {
    0: "Water",
    1: "Trees",
    2: "Grass",
    3: "Flooded vegetation",
    4: "Crops",
    5: "Shrub and scrub",
    6: "Built area",
    7: "Bare ground",
    8: "Snow and ice",
}

CLASS_COLORS = {
    0: "419BDF",
    1: "397D49",
    2: "88B053",
    3: "7A87C6",
    4: "E49635",
    5: "DFC35A",
    6: "C4281B",
    7: "A59B8F",
    8: "B39FE1",
}

PROPERTY_FIELDS = [
    "feacode",
    "eaname",
    "wardname",
    "distname",
    "lganame",
    "RCO",
]


# ============================================================
# AUTHENTICATION
# ============================================================

print("Authenticating Earth Engine...")

service_info = json.loads(SERVICE_ACCOUNT_JSON)

credentials = service_account.Credentials.from_service_account_info(
    service_info,
    scopes=[
        "https://www.googleapis.com/auth/cloud-platform",
        "https://www.googleapis.com/auth/earthengine",
    ],
)

ee.Initialize(
    credentials=credentials,
    project=PROJECT_ID,
)

gcs_client = storage.Client(
    project=PROJECT_ID,
    credentials=credentials,
)

bucket = gcs_client.bucket(BUCKET_NAME)

if not bucket.exists():
    raise RuntimeError(
        f"Google Cloud Storage bucket does not exist: {BUCKET_NAME}"
    )


# ============================================================
# EARTH ENGINE INPUTS
# ============================================================

print("Loading Gambia enumeration areas...")

eas = ee.FeatureCollection(EA_ASSET)

ea_count = eas.size().getInfo()

print(f"Enumeration areas: {ea_count}")

if ea_count == 0:
    raise RuntimeError("The EA asset contains no features.")

# Keep only known properties, provided by the GBoS EA asset.
eas = eas.select(PROPERTY_FIELDS)

country_geometry = eas.geometry().bounds()


# ============================================================
# DYNAMIC WORLD CLASSIFICATION
# ============================================================

def annual_landcover(start_date, end_date):
    """
    Annual modal Dynamic World classification.

    Dynamic World label classes:
    0 Water
    1 Trees
    2 Grass
    3 Flooded vegetation
    4 Crops
    5 Shrub and scrub
    6 Built area
    7 Bare ground
    8 Snow and ice
    """

    collection = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(country_geometry)
        .filterDate(start_date, end_date)
        .select("label")
    )

    image_count = collection.size().getInfo()

    print(
        f"Dynamic World observations from "
        f"{start_date} to {end_date}: {image_count}"
    )

    if image_count == 0:
        raise RuntimeError(
            f"No Dynamic World images found for {start_date} to {end_date}"
        )

    classified = (
        collection
        .reduce(ee.Reducer.mode())
        .rename("landcover")
        .toUint8()
        .clip(country_geometry)
    )

    return classified, image_count


# ============================================================
# AREA STATISTICS
# ============================================================

def create_area_image(classified):
    """
    Creates nine area bands.

    Every pixel is converted to hectares and assigned to
    its corresponding Dynamic World class.
    """

    pixel_area_ha = ee.Image.pixelArea().divide(10000)

    bands = []

    for class_id, class_name in CLASS_NAMES.items():

        band_name = (
            class_name.lower()
            .replace(" ", "_")
            .replace("-", "_")
        ) + "_ha"

        area_band = (
            pixel_area_ha
            .updateMask(classified.eq(class_id))
            .rename(band_name)
        )

        bands.append(area_band)

    return ee.Image.cat(bands)


def export_table(classified, year):
    """
    One reduceRegions operation per year, calculating
    all nine class areas for every enumeration area.
    """

    print(f"Preparing EA statistics for {year}...")

    area_image = create_area_image(classified)

    result = area_image.reduceRegions(
        collection=eas,
        reducer=ee.Reducer.sum(),
        scale=SCALE,
        tileScale=8,
    )

    task = ee.batch.Export.table.toCloudStorage(
        collection=result,
        description=f"Gambia_Landcover_EA_{year}",
        bucket=BUCKET_NAME,
        fileNamePrefix=f"exports/landcover_{year}",
        fileFormat="CSV",
        selectors=PROPERTY_FIELDS + [
            "water_ha",
            "trees_ha",
            "grass_ha",
            "flooded_vegetation_ha",
            "crops_ha",
            "shrub_and_scrub_ha",
            "built_area_ha",
            "bare_ground_ha",
            "snow_and_ice_ha",
        ],
    )

    task.start()
    return task


# ============================================================
# IMAGE EXPORT
# ============================================================

def export_image(classified, year):
    """
    Export a visual RGB image to Cloud Storage.
    """

    palette = [
        CLASS_COLORS[i]
        for i in range(9)
    ]

    visual = classified.visualize(
        min=0,
        max=8,
        palette=palette,
    )

    task = ee.batch.Export.image.toCloudStorage(
        image=visual,
        description=f"Gambia_Landcover_Map_{year}",
        bucket=BUCKET_NAME,
        fileNamePrefix=f"exports/landcover_map_{year}",
        region=country_geometry,
        scale=SCALE,
        maxPixels=MAX_PIXELS,
        fileFormat="GeoTIFF",
        formatOptions={
            "cloudOptimized": True,
        },
    )

    task.start()
    return task


def export_change_image(classified_2017, classified_2026):
    """
    Export a simple change visualisation.

    Green = unchanged.
    Red = changed class.
    """

    changed = classified_2017.neq(classified_2026)

    change_visual = (
        ee.Image.constant(1)
        .where(changed, 0)
        .clip(country_geometry)
        .visualize(
            min=0,
            max=1,
            palette=["D73027", "1A9850"],
        )
    )

    task = ee.batch.Export.image.toCloudStorage(
        image=change_visual,
        description="Gambia_Landcover_Change_2017_2026",
        bucket=BUCKET_NAME,
        fileNamePrefix="exports/landcover_change_2017_2026",
        region=country_geometry,
        scale=SCALE,
        maxPixels=MAX_PIXELS,
        fileFormat="GeoTIFF",
        formatOptions={
            "cloudOptimized": True,
        },
    )

    task.start()
    return task


# ============================================================
# TASK MONITORING
# ============================================================

def wait_for_tasks(tasks):
    started = time.time()

    while True:

        statuses = [
            task.status()
            for task in tasks
        ]

        states = [
            status.get("state", "UNKNOWN")
            for status in statuses
        ]

        print("Earth Engine task states:", states)

        failed = [
            status
            for status in statuses
            if status.get("state") in ("FAILED", "CANCELLED")
        ]

        if failed:
            details = json.dumps(failed, indent=2)
            raise RuntimeError(
                "Earth Engine export failed:\n" + details
            )

        if all(state == "COMPLETED" for state in states):
            print("All Earth Engine exports completed.")
            return

        if time.time() - started > TASK_TIMEOUT_SECONDS:
            raise TimeoutError(
                "Earth Engine export tasks exceeded the timeout."
            )

        time.sleep(POLL_SECONDS)


# ============================================================
# DOWNLOAD GCS EXPORTS
# ============================================================

def download_prefix(prefix, destination):
    """
    Download all files matching a GCS prefix.
    """

    destination.mkdir(parents=True, exist_ok=True)

    blobs = list(
        gcs_client.list_blobs(
            BUCKET_NAME,
            prefix=prefix,
        )
    )

    if not blobs:
        raise RuntimeError(
            f"No exported objects found under gs://{BUCKET_NAME}/{prefix}"
        )

    downloaded = []

    for blob in blobs:

        if blob.name.endswith("/"):
            continue

        filename = Path(blob.name).name
        local_path = destination / filename

        print(f"Downloading {blob.name}")

        blob.download_to_filename(str(local_path))
        downloaded.append(local_path)

    return downloaded


# ============================================================
# BUILD CSV AND JSON STATISTICS
# ============================================================

def build_statistics(csv_files, year, image_count):
    frames = []

    for csv_file in csv_files:
        if csv_file.suffix.lower() == ".csv":
            frames.append(pd.read_csv(csv_file))

    if not frames:
        raise RuntimeError(
            f"No CSV export was downloaded for {year}."
        )

    df = pd.concat(frames, ignore_index=True)

    required = ["feacode"]

    for field in required:
        if field not in df.columns:
            raise RuntimeError(
                f"Required field '{field}' missing in {year} export. "
                f"Found: {list(df.columns)}"
            )

    df["feacode"] = df["feacode"].astype(str)

    class_fields = [
        "water_ha",
        "trees_ha",
        "grass_ha",
        "flooded_vegetation_ha",
        "crops_ha",
        "shrub_and_scrub_ha",
        "built_area_ha",
        "bare_ground_ha",
        "snow_and_ice_ha",
    ]

    for field in class_fields:
        if field not in df.columns:
            df[field] = 0

        df[field] = pd.to_numeric(
            df[field],
            errors="coerce",
        ).fillna(0)

    df.to_csv(
        DATA_DIR / f"landcover_{year}.csv",
        index=False,
    )

    records = {}

    for _, row in df.iterrows():

        key = str(row["feacode"])

        records[key] = {
            "feacode": key,
            "eaname": str(row.get("eaname", "")),
            "wardname": str(row.get("wardname", "")),
            "distname": str(row.get("distname", "")),
            "lganame": str(row.get("lganame", "")),
            "RCO": str(row.get("RCO", "")),
            "areas": {
                field: round(float(row[field]), 4)
                for field in class_fields
            },
        }

    totals = {
        field: round(float(df[field].sum()), 4)
        for field in class_fields
    }

    return {
        "year": year,
        "image_count": image_count,
        "features": records,
        "totals": totals,
    }


# ============================================================
# BUILD CHANGE STATISTICS
# ============================================================

def build_change_statistics(stats_2017, stats_2026):

    change = {}

    for key, current in stats_2026["features"].items():

        previous = stats_2017["features"].get(key)

        if previous is None:
            continue

        class_changes = {}

        for field, current_area in current["areas"].items():

            previous_area = previous["areas"].get(field, 0)

            class_changes[field] = round(
                current_area - previous_area,
                4,
            )

        change[key] = {
            "feacode": key,
            "eaname": current["eaname"],
            "wardname": current["wardname"],
            "distname": current["distname"],
            "lganame": current["lganame"],
            "RCO": current["RCO"],
            "change": class_changes,
            "built_area_change_ha": class_changes["built_area_ha"],
        }

    return change


# ============================================================
# MAP TILE GENERATION
# ============================================================

def create_tiles(tiff_files, layer_name):
    """
    Convert exported RGB GeoTIFFs into XYZ web map tiles.
    """

    layer_dir = TILES_DIR / layer_name

    if layer_dir.exists():
        import shutil
        shutil.rmtree(layer_dir)

    layer_dir.mkdir(parents=True, exist_ok=True)

    if not tiff_files:
        raise RuntimeError(
            f"No GeoTIFF found for {layer_name}"
        )

    # Earth Engine may create multiple GeoTIFF shards.
    # Merge them into one mosaic before tile generation.
    mosaic = DATA_DIR / f"{layer_name}_mosaic.vrt"

    vrt_command = [
        "gdalbuildvrt",
        str(mosaic),
    ] + [str(path) for path in tiff_files]

    subprocess.run(vrt_command, check=True)

    subprocess.run(
        [
            "gdal2tiles.py",
            "--xyz",
            "--processes=2",
            "-z",
            "5-11",
            str(mosaic),
            str(layer_dir),
        ],
        check=True,
    )

    print(f"Tiles created: {layer_dir}")


# ============================================================
# MAIN PIPELINE
# ============================================================

def main():

    print("=" * 65)
    print("GBoS GEOAI | GAMBIA LAND-COVER CHANGE INTELLIGENCE")
    print("=" * 65)

    if END_2026 <= START_2026:
        raise RuntimeError(
            "2026 observation window is empty. Run after 1 January 2026."
        )

    classifications = {}
    image_counts = {}
    tasks = []

    # Build annual classifications.
    for year, (start_date, end_date) in YEARS.items():

        print(f"Building classification for {year}...")

        classified, count = annual_landcover(
            start_date,
            end_date,
        )

        classifications[year] = classified
        image_counts[year] = count

        tasks.append(
            export_table(classified, year)
        )

        tasks.append(
            export_image(classified, year)
        )

    # Build change map.
    tasks.append(
        export_change_image(
            classifications["2017"],
            classifications["2026"],
        )
    )

    # Wait for all Earth Engine jobs.
    wait_for_tasks(tasks)

    # Download and process tables.
    stats_by_year = {}

    for year in YEARS:

        csv_files = download_prefix(
            f"exports/landcover_{year}",
            DATA_DIR / f"csv_{year}",
        )

        stats_by_year[year] = build_statistics(
            csv_files,
            year,
            image_counts[year],
        )

        # Preserve an easily accessible CSV at data root.
        source = DATA_DIR / f"landcover_{year}.csv"
        print(f"Statistics saved: {source}")

    # Download annual map exports.
    map_2017 = download_prefix(
        "exports/landcover_map_2017",
        DATA_DIR / "map_2017",
    )

    map_2026 = download_prefix(
        "exports/landcover_map_2026",
        DATA_DIR / "map_2026",
    )

    map_change = download_prefix(
        "exports/landcover_change_2017_2026",
        DATA_DIR / "map_change",
    )

    # Generate tiles.
    create_tiles(
        [p for p in map_2017 if p.suffix.lower() in (".tif", ".tiff")],
        "landcover_2017",
    )

    create_tiles(
        [p for p in map_2026 if p.suffix.lower() in (".tif", ".tiff")],
        "landcover_2026",
    )

    create_tiles(
        [p for p in map_change if p.suffix.lower() in (".tif", ".tiff")],
        "landcover_change",
    )

    # Build comparison and change statistics.
    change = build_change_statistics(
        stats_by_year["2017"],
        stats_by_year["2026"],
    )

    change_df = pd.DataFrame(list(change.values()))
    change_df.to_csv(
        DATA_DIR / "change_statistics.csv",
        index=False,
    )

    class_totals = {}

    for class_id, class_name in CLASS_NAMES.items():

        field = (
            class_name.lower()
            .replace(" ", "_")
            .replace("-", "_")
        ) + "_ha"

        old_value = stats_by_year["2017"]["totals"].get(field, 0)
        new_value = stats_by_year["2026"]["totals"].get(field, 0)

        class_totals[str(class_id)] = {
            "name": class_name,
            "color": "#" + CLASS_COLORS[class_id],
            "2017_ha": old_value,
            "2026_ha": new_value,
            "change_ha": round(new_value - old_value, 4),
        }

    output = {
        "metadata": {
            "title": "Gambia Persistent Land-Cover Change Intelligence",
            "producer": "Gambia Bureau of Statistics",
            "unit": "GIS / Cartography Unit",
            "method": "Dynamic World annual modal land-cover classification",
            "source": "Google Earth Engine - GOOGLE/DYNAMICWORLD/V1",
            "baseline_period": {
                "start": START_2017,
                "end": END_2017,
            },
            "current_period": {
                "start": START_2026,
                "end": END_2026,
            },
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "scale_m": SCALE,
            "ea_count": ea_count,
            "observations": image_counts,
            "disclaimer": (
                "Satellite-derived estimates. Results are not "
                "field-validated and should not be interpreted as "
                "official land-cover statistics."
            ),
        },
        "classes": class_totals,
        "years": {
            "2017": stats_by_year["2017"],
            "2026": stats_by_year["2026"],
        },
        "change": change,
    }

    stats_path = DATA_DIR / "stats.json"

    with open(stats_path, "w", encoding="utf-8") as file:
        json.dump(
            output,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print("=" * 65)
    print("LAND-COVER PIPELINE COMPLETED")
    print(f"EA count: {ea_count}")
    print(f"Statistics: {stats_path}")
    print("=" * 65)


if __name__ == "__main__":
    main()
