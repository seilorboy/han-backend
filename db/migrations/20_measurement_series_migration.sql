-- One-time migration for an existing Valkamakatu11 database.
-- Take a verified database backup before running this script.
--
-- Existing load-meter rows are known to contain BN03 values.
-- Existing PV_MAIN rows contain internal submeter production.

USE Valkamakatu11;

ALTER TABLE meters
    MODIFY role ENUM('load', 'pv_raw', 'consumption_raw')
        COLLATE utf8mb4_unicode_ci NOT NULL;

ALTER TABLE measurements
    ADD COLUMN reading_type
        ENUM('BN01', 'BN02', 'BN03', 'INTERNAL') NULL AFTER ts,
    ADD COLUMN wh_consumption DOUBLE DEFAULT 0 AFTER wh_prod;

UPDATE measurements ms
JOIN meters m ON m.id = ms.meter_id
SET ms.reading_type = CASE
    WHEN m.role = 'pv_raw' THEN 'INTERNAL'
    ELSE 'BN03'
END
WHERE ms.reading_type IS NULL;

-- Abort manually if this query returns anything other than zero.
SELECT COUNT(*) AS rows_without_reading_type
FROM measurements
WHERE reading_type IS NULL;

ALTER TABLE measurements
    MODIFY reading_type
        ENUM('BN01', 'BN02', 'BN03', 'INTERNAL') NOT NULL,
    DROP INDEX uq_measurements_meter_ts,
    ADD UNIQUE KEY uq_measurements_meter_ts_type (
        meter_id,
        ts,
        reading_type
    );

-- Verification output.
SELECT
    m.meter_serial,
    m.role,
    ms.reading_type,
    COUNT(*) AS row_count,
    ROUND(SUM(ms.wh_import) / 1000.0, 3) AS import_kwh,
    ROUND(SUM(ms.wh_export) / 1000.0, 3) AS export_kwh,
    ROUND(SUM(ms.wh_prod) / 1000.0, 3) AS production_kwh,
    ROUND(SUM(ms.wh_consumption) / 1000.0, 3) AS consumption_kwh
FROM measurements ms
JOIN meters m ON m.id = ms.meter_id
GROUP BY m.id, m.meter_serial, m.role, ms.reading_type
ORDER BY m.id, ms.reading_type;
