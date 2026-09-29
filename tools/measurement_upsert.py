"""Shared measurement upsert helper for Valkamakatu import tools."""

READING_TYPES = {"BN01", "BN02", "BN03", "INTERNAL"}


def upsert_measurement(
    cursor,
    *,
    meter_id,
    timestamp,
    reading_type,
    wh_import=0.0,
    wh_export=0.0,
    wh_prod=0.0,
    wh_consumption=0.0,
):
    """
    Insert or replace one interval series value.

    Datahub consumption belongs in wh_import and Datahub production in
    wh_export. Internal production submeters use wh_prod; internal consumption
    submeters use wh_consumption. The caller owns the database transaction.
    """

    normalized_type = str(reading_type).strip().upper()
    if normalized_type not in READING_TYPES:
        raise ValueError(
            f"Unsupported reading_type {reading_type!r}; "
            f"expected one of {sorted(READING_TYPES)}"
        )

    cursor.execute(
        """
        INSERT INTO measurements (
            meter_id,
            ts,
            reading_type,
            wh_import,
            wh_export,
            wh_prod,
            wh_consumption
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            wh_import = VALUES(wh_import),
            wh_export = VALUES(wh_export),
            wh_prod = VALUES(wh_prod),
            wh_consumption = VALUES(wh_consumption);
        """,
        (
            meter_id,
            timestamp,
            normalized_type,
            float(wh_import or 0),
            float(wh_export or 0),
            float(wh_prod or 0),
            float(wh_consumption or 0),
        ),
    )
