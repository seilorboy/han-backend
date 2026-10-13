"""Import the detailed energy-community workbook into measurements.

The source workbook uses Europe/Helsinki wall-clock timestamps. Preview is the
default. Database writes require both --apply and --accept-source-warnings.
"""

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo


HELSINKI = ZoneInfo("Europe/Helsinki")
UTC = timezone.utc
APARTMENT_COUNT = 24


@dataclass(frozen=True)
class Interval:
    timestamp: datetime
    pv_kwh: float
    common_bn01_import_kwh: float
    common_bn01_export_kwh: float
    common_bn02_import_kwh: float
    common_bn02_export_kwh: float
    common_bn03_import_kwh: float
    common_bn03_export_kwh: float
    apartment_bn01_kwh: tuple
    apartment_bn03_kwh: tuple


def parse_local_timestamp(value):
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value.strip():
        result = datetime.fromisoformat(value.strip())
    else:
        return None
    if result.tzinfo is not None:
        raise ValueError(f"Expected a local timestamp without offset, got {value!r}")
    return result


def local_to_utc_naive(local_timestamp, dst_fold="skip"):
    """Convert an unambiguous Helsinki wall-clock timestamp to UTC-naive.

    Ambiguous autumn timestamps are skipped by default because the workbook
    contains no offset/fold marker. A caller may explicitly choose first or
    second, but the choice must never be implicit.
    """
    first = local_timestamp.replace(tzinfo=HELSINKI, fold=0)
    second = local_timestamp.replace(tzinfo=HELSINKI, fold=1)

    first_valid = first.astimezone(UTC).astimezone(HELSINKI).replace(tzinfo=None) == local_timestamp
    second_valid = second.astimezone(UTC).astimezone(HELSINKI).replace(tzinfo=None) == local_timestamp

    if not first_valid and not second_valid:
        raise ValueError(f"Non-existent Helsinki wall-clock time: {local_timestamp}")

    ambiguous = first_valid and second_valid and first.utcoffset() != second.utcoffset()
    if ambiguous:
        if dst_fold == "skip":
            return None
        aware = first if dst_fold == "first" else second
    else:
        aware = first if first_valid else second

    return aware.astimezone(UTC).replace(tzinfo=None)


def energy(value, *, cell):
    if value is None or value == "":
        raise ValueError(f"Missing energy value in {cell}")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"Invalid energy value in {cell}: {value!r}")
    return result


def validate_headers(property_headers, apartment_headers):
    expected_property = {
        0: "Päivämäärä",
        1: "PV tuotto",
        2: "BN1 tuotto",
        4: "BN1 kulutus",
        8: "BN2 Kiinteistö",
        9: "BN03",
    }
    for index, text in expected_property.items():
        if text.casefold() not in str(property_headers[index]).casefold():
            raise ValueError(
                f"Unexpected Kiinteistö header in column {index + 1}: "
                f"{property_headers[index]!r}; expected text {text!r}"
            )

    for apartment in range(1, APARTMENT_COUNT + 1):
        bn01 = str(apartment_headers[7 + apartment])
        bn03 = str(apartment_headers[31 + apartment])
        if "bn1" not in bn01.casefold() or f"a{apartment}" not in bn01.casefold():
            raise ValueError(f"Unexpected apartment BN01 header: {bn01!r}")
        if "bn3" not in bn03.casefold() or f"a{apartment}" not in bn03.casefold():
            raise ValueError(f"Unexpected apartment BN03 header: {bn03!r}")


