
import os
import json
import csv
import time
import shutil
import tempfile
import subprocess
from pathlib import Path
from collections import defaultdict

import ee
from google.cloud import storage


# ============================================================
# GBoS GEOAI
# GAMBIA PERSISTENT LAND-COVER CHANGE INTELLIGENCE
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "data"
TILES_DIR = ROOT / "tiles"

DATA_DIR.mkdir(exist_ok=True)
TILES_DIR.mkdir(exist_ok=True)

PROJECT = os.environ["EE_PROJECT_ID"]
BUCKET_NAME = os.environ["GCS_BUCKET"]
SERVICE_JSON = os.environ["EE_SERVICE_ACCOUNT_JSON"]

EA_ASSET = os.environ.get(
    "GEE_EA_ASSET",
    "projects/ee-aishaansu80/assets/GambiaEA_Final1"
)

CLASS_NAMES = {
    0: "Water",
    1: "Trees",
    2: "Grass",
    3: "Flooded vegetation",
    4: "Crops",
    5: "Shrub and scrub",
    6: "Built area",
    7: "Bare ground",
    8: "Snow and ice"
}

PALETTE = [
    "419BDF",
    "397D49",
    "88B053",
    "7A87C6",
    "E49635",
    "DFC35A",
    "C4281B",
    "A59B8F",
    "B39FE1"
]

CHANGE_PALETTE = [
    "2E8B57",
    "D73027"
]


# ============================================================
# AUTHENTICATION
# ============================================================

def initialize_ee():

    key = json.loads(SERVICE_JSON)

    temporary_key = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False
    )

    json.dump(key, temporary_key)
    temporary_key.close()

    credentials = ee.ServiceAccountCredentials(
        key["client_email"],
        temporary_key.name
    )

    ee.Initialize(
        credentials=credentials,
        project=PROJECT
    )

    return temporary_key.name


# ============================================================
# DYNAMIC WORLD PROCESSING
# ============================================================

def get_landcover(year, end_date, country):

    start_date = f"{year}-01-01"

    collection = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterDate(start_date, end_date)
        .filterBounds(country)
        .select("label")
    )

    observation_count = collection.size()

    modal_image = (
        collection
        .reduce(ee.Reducer.mode())
        .rename("label")
        .toByte()
        .clip(country)
    )

    return modal_image, observation_count


# ============================================================
# EA LAND-COVER AREA STATISTICS
# ============================================================

def calculate_ea_statistics(image, eas, year):

    output = ee.FeatureCollection([])

    for class_id, class_name in CLASS_NAMES.items():

        area_image = (
            ee.Image.pixelArea()
            .divide(10000)
            .updateMask(image.eq(class_id))
            .rename("area_ha")
        )

        reduced = area_image.reduceRegions(
            collection=eas,
            reducer=ee.Reducer.sum(),
            scale=10,
            tileScale=4
        )

        def add_attributes(feature):

            area = ee.Number(
                ee.Algorithms.If(
                    feature.get("sum"),
                    feature.get("sum"),
                    0
                )
            )

            return feature.set({
                "year": year,
                "class_id": class_id,
                "class_name": class_name,
                "area_ha": area
            })

        output = output.merge(
            reduced.map(add_attributes)
        )

    return output


# ============================================================
# EARTH ENGINE EXPORTS
# ============================================================

def export_image(image, description, prefix, region):

    task = ee.batch.Export.image.toCloudStorage(
        image=image,
        description=description,
        bucket=BUCKET_NAME,
        fileNamePrefix=prefix,
        region=region,
        scale=10,
        crs="EPSG:4326",
        maxPixels=1e13,
        fileFormat="GeoTIFF",
        formatOptions={
            "cloudOptimized": True
        }
    )

    task.start()

    return task


def export_table(collection):

    task = ee.batch.Export.table.toCloudStorage(
        collection=collection,
        description="GBoS_EA_Landcover_Statistics",
        bucket=BUCKET_NAME,
        fileNamePrefix="exports/ea_statistics",
        fileFormat="CSV"
    )

    task.start()

    return task


