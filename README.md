# Energy Meter Reading, Data Logging and Visualization

This project collects, stores, processes and visualizes electricity data for
Valkamakatu 11.

The system combines:

- HAN/P1 meter reading with an Arduino Uno R4 WiFi
- a Flask REST API
- MySQL/MariaDB storage
- Docker-based deployment on Debian Linux
- a Chart.js consumption view
- a Plotly Sankey view for daily energy flows and annual totals

## System overview

The project currently handles two data paths.

### HAN/P1 readings

An Arduino Uno R4 WiFi reads a compatible electricity meter through its HAN/P1
port and sends readings to the Flask backend with HTTP POST requests. These
readings are stored in the `han_energy` table.

The backend can return the latest reading and aggregate readings into
15-minute intervals for the consumption chart.

### Valkamakatu 11 energy data

Hourly energy series are stored in the `measurements` table and connected to
meter metadata in the `meters` table. This dataset includes:

- the common-area connection point
- 24 apartment connection points
- an internal photovoltaic production submeter

The data is used to generate a daily Sankey diagram and annual Grid, Export and
PV totals.

## Components

### Arduino firmware

Folder: `arduino/`

The firmware:

- runs on Arduino Uno R4 WiFi
- reads a compatible HAN/P1 interface
- connects to the backend over WiFi
- sends readings with HTTP POST requests
- provides basic connection and transmission error handling

### Docker backend

Folder: `docker/`

The Docker deployment contains the Flask backend and a MySQL/MariaDB database.
Depending on the deployment, a reverse proxy can expose the API and static web
pages.

Start the configured services with:

```bash
docker compose up -d
```

Rebuild the backend after Python source changes:

```bash
docker compose up -d --build
```

Inspect service status and backend logs:

```bash
docker compose ps
docker compose logs -f
```

## Configuration

The Flask backend reads its database configuration from environment variables:

| Variable | Description |
| --- | --- |
| `DB_HOST` | Database hostname or Compose service name |
| `DB_USER` | Database user |
| `DB_PASSWORD` | Database password |
| `DB_NAME` | Database name, for example the Valkamakatu 11 database |

Keep credentials in the deployment environment or an untracked `.env` file.
Do not commit real passwords to the repository.

## Web views

### Consumption chart

The consumption page uses Chart.js to display readings aggregated into
15-minute intervals.

Relevant backend endpoint:

```text
GET /api/energy/quarter-hour?date=YYYY-MM-DD
```

### Sankey diagram

The Sankey page uses Plotly and loads its data from:

```text
GET /api/sankey?date=YYYY-MM-DD
```

The response contains:

- `nodes` and `links` for the selected day
- `meta` with daily totals
- `annual` with totals for the selected calendar year

Example response structure:

```json
{
  "date": "2025-09-01",
  "nodes": ["PV", "Grid", "Export", "Common", "APT1"],
  "links": [],
  "meta": {
    "pv_kwh": 0.0,
    "common_load_kwh": 0.0,
    "apartments_load_kwh": 0.0,
    "grid_to_load_kwh": 0.0,
    "pv_export_kwh": 0.0
  },
  "annual": {
    "year": 2025,
    "grid_kwh": 0.0,
    "export_kwh": 0.0,
    "pv_kwh": 0.0
  }
}
```

## Energy data model

### `meters`

The `meters` table identifies each energy series.

| Column | Purpose |
| --- | --- |
| `id` | Primary key |
| `meter_serial` | Application-level meter identifier |
| `usage_point_no` | Usage-point identifier, when available |
| `role` | `load`, `pv_raw` or `consumption_raw` |
| `apartment_id` | Apartment reference for apartment meters |
| `active` | Whether the meter is currently active |
| `created_at` | Row creation time |

The currently configured logical meters are:

- `PV_MAIN`: internal PV production submeter, role `pv_raw`
- `COMMON_MAIN`: common-area connection point, role `load`
- `APT1` through `APT24`: apartment connection points, role `load`

Future internal consumption submeters use role `consumption_raw`. Their measured
interval consumption is stored in `wh_consumption` with reading type
`INTERNAL`. Internal submeter consumption is not automatically counted as Grid
energy because it may measure a load already included in a Datahub load series.

`PV_MAIN` is an internal property submeter. It is not a distribution system
operator's Datahub metering series and must not be labelled BN01.

### `measurements`

Each row represents energy for one measurement interval. Values are stored in
watt-hours.