def load_intervals(path, dst_fold="skip"):
    try:
        import openpyxl
    except ImportError as error:
        raise RuntimeError("openpyxl is required; install tools/requirements.txt") from error

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        required = {"Kiinteistö", "Asukkaat"}
        missing = required.difference(workbook.sheetnames)
        if missing:
            raise ValueError(f"Workbook is missing sheets: {sorted(missing)}")

        property_sheet = workbook["Kiinteistö"]
        apartment_sheet = workbook["Asukkaat"]
        property_headers = next(property_sheet.iter_rows(min_row=2, max_row=2, values_only=True))
        apartment_headers = next(apartment_sheet.iter_rows(min_row=2, max_row=2, values_only=True))
        validate_headers(property_headers, apartment_headers)

        property_rows = {}
        local_timestamps = []
        for row_number, row in enumerate(
            property_sheet.iter_rows(min_row=3, values_only=True), start=3
        ):
            local_timestamp = parse_local_timestamp(row[0])
            if local_timestamp is None:
                if any(value not in (None, "") for value in row[1:]):
                    raise ValueError(f"Kiinteistö row {row_number} has data but no timestamp")
                continue
            if local_timestamp in property_rows:
                raise ValueError(f"Duplicate Kiinteistö timestamp: {local_timestamp}")
            property_rows[local_timestamp] = (row_number, row)
            local_timestamps.append(local_timestamp)

        apartment_rows = {}
        untimestamped_apartment_rows = []
        for row_number, row in enumerate(
            apartment_sheet.iter_rows(min_row=3, values_only=True), start=3
        ):
            local_timestamp = parse_local_timestamp(row[0])
            if local_timestamp is None:
                if any(value not in (None, "") for value in row[8:80]):
                    untimestamped_apartment_rows.append(row_number)
                continue
            if local_timestamp in apartment_rows:
                raise ValueError(f"Duplicate Asukkaat timestamp: {local_timestamp}")
            apartment_rows[local_timestamp] = (row_number, row)

        if set(property_rows) != set(apartment_rows):
            raise ValueError("Kiinteistö and Asukkaat timestamps do not match")

        expected = []
        cursor = min(local_timestamps)
        while cursor <= max(local_timestamps):
            expected.append(cursor)
            cursor += timedelta(hours=1)
        missing_local_hours = [stamp for stamp in expected if stamp not in property_rows]
        nonexistent_dst_hours = []
        unexpected_missing_hours = []
        for stamp in missing_local_hours:
            try:
                local_to_utc_naive(stamp)
            except ValueError:
                nonexistent_dst_hours.append(stamp)
            else:
                unexpected_missing_hours.append(stamp)

        skipped_ambiguous = []
        intervals = []
        source_warning_counts = Counter()
        source_warning_examples = defaultdict(list)

        for local_timestamp in sorted(property_rows):
            utc_timestamp = local_to_utc_naive(local_timestamp, dst_fold)
            if utc_timestamp is None:
                skipped_ambiguous.append(local_timestamp)
                continue

            property_row_number, prop = property_rows[local_timestamp]
            apartment_row_number, apts = apartment_rows[local_timestamp]
            pv = energy(prop[1], cell=f"Kiinteistö!B{property_row_number}")
            common_bn01_export = energy(prop[2], cell=f"Kiinteistö!C{property_row_number}")
            common_bn01_import = energy(prop[4], cell=f"Kiinteistö!E{property_row_number}")
            common_bn02_import = energy(prop[8], cell=f"Kiinteistö!I{property_row_number}")
            common_bn03_export = energy(prop[9], cell=f"Kiinteistö!J{property_row_number}")

            apartment_bn01 = tuple(
                energy(apts[8 + index], cell=f"Asukkaat row {apartment_row_number}, BN01 A{index + 1}")
                for index in range(APARTMENT_COUNT)
            )
            apartment_bn03 = tuple(
                energy(apts[32 + index], cell=f"Asukkaat row {apartment_row_number}, BN03 A{index + 1}")
                for index in range(APARTMENT_COUNT)
            )
            allocation = sum(
                max(before - after, 0.0)
                for before, after in zip(apartment_bn01, apartment_bn03)
            )
            common_bn02_export = common_bn03_export + allocation

            checks = {
                "BN02 export exceeds PV": common_bn02_export - pv,
                "BN01 export exceeds PV": common_bn01_export - pv,
                "BN02 import and export both positive": min(
                    common_bn02_import, common_bn02_export
                ),
                "BN03 import and export both positive": min(
                    common_bn02_import, common_bn03_export
                ),
            }
            for message, amount in checks.items():
                if amount > 0.001:
                    source_warning_counts[message] += 1
                    if len(source_warning_examples[message]) < 5:
                        source_warning_examples[message].append(
                            (local_timestamp, amount)
                        )

            intervals.append(
                Interval(
                    timestamp=utc_timestamp,
                    pv_kwh=pv,
                    common_bn01_import_kwh=common_bn01_import,
                    common_bn01_export_kwh=common_bn01_export,
                    common_bn02_import_kwh=common_bn02_import,
                    common_bn02_export_kwh=common_bn02_export,
                    common_bn03_import_kwh=common_bn02_import,
                    common_bn03_export_kwh=common_bn03_export,
                    apartment_bn01_kwh=apartment_bn01,
                    apartment_bn03_kwh=apartment_bn03,
                )
            )

        utc_timestamps = [interval.timestamp for interval in intervals]
        if len(utc_timestamps) != len(set(utc_timestamps)):
            raise ValueError("Timestamp conversion created duplicate UTC timestamps")

        diagnostics = {
            "source_intervals": len(property_rows),
            "importable_intervals": len(intervals),
            "first_local": min(local_timestamps),
            "last_local": max(local_timestamps),
            "first_utc": min(utc_timestamps),
            "last_utc": max(utc_timestamps),
            "nonexistent_dst_hours": nonexistent_dst_hours,
            "unexpected_missing_hours": unexpected_missing_hours,
            "skipped_ambiguous_hours": skipped_ambiguous,
            "untimestamped_apartment_rows": untimestamped_apartment_rows,
            "source_warning_counts": dict(source_warning_counts),
            "source_warning_examples": dict(source_warning_examples),
        }
        return intervals, diagnostics
    finally:
        workbook.close()


