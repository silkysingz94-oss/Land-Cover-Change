
# GBoS GEOAI | Gambia Persistent Land-Cover Change Intelligence

A public geospatial dashboard for satellite-derived land-cover mapping and change analysis in The Gambia.

## Project components

- Google Earth Engine: satellite image processing.
- Dynamic World V1: land-cover classification.
- Google Cloud Storage: temporary export storage.
- GitHub Actions: automated processing and updates.
- Leaflet: interactive web mapping.
- Chart.js: land-cover analytics.
- Census_EAs_Geo.json: GBoS EA boundary reference.

## Comparison periods

- Baseline: 1 January 2017 to 1 January 2018.
- Current: 1 January 2026 to the workflow execution date.

The 2026 output is year-to-date and is not a completed annual classification.

## Dynamic World classes

| Value | Class |
|---|---|
| 0 | Water |
| 1 | Trees |
| 2 | Grass |
| 3 | Flooded vegetation |
| 4 | Crops |
| 5 | Shrub and scrub |
| 6 | Built area |
| 7 | Bare ground |
| 8 | Snow and ice |

## Repository structure

```text
Land-Cover-Change/
├── index.html
├── requirements.txt
├── README.md
├── Census_EAs_Geo.json
├── scripts/
│   └── run_pipeline.py
├── data/
│   └── .gitkeep
├── tiles/
│   └── .gitkeep
└── .github/
    └── workflows/
        └── update-landcover.yml
```

## GitHub configuration

### Repository secrets

Add these under:

Settings > Secrets and variables > Actions > Secrets.

| Secret | Value |
|---|---|
| EE_PROJECT_ID | Your Google Cloud project ID |
| EE_SERVICE_ACCOUNT_JSON | Full service-account JSON key contents |

### Repository variables

Add these under:

Settings > Secrets and variables > Actions > Variables.

| Variable | Value |
|---|---|
| GCS_BUCKET | gambia-landcover-outputs |
| GEE_EA_ASSET | projects/ee-aishaansu80/assets/GambiaEA_Final1 |

Change the bucket name if you created a different bucket.

## Google Cloud requirements

1. Enable the Earth Engine API.
2. Enable the Cloud Storage API.
3. Create a Cloud Storage bucket.
4. Register and authorise the service account for Earth Engine.
5. Give the service account access to the EA asset.
6. Give the service account permission to create and read objects in the bucket.
7. Ensure the Earth Engine project is authorised for exports to Cloud Storage.

Never place service-account credentials in index.html or any public repository file.

## Running the workflow

1. Open the GitHub Actions tab.
2. Select Update Land Cover Intelligence.
3. Select Run workflow.
4. Select the main branch.
5. Start the workflow.
6. Wait for all Earth Engine exports and tile generation to finish.

The workflow is also scheduled for the fifth day of every month at 03:00 UTC.

## Generated outputs

```text
data/
├── stats.json
├── landcover_2017.csv
├── landcover_2026.csv
└── change_statistics.csv

tiles/
├── landcover_2017/
├── landcover_2026/
└── landcover_change/
```

## Important limitations

- Dynamic World is a satellite-derived land-cover product.
- The 2026 classification covers available observations from 1 January to the processing date.
- Cloud cover, observation availability, classification uncertainty and spatial resolution affect results.
- The comparison is not a direct field-validated change inventory.
- Satellite-derived results should not be interpreted as official GBoS land-cover statistics.
- The raster tiles are generated for web display at zoom levels 5–11.
- The current dashboard uses national raster tiles; selecting an EA or ward zooms to that area and filters its statistics, but does not generate a separately clipped raster for each selection.

## Credits

Produced by Ansu Singhateh  
GIS Analyst | GIS / Cartography Unit  
Gambia Bureau of Statistics

GBoS GEOAI • Research and educational use