| Column | Purpose |
| --- | --- |
| `id` | Primary key |
| `meter_id` | Foreign key to `meters.id` |
| `ts` | Measurement interval timestamp |
| `reading_type` | `BN01`, `BN02`, `BN03` or `INTERNAL` |
| `wh_import` | Imported energy during the interval, Wh |
| `wh_export` | Exported energy during the interval, Wh |
| `wh_prod` | Production measured by an internal submeter, Wh |
| `wh_consumption` | Consumption measured by an internal submeter, Wh |
| `created_at` | Database insertion time |

Energy totals are calculated by summing interval values and dividing by 1000:

```text
kWh = SUM(Wh) / 1000
```

These values are interval energies, not cumulative meter-register readings.

### `han_energy`

The `han_energy` table stores readings received through the generic HAN API.

| Column | Purpose |
| --- | --- |
| `id` | Primary key |
| `ts` | Reading timestamp |
| `energy_kwh` | Received energy reading |

This table is separate from the Valkamakatu 11 `meters` and `measurements`
model.

## Datahub and energy-community semantics

Datahub series are stored separately by reading type:

- BN01 means a metered series
- BN02 means a netted series
- BN03 means an energy-community series after community credit allocation

The unique measurement key is `(meter_id, ts, reading_type)`. It allows BN01,
BN02 and BN03 values for the same connection point and interval to coexist.

The apartment BN03 `wh_import` values are final imported-energy values. The
solar-energy credit allocated to each community member has already been
deducted from them.

`COMMON_MAIN.wh_import` contains the final imported energy for the common-area
connection point. `COMMON_MAIN.wh_export` contains the surplus sold to the grid
after energy-community credit allocation.

`PV_MAIN` with reading type `INTERNAL` and column `wh_prod` contains total PV
production measured by the property's own production submeter.

The application therefore calculates the requested totals as follows:

```text
Grid = SUM(BN03 wh_import for all role='load' meters) / 1000

Export = SUM(COMMON_MAIN BN03 wh_export) / 1000

PV = SUM(PV_MAIN INTERNAL wh_prod) / 1000
```

PV production must not be subtracted from the load meters again. Doing so would
apply the energy-community credit twice and understate Grid energy.

For every interval, the Sankey PV split is calculated as follows:

```text
PV used in common areas = PV_MAIN INTERNAL production - COMMON_MAIN BN02 production

PV used by apartments = COMMON_MAIN BN02 production - COMMON_MAIN BN03 production

Export = COMMON_MAIN BN03 production
```

The apartment share is displayed as an estimate using an equal allocation of
`1/24`. Exact apartment-level allocation cannot be proven without the members'
own paired series. If a BN02 value is missing, the application does not invent
a split; it sends that interval's remainder to the `CommunityUse` fallback node
and labels it as unallocated PV.

## API

### Submit a HAN reading

```text
POST /api/energy
Content-Type: application/json
```

Example request body:

```json
{
  "energy_kwh": 43569.76
}
```

### Get the latest HAN reading

```text
GET /api/energy/latest
```

### Get 15-minute consumption values

```text
GET /api/energy/quarter-hour?date=YYYY-MM-DD
```

### Get daily Sankey data and annual totals

```text
GET /api/sankey?date=YYYY-MM-DD
```

Test the Sankey endpoint locally with:

```bash
curl -s "http://localhost:5000/api/sankey?date=2025-09-01" \
  | python3 -m json.tool
```

The externally exposed port can differ when Docker Compose or a reverse proxy
maps the Flask service to another address.

## Time zones

Database measurement timestamps are handled as UTC by the backend. User-selected
dates are interpreted in the `Europe/Helsinki` time zone and converted to UTC
query boundaries. This accounts for both standard time and daylight-saving
time.

The Python environment or operating-system image must provide IANA time-zone
data for `Europe/Helsinki`. If it does not, install the Python `tzdata` package
or add time-zone data to the container image.

## Requirements

### Hardware

- Arduino Uno R4 WiFi
- compatible electricity meter with a HAN/P1 interface
- Debian Linux host or virtual machine
- network connectivity between the reader and backend

### Software

- Docker Engine
- Docker Compose
- Arduino IDE 2.x for firmware development
- Python 3 with Flask, MySQL Connector and time-zone data in the backend image
- a modern web browser with access to the configured Chart.js and Plotly CDN
  resources

## Development and verification

After backend changes:

```bash
docker compose up -d --build
docker compose logs -f
```

Verify the database services and inspect available data when necessary:

```sql
SELECT
    m.meter_serial,
    MIN(ms.ts) AS first_measurement,
    MAX(ms.ts) AS last_measurement,
    COUNT(*) AS measurement_count
FROM measurements ms
JOIN meters m ON m.id = ms.meter_id
GROUP BY m.id, m.meter_serial
ORDER BY m.id;
```

