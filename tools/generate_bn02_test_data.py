"""Synthetic BN02 experiment. Preview by default; UTC rows, Helsinki date selection.

Run in the API container (mysql-connector-python is already installed).
The manifest records inserted IDs and values so undo never deletes other series.
PV_MAIN remains INTERNAL: an internal submeter must not be labelled BN02.
"""
import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo


def build_rows(meters, measurements):
    expected = {"COMMON_MAIN": "load", "PV_MAIN": "pv_raw"}
    expected.update({f"APT{i}": "load" for i in range(1, 25)})
    ids = {}
    for meter in meters:
        serial = meter["meter_serial"]
        if serial in expected:
            if serial in ids or meter["role"] != expected[serial] or not meter["active"]:
                raise ValueError(f"Invalid/duplicate/inactive meter: {serial}")
            ids[serial] = meter["id"]
    if ids.keys() != expected.keys():
        raise ValueError("Requires active COMMON_MAIN, PV_MAIN and APT1–APT24")
    source = {(r["meter_id"], r["ts"], r["reading_type"]): r for r in measurements}
    timestamps = sorted({r["ts"] for r in measurements if r["meter_id"] in ids.values()})
    if not timestamps:
        raise ValueError("No measurements for selected date")

    def energy(row, field):
        value = float(row[field]) if row[field] is not None else None
        if value is None or not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid source {field} at {row['ts']}")
        return value

    result = []
    for ts in timestamps:
        def get(serial, kind):
            key = (ids[serial], ts, kind)
            if key not in source:
                raise ValueError(f"Missing {serial} {kind} at {ts}; no rows written")
            return source[key]
        pv = energy(get("PV_MAIN", "INTERNAL"), "wh_prod")
        common = get("COMMON_MAIN", "BN03")
        export = energy(common, "wh_export")
        if export > pv:
            raise ValueError(f"BN03 export exceeds PV at {ts}")
        share = (pv - export) / 24
        for serial in expected:
            if serial == "PV_MAIN":
                continue
            if (ids[serial], ts, "BN02") in source:
                raise ValueError(f"BN02 already exists for {serial} at {ts}; choose another date or undo")
            bn03 = get(serial, "BN03")
            imported = energy(bn03, "wh_import")
            exported = pv if serial == "COMMON_MAIN" else energy(bn03, "wh_export")
            if serial != "COMMON_MAIN":
                imported += share
            result.append((ids[serial], ts, "BN02", imported, exported, 0.0, 0.0))
    return result


def undo(cursor, manifest, database):
    if manifest["database"] != database:
        raise ValueError("Manifest database does not match DB_NAME")
    for entry in manifest["rows"]:
        cursor.execute("SELECT meter_id, ts, reading_type, wh_import, wh_export, wh_prod, wh_consumption FROM measurements WHERE id=%s FOR UPDATE", (entry["id"],))
        actual = cursor.fetchone()
        if actual is None:
            continue
        actual = list(actual)
        actual[1] = actual[1].isoformat()
        if actual != entry["values"] or actual[2] != "BN02":
            raise ValueError(f"Row {entry['id']} changed since generation; undo cancelled")
        cursor.execute("DELETE FROM measurements WHERE id=%s", (entry["id"],))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--date", type=date.fromisoformat)
    choice.add_argument("--undo", type=Path, help="Manifest of test rows to remove")
    parser.add_argument("--apply", action="store_true", help="Write previewed changes")
    parser.add_argument("--manifest", type=Path, help="New manifest path, required for creation with --apply")
    args = parser.parse_args()
    if args.apply and args.date and args.manifest is None:
        parser.error("--apply requires --manifest for undo")
    import mysql.connector
    config = {"host": os.getenv("DB_HOST", "db"), "port": int(os.getenv("DB_PORT", "3306")),
              "user": os.environ["DB_USER"], "password": os.environ["DB_PASSWORD"],
              "database": os.environ["DB_NAME"]}
    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()
    try:
        if args.undo:
            undo(cursor, json.loads(args.undo.read_text()), config["database"])
            if args.apply:
                conn.commit()
            else:
                conn.rollback()
            print("Undo committed" if args.apply else "Undo preview OK; rolled back. Use --apply to remove.")
            return
        start = datetime.combine(args.date, time(), ZoneInfo("Europe/Helsinki"))
        end = start + timedelta(days=1)
        bounds = tuple(t.astimezone(timezone.utc).replace(tzinfo=None) for t in (start, end))
        cursor.close()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, meter_serial, role, active FROM meters")
        meters = cursor.fetchall()
        cursor.execute("SELECT meter_id, ts, reading_type, wh_import, wh_export, wh_prod, wh_consumption FROM measurements WHERE ts >= %s AND ts < %s", bounds)
        rows = build_rows(meters, cursor.fetchall())
        print(f"SYNTHETIC BN02: {args.date}, {len(rows)} rows, {len(rows) // 25} intervals")
        print("Assumption: no PV self-consumption in common areas; remaining PV shared equally across 24 apartments.")
        if not args.apply:
            print("Preview only. No database changes.")
            return
        manifest = {"database": config["database"], "date": str(args.date), "rows": []}
        for row in rows:
            cursor.execute("INSERT INTO measurements (meter_id, ts, reading_type, wh_import, wh_export, wh_prod, wh_consumption) VALUES (%s,%s,%s,%s,%s,%s,%s)", row)
            values = list(row)
            values[1] = values[1].isoformat()
            manifest["rows"].append({"id": cursor.lastrowid, "values": values})
        # Persist recovery information before commit; never overwrite an old manifest.
        with args.manifest.open("x") as output:
            json.dump(manifest, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        conn.commit()
        print(f"Committed. Keep undo manifest: {args.manifest}")
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