def database_rows(intervals, meter_ids):
    """Yield complete measurement rows in Wh; apartment BN02 equals BN01.

    Apartments have no production behind their Datahub usage points, so their
    BN01 consumption is also their BN02 consumption. BN03 comes directly from
    the workbook's final billing series.
    """
    for interval in intervals:
        yield (
            meter_ids["PV_MAIN"], interval.timestamp, "INTERNAL",
            0.0, 0.0, interval.pv_kwh * 1000.0, 0.0,
        )
        for reading_type, imported, exported in (
            ("BN01", interval.common_bn01_import_kwh, interval.common_bn01_export_kwh),
            ("BN02", interval.common_bn02_import_kwh, interval.common_bn02_export_kwh),
            ("BN03", interval.common_bn03_import_kwh, interval.common_bn03_export_kwh),
        ):
            yield (
                meter_ids["COMMON_MAIN"], interval.timestamp, reading_type,
                imported * 1000.0, exported * 1000.0, 0.0, 0.0,
            )
        for index in range(APARTMENT_COUNT):
            serial = f"APT{index + 1}"
            for reading_type, imported in (
                ("BN01", interval.apartment_bn01_kwh[index]),
                ("BN02", interval.apartment_bn01_kwh[index]),
                ("BN03", interval.apartment_bn03_kwh[index]),
            ):
                yield (
                    meter_ids[serial], interval.timestamp, reading_type,
                    imported * 1000.0, 0.0, 0.0, 0.0,
                )


def totals(intervals):
    result = defaultdict(float)
    for interval in intervals:
        result["PV_MAIN INTERNAL production"] += interval.pv_kwh
        result["COMMON_MAIN BN01 import"] += interval.common_bn01_import_kwh
        result["COMMON_MAIN BN01 export"] += interval.common_bn01_export_kwh
        result["COMMON_MAIN BN02 import"] += interval.common_bn02_import_kwh
        result["COMMON_MAIN BN02 export"] += interval.common_bn02_export_kwh
        result["COMMON_MAIN BN03 import"] += interval.common_bn03_import_kwh
        result["COMMON_MAIN BN03 export"] += interval.common_bn03_export_kwh
        result["Apartments BN01/BN02 import"] += sum(interval.apartment_bn01_kwh)
        result["Apartments BN03 import"] += sum(interval.apartment_bn03_kwh)
    return result


def load_environment():
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")


