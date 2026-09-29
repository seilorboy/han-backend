"""Shared interval upserts; callers own the transaction and supply UTC timestamps."""

import math

READING_TYPES = {"BN01", "BN02", "BN03", "INTERNAL"}
ENERGY_COLUMNS = ("wh_import", "wh_export", "wh_prod", "wh_consumption")


def normalize_reading_type(reading_type):
    normalized = str(reading_type).strip().upper()
    if normalized not in READING_TYPES:
        raise ValueError(f"Unsupported reading_type {reading_type!r}; expected {sorted(READING_TYPES)}")
    return normalized


def upsert_measurement(
    cursor, *, meter_id, timestamp, reading_type,
    wh_import=None, wh_export=None, wh_prod=None, wh_consumption=None,
):
    """Update supplied channels only, preserving separately imported channels.

    Omitted channels start at zero for new rows. Explicit zero clears a channel.
    Datahub production is export; internal production is gross PV production.
    """
    reading_type = normalize_reading_type(reading_type)
    supplied = dict(zip(ENERGY_COLUMNS, (wh_import, wh_export, wh_prod, wh_consumption)))
    values = {name: float(value) for name, value in supplied.items() if value is not None}
    if not values:
        raise ValueError("At least one energy value is required")
    if any(not math.isfinite(value) or value < 0 for value in values.values()):
        raise ValueError("Energy values must be finite and non-negative")
    forbidden = ("wh_import", "wh_export") if reading_type == "INTERNAL" else ("wh_prod", "wh_consumption")
    if any(values.get(name, 0) != 0 for name in forbidden):
        raise ValueError(f"Invalid energy channel for {reading_type}")
    updates = ", ".join(f"{name} = VALUES({name})" for name in values)
    cursor.execute(
        f"""
        INSERT INTO measurements
            (meter_id, ts, reading_type, wh_import, wh_export, wh_prod, wh_consumption)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE {updates}
        """,
        (meter_id, timestamp, reading_type, *(values.get(name, 0.0) for name in ENERGY_COLUMNS)),
    )