def wait_for_tasks(tasks):

    while tasks:

        remaining = []

        for task in tasks:

            status = task.status()
            state = status.get("state")

            print(
                status.get("description"),
                state
            )

            if state == "FAILED":
                raise RuntimeError(
                    status.get("error_message")
                )

            if state == "CANCELLED":
                raise RuntimeError(
                    "Earth Engine export was cancelled."
                )

            if state != "COMPLETED":
                remaining.append(task)

        tasks = remaining

        if tasks:
            time.sleep(30)


# ============================================================
# DOWNLOAD EARTH ENGINE OUTPUTS FROM CLOUD STORAGE
# ============================================================

def download_prefix(prefix):

    client = storage.Client(
        project=PROJECT
    )

    bucket = client.bucket(BUCKET_NAME)

    blobs = list(
        client.list_blobs(
            bucket,
            prefix=prefix
        )
    )

    if not blobs:
        raise RuntimeError(
            f"No files found for {prefix}"
        )

    downloaded = []

    for blob in blobs:

        if blob.name.endswith("/"):
            continue

        filename = Path(blob.name).name

        local_path = DATA_DIR / filename

        blob.download_to_filename(local_path)

        downloaded.append(local_path)

    return downloaded


# ============================================================
# CREATE PUBLIC XYZ MAP TILES
# ============================================================

def create_tiles(tif_path, layer_name):

    output = TILES_DIR / layer_name

    if output.exists():
        shutil.rmtree(output)

    output.mkdir(
        parents=True,
        exist_ok=True
    )

    command = [
        "gdal2tiles.py",
        "--xyz",
        "--zoom=5-12",
        "--processes=2",
        str(tif_path),
        str(output)
    ]

    subprocess.run(
        command,
        check=True
    )


# ============================================================
# READ EA STATISTICS
# ============================================================

def read_csv_files(files):

    rows = []

    for file in files:

        if file.suffix.lower() != ".csv":
            continue

        with file.open(
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as f:

            reader = csv.DictReader(f)

            for row in reader:

                try:

                    area = float(
                        row.get("area_ha") or
                        row.get("sum") or 0
                    )

                    year = int(
                        float(row.get("year"))
                    )

                    class_id = int(
                        float(row.get("class_id"))
                    )

                except (ValueError, TypeError):
                    continue

                rows.append({
                    "ea_code": str(
                        row.get("feacode") or
                        row.get("FEACODE") or
                        row.get("EA_code") or ""
                    ),
                    "ea_name": row.get("eaname", ""),
                    "ward": row.get("wardname", ""),
                    "district": row.get("distname", ""),
                    "lga": row.get("lganame", ""),
                    "region": row.get("RCO", ""),
                    "year": year,
                    "class_id": class_id,
                    "class_name": row.get(
                        "class_name",
                        CLASS_NAMES.get(class_id, "Unknown")
                    ),
                    "area_ha": area
                })

    return rows


# ============================================================
# BUILD PUBLIC JSON
# ============================================================

def build_statistics(rows):

    records = {}

    national = defaultdict(
        lambda: defaultdict(float)
    )

    for row in rows:

        code = row["ea_code"]

        if not code:
            continue

        year = row["year"]

        key = f"{code}_{year}"

        if key not in records:

            records[key] = {
                "ea_code": code,
                "ea_name": row["ea_name"],
                "ward": row["ward"],
                "district": row["district"],
                "lga": row["lga"],
                "region": row["region"],
                "year": year,
                "classes": {}
            }

        class_id = str(row["class_id"])

        records[key]["classes"][class_id] = {
            "name": row["class_name"],
            "area_ha": row["area_ha"]
        }

        national[str(year)][class_id] += row["area_ha"]

    national_output = {}

    for year, classes in national.items():

        national_output[year] = {}

        for class_id, area in classes.items():

            national_output[year][class_id] = {
                "name": CLASS_NAMES[int(class_id)],
                "area_ha": area
            }

    output = {

        "title": "Gambia Persistent Land-Cover Change Intelligence",

        "generated_utc": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime()
        ),

        "source": "Google Earth Engine Dynamic World V1",

        "resolution_m": 10,

        "years": [2017, 2026],

        "classes": {
            str(k): v
            for k, v in CLASS_NAMES.items()
        },

        "national": national_output,

        "ea_records": list(records.values()),

        "map_layers": {
            "2017": "./tiles/landcover_2017/{z}/{x}/{y}.png",
            "2026": "./tiles/landcover_2026/{z}/{x}/{y}.png",
            "change": "./tiles/change_2017_2026/{z}/{x}/{y}.png"
        },

        "methodology": {
            "2017": "Modal Dynamic World label from calendar year 2017.",
            "2026": "Modal Dynamic World label from 1 January 2026 through the pipeline run date.",
            "change": "Pixels where the modal class differs between the two periods.",
            "area": "Pixel area summed within each EA, expressed in hectares."
        }
    }

    path = DATA_DIR / "stats.json"

    path.write_text(
        json.dumps(output, separators=(",", ":")),
        encoding="utf-8"
    )


