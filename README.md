
# GBoS GEOAI
## Gambia Persistent Land-Cover Change Intelligence (2017–2026)

An automated satellite remote-sensing and land-cover monitoring system for The Gambia.

### Main components

- Google Earth Engine: satellite image processing.
- Dynamic World V1: 10 m land-cover classification.
- Census Enumeration Areas: EA-level spatial statistics.
- Python: automated processing and output preparation.
- Google Cloud Storage: temporary processing exports.
- GitHub Actions: automated workflow.
- Leaflet: public interactive map.
- Chart.js: statistical visualisation.
- GitHub Pages: public dashboard hosting.

### Data periods

2017: Calendar-year baseline.

2026: Year-to-date observations through the latest successful update.

### Land-cover classes

0. Water
1. Trees
2. Grass
3. Flooded vegetation
4. Crops
5. Shrub and scrub
6. Built area
7. Bare ground
8. Snow and ice

### Required GitHub configuration

Repository Settings → Secrets and variables → Actions.

Create these secrets:

- EE_PROJECT_ID
- EE_SERVICE_ACCOUNT_JSON

Create these variables:

- GEE_EA_ASSET
- GCS_BUCKET

The Earth Engine asset should be a FeatureCollection containing the Gambian EA boundaries and the fields used by the processing script:

- feacode
- eaname
- wardname
- distname
- lganame
- RCO

The public dashboard boundary file is:

https://raw.githubusercontent.com/silkysingz94-oss/Land-Cover-Change/main/Census_EAs_Geo.json

### Run the workflow

1. Open the GitHub repository.
2. Select Actions.
3. Select GBoS GEOAI - Automated Land Cover Update.
4. Select Run workflow.
5. Wait for processing and publishing to finish.

The workflow is also scheduled to run on the 5th of each month.

### GitHub Pages

Repository Settings → Pages.

Select:

- Deploy from a branch
- Branch: main
- Folder: / (root)

Public dashboard:

https://silkysingz94-oss.github.io/Land-Cover-Change/

### Important interpretation

The 2026 map is year-to-date, not a complete annual observation. The change layer identifies pixels where the modal Dynamic World class differs between the two periods. It is not a direct measurement of the date or cause of change.

The land-cover maps and statistics are satellite-derived estimates and require independent validation before being used as official land-cover statistics.