Check for duplicate measurement intervals:

```sql
SELECT meter_id, ts, COUNT(*) AS row_count
FROM measurements
GROUP BY meter_id, ts
HAVING COUNT(*) > 1;
```

## Testing Sankey with synthetic BN02 data

Use `tools/generate_bn02_test_data.py` to generate temporary BN02 series for
one day when real BN02 data is unavailable. This experiment assumes that the
common areas use no PV directly and divides the remaining PV equally between
24 apartments. It does not reconstruct actual Datahub measurements.

For each measurement interval, the script calculates:

```text
COMMON_MAIN BN02 export = PV_MAIN INTERNAL production
COMMON_MAIN BN02 import = COMMON_MAIN BN03 import
Apartment PV share = (PV_MAIN INTERNAL production - COMMON_MAIN BN03 export) / 24
Apartment BN02 import = apartment BN03 import + apartment PV share
Apartment BN02 export = apartment BN03 export
```

`PV_MAIN` stays in the `INTERNAL` series. Existing measurements are preserved.
The current Sankey uses the common-area BN02 export to calculate the PV split;
it does not use the apartment BN02 series for the displayed allocation.

### Prerequisites

- Apply the measurement-series migration described in
  [the migration instructions](docs/IMPLEMENTATION.md) first.
- Update the server checkout so it contains the test-data script. Run the
  commands below from the repository root with the database service running
  and the API image built with its database environment configured.
- The selected day must have matching source intervals for active `PV_MAIN`,
  `COMMON_MAIN` and `APT1`–`APT24`: internal PV production and BN03 load series.
  The script rejects missing source intervals, existing BN02 rows in the target
  series, and common BN03 export greater than PV production.

Dates are interpreted in `Europe/Helsinki`; stored timestamps remain UTC.
Replace `2025-09-01` in the commands with the day you want to test, including
in the manifest filename.

### Preview and create test data

Preview the generated row count without writing to the database:

```bash
mkdir -p data/bn02-test

docker compose run --rm --no-deps \
  -v "$PWD/tools:/tools:ro" \
  -v "$PWD/data/bn02-test:/test-data" \
  api python /tools/generate_bn02_test_data.py \
  --date 2025-09-01
```

If the preview succeeds, create the test rows with `--apply`:

```bash
docker compose run --rm --no-deps \
  -v "$PWD/tools:/tools:ro" \
  -v "$PWD/data/bn02-test:/test-data" \
  api python /tools/generate_bn02_test_data.py \
  --date 2025-09-01 --apply \
  --manifest /test-data/2025-09-01.json
```

The manifest records the inserted row IDs and values. It is saved on the server
at `data/bn02-test/2025-09-01.json`. **Keep this file until the test rows have
been removed.** Use a new manifest filename for each experiment; the script
refuses to overwrite an existing file.

### Check the diagram

Reload `/sankey.html` and select the test date. No service restart is needed.
Expected results for the selected day:

- PV used in common areas is zero under this test assumption.
- PV used by apartments equals total PV minus common BN03 export and is split
  equally among the 24 apartments.
- The unallocated PV flow disappears for the complete test intervals.
- Grid and Export totals remain unchanged.

The UI does not automatically label the generated series as test data. If real
BN01 values exist, the synthetic BN02 values may trigger BN01/BN02 consistency
warnings in backend logs.

### Remove test data

After checking the diagram, remove the generated rows using the saved manifest:

```bash
docker compose run --rm --no-deps \
  -v "$PWD/tools:/tools:ro" \
  -v "$PWD/data/bn02-test:/test-data" \
  api python /tools/generate_bn02_test_data.py \
  --undo /test-data/2025-09-01.json --apply
```

Omit `--apply` to preview the removal; that operation is rolled back. Undo
removes only the recorded rows and refuses deletion if their values have
changed. Remove the test series before importing real BN02 data for the same
day. Reload the diagram afterwards to see the original data again.

See [the detailed test-data notes](docs/BN02_TEST_DATA.md) for additional
transaction and recovery details.

## Known limitations and possible improvements

- Import the available BN01, BN02 and BN03 series for all relevant connection
  points.
- Store member-specific credit allocations if exact apartment-level PV flows
  are required instead of the current equal `1/24` estimate.
- Add automated tests for API responses and energy-balance rules.
- Add database migrations and explicit uniqueness constraints for measurement
  intervals.
- Add authentication and transport security when measurement endpoints are
  exposed outside a trusted network.
- Add monitoring, data-quality validation and missing-interval reporting.
- Add support for additional meter types and measurement resolutions.

## License

Add or update the repository's `LICENSE` file to state the licensing terms.