# ============================================================
# MAIN AUTOMATED WORKFLOW
# ============================================================

def main():

    key_path = initialize_ee()

    try:

        print("Loading EA boundaries from Earth Engine asset...")

        eas = ee.FeatureCollection(EA_ASSET)

        country = eas.geometry().dissolve(100)

        today = time.strftime(
            "%Y-%m-%d",
            time.gmtime()
        )

        print("Processing 2017 land cover...")

        image_2017, count_2017 = get_landcover(
            2017,
            "2018-01-01",
            country
        )

        print("Processing 2026 land cover...")

        image_2026, count_2026 = get_landcover(
            2026,
            today,
            country
        )

        counts = {
            "2017": count_2017.getInfo(),
            "2026": count_2026.getInfo()
        }

        print("Observation counts:", counts)

        if counts["2017"] == 0 or counts["2026"] == 0:
            raise RuntimeError(
                "No Dynamic World observations found for one of the periods."
            )

        print("Calculating EA statistics...")

        statistics = (
            calculate_ea_statistics(
                image_2017,
                eas,
                2017
            )
            .merge(
                calculate_ea_statistics(
                    image_2026,
                    eas,
                    2026
                )
            )
        )

        changed = (
            image_2017
            .neq(image_2026)
            .rename("change")
            .toByte()
        )

        tasks = []

        tasks.append(
            export_table(statistics)
        )

        tasks.append(
            export_image(
                image_2017.visualize(
                    min=0,
                    max=8,
                    palette=PALETTE
                ),
                "GBoS_Landcover_2017",
                "exports/landcover_2017",
                country
            )
        )

        tasks.append(
            export_image(
                image_2026.visualize(
                    min=0,
                    max=8,
                    palette=PALETTE
                ),
                "GBoS_Landcover_2026",
                "exports/landcover_2026",
                country
            )
        )

        tasks.append(
            export_image(
                changed.visualize(
                    min=0,
                    max=1,
                    palette=CHANGE_PALETTE
                ),
                "GBoS_Landcover_Change",
                "exports/change_2017_2026",
                country
            )
        )

        print("Waiting for Earth Engine exports...")

        wait_for_tasks(tasks)

        print("Downloading generated files...")

        csv_files = download_prefix(
            "exports/ea_statistics"
        )

        image_specs = [
            ("exports/landcover_2017", "landcover_2017"),
            ("exports/landcover_2026", "landcover_2026"),
            ("exports/change_2017_2026", "change_2017_2026")
        ]

        for prefix, layer in image_specs:

            files = download_prefix(prefix)

            tif = next(
                (
                    file for file in files
                    if file.suffix.lower() in (".tif", ".tiff")
                ),
                None
            )

            if tif is None:
                raise RuntimeError(
                    f"No GeoTIFF was downloaded for {layer}"
                )

            print("Creating tiles:", layer)

            create_tiles(
                tif,
                layer
            )

        print("Building public statistics JSON...")

        rows = read_csv_files(csv_files)

        if not rows:
            raise RuntimeError(
                "No EA statistics were returned."
            )

        build_statistics(rows)

        metadata = {
            "generated_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime()
            ),
            "project": PROJECT,
            "ea_asset": EA_ASSET,
            "dynamic_world_observations": counts,
            "period_2017": "2017-01-01 to 2018-01-01",
            "period_2026": f"2026-01-01 to {today}"
        }

        (DATA_DIR / "run_metadata.json").write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8"
        )

        print("SUCCESS: GBoS GEOAI outputs generated.")

    finally:

        if os.path.exists(key_path):
            os.remove(key_path)


if __name__ == "__main__":
    main()
