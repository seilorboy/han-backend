# Synthetic BN02 experiment

`tools/generate_bn02_test_data.py` generates one Helsinki calendar day's synthetic
BN02 intervals using the original UTC timestamps. It assumes common-area PV
self-consumption is zero. For each interval:

- COMMON_MAIN BN02 export = PV_MAIN INTERNAL production.
- COMMON_MAIN BN02 import = COMMON_MAIN BN03 import.
- Apartment BN02 import = apartment BN03 import + (PV - common BN03 export) / 24.
- Apartment BN02 export = apartment BN03 export.
- PV_MAIN stays INTERNAL; existing series are not modified.

This is a visualization experiment, not reconstructed Datahub measurements. The
current Sankey uses common BN02 export for the PV split and BN03 imports for Grid;
apartment BN02 values are not currently used to calculate the displayed split.
Synthetic intervals with simultaneous common import/export may trigger the
backend's BN01/BN02 consistency warning if real BN01 data is present.

The tool requires complete source intervals for all 26 meters and refuses existing
BN02 rows. Resolve missing/inconsistent source data or choose a different day.

After transferring the script to the server, run from the repository root:

```bash
mkdir -p data/bn02-test

docker compose run --rm --no-deps \
  -v "$PWD/tools:/tools:ro" -v "$PWD/data/bn02-test:/test-data" \
  api python /tools/generate_bn02_test_data.py --date 2025-09-01
```

After reviewing the preview, create the series:

```bash
docker compose run --rm --no-deps \
  -v "$PWD/tools:/tools:ro" -v "$PWD/data/bn02-test:/test-data" \
  api python /tools/generate_bn02_test_data.py --date 2025-09-01 \
  --apply --manifest /test-data/2025-09-01.json
```

The manifest is saved on the host under `data/bn02-test/`. Keep it until cleanup.
Open Sankey for the selected date: expected common PV use is zero, apartment PV
use is PV minus common BN03 export, and Grid and Export totals are unchanged.
The UI does not label synthetic series automatically; remove the experiment after
checking it and before importing real BN02 for this date.

Remove only recorded test rows (omit `--apply` for an undo preview):

```bash
docker compose run --rm --no-deps \
  -v "$PWD/tools:/tools:ro" -v "$PWD/data/bn02-test:/test-data" \
  api python /tools/generate_bn02_test_data.py \
  --undo /test-data/2025-09-01.json --apply
```

Undo refuses to delete recorded rows whose values have changed. Both creation
and undo use a database transaction; errors roll back that operation. Do not
reuse a manifest filename. Retain it if a database commit reports an uncertain
outcome so the recorded IDs can be checked and cleaned up.
