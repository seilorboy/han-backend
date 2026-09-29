# BN01–BN03 and internal consumption migration

Apply the changes in this order. Do not import BN01 or BN02 rows before the new
schema and backend are active.

## 1. Back up the database

Create and verify a complete dump of `Valkamakatu11` before any schema change.

## 2. Run the one-time migration

Copy `20_measurement_series_migration.sql` to the database container and run it
with an administrative MySQL account.

The migration:

- adds `reading_type`
- marks existing load rows as `BN03`
- marks existing `pv_raw` rows as `INTERNAL`
- adds `wh_consumption`
- permits the `consumption_raw` meter role
- changes the unique key to `(meter_id, ts, reading_type)`

Verify after migration:

```sql
DESCRIBE measurements;
SHOW INDEX FROM measurements;

SELECT reading_type, COUNT(*)
FROM measurements
GROUP BY reading_type;
```

Existing data should initially consist of `BN03` and `INTERNAL` rows.

## 3. Deploy application files

Replace:

- `api/app.py`
- `web/sankey.js`
- `db/init/10_valkamakatu11.sql`

The init file is for new empty database volumes. It does not migrate the current
database.

Rebuild and recreate the API and web containers, then test `/api/sankey` before
importing new reading types. With no BN02 data yet, PV remains in the explicit
fallback node `CommunityUse`.

## 4. Update import tools

Copy `measurement_upsert.py` beside the importer modules or merge its SQL into
them. Every imported row must provide a reading type.

Mapping:

| Source series | `reading_type` | Value column |
| --- | --- | --- |
| Datahub measured consumption | `BN01` | `wh_import` |
| Datahub measured production | `BN01` | `wh_export` |
| Datahub netted consumption | `BN02` | `wh_import` |
| Datahub netted production | `BN02` | `wh_export` |
| Datahub community consumption | `BN03` | `wh_import` |
| Datahub community production | `BN03` | `wh_export` |
| Internal PV submeter | `INTERNAL` | `wh_prod` |
| Internal consumption submeter | `INTERNAL` | `wh_consumption` |

Never store Datahub production in `wh_prod`. That column is reserved for gross
production from an internal submeter.

## 5. Import the common-area series

For `COMMON_MAIN`, import available BN01, BN02 and BN03 consumption and
production values at the original UTC timestamps and resolution.

The Sankey calculation is performed per interval:

```text
PV to common = PV_MAIN INTERNAL production - COMMON_MAIN BN02 production

PV to apartments = COMMON_MAIN BN02 production - COMMON_MAIN BN03 production

PV export = COMMON_MAIN BN03 production
```

The apartment total is divided equally between the 24 apartments and labelled
as an estimate. Grid flows continue to use the final BN03 consumption values.

## 6. Data-quality checks

For each interval, check:

```text
0 <= BN03 production <= BN02 production <= internal PV production
```

When BN01 is available, also check:

```text
BN02 production ~= max(BN01 production - BN01 consumption, 0)
BN02 consumption ~= max(BN01 consumption - BN01 production, 0)
```

The API logs warnings when these balances differ by more than one watt-hour.