def db_config():
    missing = [
        name for name in ("DB_USER", "DB_PASSWORD", "DB_NAME")
        if not os.getenv(name)
    ]
    if missing:
        raise RuntimeError(f"Missing database settings: {', '.join(missing)}")
    return {
        "host": os.getenv("DB_HOST", "db"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "database": os.environ["DB_NAME"],
    }


def resolve_meter_ids(cursor):
    expected = {"PV_MAIN", "COMMON_MAIN"}
    expected.update(f"APT{index}" for index in range(1, APARTMENT_COUNT + 1))
    cursor.execute("SELECT id, meter_serial, role, active FROM meters")
    found = {}
    for meter_id, serial, role, active in cursor.fetchall():
        serial = (serial or "").upper()
        if serial not in expected:
            continue
        required_role = "pv_raw" if serial == "PV_MAIN" else "load"
        if not active or role != required_role or serial in found:
            raise ValueError(f"Invalid, inactive or duplicate meter: {serial}")
        found[serial] = meter_id
    missing = expected.difference(found)
    if missing:
        raise ValueError(f"Missing meters: {sorted(missing)}")
    return found


def apply_rows(intervals):
    try:
        import mysql.connector
    except ImportError as error:
        raise RuntimeError(
            "mysql-connector-python is required; install tools/requirements.txt"
        ) from error

    load_environment()
    connection = mysql.connector.connect(**db_config())
    cursor = connection.cursor()
    sql = """
        INSERT INTO measurements
            (meter_id, ts, reading_type, wh_import, wh_export, wh_prod, wh_consumption)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            wh_import = VALUES(wh_import),
            wh_export = VALUES(wh_export),
            wh_prod = VALUES(wh_prod),
            wh_consumption = VALUES(wh_consumption)
    """
    try:
        meter_ids = resolve_meter_ids(cursor)
        batch = []
        written = 0
        for row in database_rows(intervals, meter_ids):
            batch.append(row)
            if len(batch) == 1000:
                cursor.executemany(sql, batch)
                written += len(batch)
                batch.clear()
        if batch:
            cursor.executemany(sql, batch)
            written += len(batch)
        connection.commit()
        return written
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def print_preview(intervals, diagnostics):
    print("\n=== TUONNIN ESIKATSELU ===")
    print(f"Lähteen aikaleimalliset tunnit: {diagnostics['source_intervals']}")
    print(f"Tuotavat yksiselitteiset tunnit: {diagnostics['importable_intervals']}")
    print(f"Paikallinen aikaväli: {diagnostics['first_local']} – {diagnostics['last_local']}")
    print(f"UTC-aikaväli: {diagnostics['first_utc']} – {diagnostics['last_utc']}")
    print(f"Tietokantarivejä: {len(intervals) * 76}")
    print("\nEnergiat (kWh):")
    for name, value in totals(intervals).items():
        print(f"  {name}: {value:.3f}")

    for label, values in (
        ("Kesäaikasiirtymän olemattomat paikalliset tunnit", diagnostics["nonexistent_dst_hours"]),
        ("Odottamatta puuttuvat paikalliset tunnit", diagnostics["unexpected_missing_hours"]),
        ("Ohitetut DST-epäselvät tunnit", diagnostics["skipped_ambiguous_hours"]),
        ("Asukkaat-rivit ilman aikaleimaa", diagnostics["untimestamped_apartment_rows"]),
    ):
        print(f"\n{label}: {len(values)}")
        for value in values[:10]:
            print(f"  {value}")

    print("\nLähdeaineiston varoitukset:")
    for message, count in diagnostics["source_warning_counts"].items():
        print(f"  {message}: {count} tuntia")
        for timestamp, amount in diagnostics["source_warning_examples"][message]:
            print(f"    {timestamp}: {amount:.3f} kWh")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument(
        "--dst-fold", choices=("skip", "first", "second"), default="skip",
        help="ambiguous autumn hour handling; default: skip",
    )
    parser.add_argument("--accept-source-warnings", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    intervals, diagnostics = load_intervals(args.workbook, args.dst_fold)
    print_preview(intervals, diagnostics)

    has_warnings = bool(
        diagnostics["unexpected_missing_hours"]
        or diagnostics["skipped_ambiguous_hours"]
        or diagnostics["untimestamped_apartment_rows"]
        or diagnostics["source_warning_counts"]
    )
    if not args.apply:
        print("\nEsikatselu valmis. Tietokantaan ei kirjoitettu.")
        return
    if has_warnings and not args.accept_source_warnings:
        raise SystemExit(
            "Tuonti keskeytetty: hyväksy raportoidut lähdevaroitukset "
            "valinnalla --accept-source-warnings."
        )

    written = apply_rows(intervals)
    print(f"\nValmis: {written} mittausriviä lisättiin tai päivitettiin.")


if __name__ == "__main__":
    main()
