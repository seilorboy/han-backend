from flask import Flask, request, jsonify
import mysql.connector
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import logging
import sys
from collections import defaultdict


logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)

UTC = timezone.utc
HELSINKI_TZ = ZoneInfo("Europe/Helsinki")

app = Flask(__name__)

DB_CONFIG = {
    "host": os.environ["DB_HOST"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "database": os.environ["DB_NAME"],
}


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


# Luodaan han_energy-taulu tarvittaessa (tämä on erillinen testitaulu).
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS han_energy (
                id INT AUTO_INCREMENT PRIMARY KEY,
                ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                energy_kwh DOUBLE NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


# -------------------------------------------
# S A N K E Y   A P U F U N K T I O T
# -------------------------------------------

def calculate_sankey_data(start_utc_naive, end_utc_naive):
    """
    Laskee päiväkohtaisen Sankey-datan.

    Tietokannan sisältö:
      - PV_MAIN / INTERNAL / wh_prod = sisäisen alamittarin PV-tuotanto
      - COMMON_MAIN / BN02 / wh_export = yhteisölle jaettavissa oleva PV
      - COMMON_MAIN / BN03 / wh_export = yhteisöjaon jälkeinen verkkovienti
      - load-mittarit / BN03 / wh_import = lopullinen verkosta ostettu energia

    Asunnoille kohdistunut PV arvioidaan tasajaolla 1/24. Jos BN02-sarja
    puuttuu joltakin aikaväliltä, kyseisen aikavälin PV-käyttö esitetään
    CommunityUse-koontina eikä sitä jaeta arvauksena asuntoihin.
    """

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    try:
        measurement_query = """
            SELECT
                m.meter_serial,
                m.role,
                ms.ts,
                ms.reading_type,
                COALESCE(ms.wh_import, 0) AS wh_import,
                COALESCE(ms.wh_export, 0) AS wh_export,
                COALESCE(ms.wh_prod, 0) AS wh_prod,
                COALESCE(ms.wh_consumption, 0) AS wh_consumption
            FROM measurements ms
            JOIN meters m ON m.id = ms.meter_id
            WHERE ms.ts >= %s
              AND ms.ts < %s
            ORDER BY ms.ts, m.id, ms.reading_type;
        """

        cur.execute(measurement_query, (start_utc_naive, end_utc_naive))
        rows = cur.fetchall()

        cur.execute(
            """
            SELECT meter_serial
            FROM meters
            WHERE active = 1
              AND meter_serial REGEXP '^APT[0-9]+$';
            """
        )
        apartment_rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    def apartment_sort_key(serial):
        try:
            return int(serial.replace("APT", ""))
        except ValueError:
            return 999999

    apartment_names = sorted(
        {
            (row["meter_serial"] or "").upper()
            for row in apartment_rows
            if row.get("meter_serial")
        },
        key=apartment_sort_key,
    )

    # Avain: (mittari, aikaleima, lukematyyppi). Uniikkiavain tietokannassa
    # estää päällekkäiset rivit, mutta summataan silti puolustavasti.
    series = defaultdict(
        lambda: {
            "wh_import": 0.0,
            "wh_export": 0.0,
            "wh_prod": 0.0,
            "wh_consumption": 0.0,
        }
    )
    timestamps = set()

    for row in rows:
        serial = (row["meter_serial"] or "").upper()
        reading_type = (row["reading_type"] or "").upper()
        timestamp = row["ts"]
        key = (serial, timestamp, reading_type)
        timestamps.add(timestamp)

        for field in (
            "wh_import",
            "wh_export",
            "wh_prod",
            "wh_consumption",
        ):
            series[key][field] += float(row[field] or 0)

    pv_prod_wh = 0.0
    pv_to_common_wh = 0.0
    pv_to_apartments_wh = 0.0
    pv_export_wh = 0.0
    pv_unallocated_wh = 0.0
    common_grid_wh = 0.0
    apartments_grid_wh = {name: 0.0 for name in apartment_names}
    internal_consumption_wh = sum(
        value["wh_consumption"]
        for (_serial, _timestamp, reading_type), value in series.items()
        if reading_type == "INTERNAL"
    )
    intervals_with_bn02 = 0
    intervals_without_bn02 = 0

    for timestamp in sorted(timestamps):
        pv_key = ("PV_MAIN", timestamp, "INTERNAL")
        common_bn01_key = ("COMMON_MAIN", timestamp, "BN01")
        common_bn02_key = ("COMMON_MAIN", timestamp, "BN02")
        common_bn03_key = ("COMMON_MAIN", timestamp, "BN03")

        pv_wh = series[pv_key]["wh_prod"]
        bn03_export_wh = series[common_bn03_key]["wh_export"]
        common_grid_wh += series[common_bn03_key]["wh_import"]
        pv_prod_wh += pv_wh
        pv_export_wh += bn03_export_wh

        for apartment in apartment_names:
            apartments_grid_wh[apartment] += series[
                (apartment, timestamp, "BN03")
            ]["wh_import"]

        if common_bn02_key not in series:
            # BN02 puuttuu: tunnetaan PV ja lopullinen export, mutta ei jakoa
            # yhteisten tilojen ja asuntojen kesken.
            pv_unallocated_wh += max(pv_wh - bn03_export_wh, 0.0)
            if pv_wh > 0 or bn03_export_wh > 0:
                intervals_without_bn02 += 1
            continue

        intervals_with_bn02 += 1
        available_to_community_wh = series[common_bn02_key]["wh_export"]

        if common_bn01_key in series:
            bn01_import_wh = series[common_bn01_key]["wh_import"]
            bn01_export_wh = series[common_bn01_key]["wh_export"]
            expected_bn02_import_wh = max(
                bn01_import_wh - bn01_export_wh,
                0.0,
            )
            expected_bn02_export_wh = max(
                bn01_export_wh - bn01_import_wh,
                0.0,
            )
            actual_bn02_import_wh = series[common_bn02_key]["wh_import"]

            if (
                abs(actual_bn02_import_wh - expected_bn02_import_wh) > 1.0
                or abs(
                    available_to_community_wh - expected_bn02_export_wh
                ) > 1.0
            ):
                logging.warning(
                    "Sankey netting mismatch at %s: BN01 import/export "
                    "%.1f/%.1f Wh, BN02 import/export %.1f/%.1f Wh",
                    timestamp,
                    bn01_import_wh,
                    bn01_export_wh,
                    actual_bn02_import_wh,
                    available_to_community_wh,
                )

        if available_to_community_wh > pv_wh + 1.0:
            logging.warning(
                "Sankey data mismatch at %s: BN02 production %.1f Wh "
                "exceeds internal PV production %.1f Wh",
                timestamp,
                available_to_community_wh,
                pv_wh,
            )

        if bn03_export_wh > available_to_community_wh + 1.0:
            logging.warning(
                "Sankey data mismatch at %s: BN03 production %.1f Wh "
                "exceeds BN02 production %.1f Wh",
                timestamp,
                bn03_export_wh,
                available_to_community_wh,
            )

        pv_to_common_wh += max(pv_wh - available_to_community_wh, 0.0)
        pv_to_apartments_wh += max(
            available_to_community_wh - bn03_export_wh,
            0.0,
        )

    pv_prod = pv_prod_wh / 1000.0
    pv_common = pv_to_common_wh / 1000.0
    pv_apartments_total = pv_to_apartments_wh / 1000.0
    pv_export = pv_export_wh / 1000.0
    pv_unallocated = pv_unallocated_wh / 1000.0
    common_import = common_grid_wh / 1000.0
    apartments = {
        serial: value / 1000.0
        for serial, value in apartments_grid_wh.items()
    }
    total_apartment_import = sum(apartments.values())
    grid_to_load = common_import + total_apartment_import

    if len(apartment_names) == 24:
        estimated_pv_per_apartment = pv_apartments_total / 24.0
    else:
        estimated_pv_per_apartment = 0.0
        if pv_apartments_total > 0:
            pv_unallocated += pv_apartments_total
            pv_apartments_total = 0.0
            logging.warning(
                "Sankey: equal 1/24 allocation requires 24 active apartments; "
                "found %d",
                len(apartment_names),
            )

    nodes = [
        "PV",
        "Grid",
        "Export",
        "Common",
    ]

    if pv_unallocated > 0:
        nodes.append("CommunityUse")

    nodes += apartment_names

    index = {name: position for position, name in enumerate(nodes)}
    links = []

    # PV -> yhteisten tilojen käyttö BN02-tuotannon jäännöksenä.
    if pv_common > 0:
        links.append(
            {
                "source": index["PV"],
                "target": index["Common"],
                "value": round(pv_common, 3),
            }
        )

    # PV -> asunnot, arvioitu tasajako 1/24 toteutuneesta yhteisöosuudesta.
    if estimated_pv_per_apartment > 0:
        for apartment in apartment_names:
            links.append(
                {
                    "source": index["PV"],
                    "target": index[apartment],
                    "value": round(estimated_pv_per_apartment, 3),
                }
            )

    # PV -> verkkoon myyty todellinen BN03-energia.
    if pv_export > 0:
        links.append(
            {
                "source": index["PV"],
                "target": index["Export"],
                "value": round(pv_export, 3),
            }
        )

    # Vain niiden aikavälien koonti, joilta BN02 puuttuu.
    if pv_unallocated > 0:
        links.append(
            {
                "source": index["PV"],
                "target": index["CommunityUse"],
                "value": round(pv_unallocated, 3),
            }
        )

    # Grid -> yhteiset tilat, lopullinen BN03-import.
    if common_import > 0:
        links.append(
            {
                "source": index["Grid"],
                "target": index["Common"],
                "value": round(common_import, 3),
            }
        )

    # Grid -> asunnot, lopulliset BN03-importit.
    for apartment in apartment_names:
        value = apartments[apartment]

        if value > 0:
            links.append(
                {
                    "source": index["Grid"],
                    "target": index[apartment],
                    "value": round(value, 3),
                }
            )

    meta = {
        "pv_kwh": round(pv_prod, 3),
        "common_load_kwh": round(common_import, 3),
        "apartments_load_kwh": round(total_apartment_import, 3),
        "grid_to_load_kwh": round(grid_to_load, 3),
        "pv_export_kwh": round(pv_export, 3),
        "pv_to_common_kwh": round(pv_common, 3),
        "pv_to_apartments_kwh": round(pv_apartments_total, 3),
        "pv_unallocated_kwh": round(pv_unallocated, 3),
        "internal_consumption_kwh": round(
            internal_consumption_wh / 1000.0,
            3,
        ),
        "allocation_basis": "equal_1_24_estimate",
        "intervals_with_bn02": intervals_with_bn02,
        "intervals_without_bn02": intervals_without_bn02,
    }

    return {
        "nodes": nodes,
        "links": links,
        "meta": meta,
    }


def annual_pv_split(intervals):
    """Do not present partial/invalid annual PV allocations as complete savings."""
    common = apartments = 0.0
    complete = True
    for interval in intervals:
        pv, bn02, bn03 = (interval[key] for key in ("pv", "bn02", "bn03"))
        if pv == 0 and bn03 == 0 and bn02 in (None, 0):
            continue
        if any(value is None for value in (pv, bn02, bn03)) or not 0 <= bn03 <= bn02 <= pv:
            complete = False
            continue
        common += pv - bn02
        apartments += bn02 - bn03
    return {
        "common_kwh": round(common / 1000, 2) if complete else None,
        "apartments_kwh": round(apartments / 1000, 2) if complete else None,
        "complete": complete,
    }


def calculate_annual_totals(start_utc_naive, end_utc_naive):
    """
    Laskee valitun kalenterivuoden Grid-, Export- ja PV-summat.

    Tietokannan arvot ovat Wh-yksikössä. API palauttaa kWh-arvot.
    """

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    try:
        query = """
            SELECT
                COALESCE(SUM(CASE WHEN m.meter_serial = 'COMMON_MAIN'
                    AND ms.reading_type = 'BN03' THEN ms.wh_import ELSE 0 END), 0) AS common_grid_wh,
                COALESCE(SUM(CASE WHEN m.role = 'load' AND m.meter_serial REGEXP '^APT[0-9]+$'
                    AND ms.reading_type = 'BN03' THEN ms.wh_import ELSE 0 END), 0) AS apartments_grid_wh,
                COALESCE(SUM(
                    CASE
                        WHEN m.role = 'load'
                         AND ms.reading_type = 'BN03'
                        THEN ms.wh_import
                        ELSE 0
                    END
                ), 0) AS grid_wh,

                COALESCE(SUM(
                    CASE
                        WHEN m.meter_serial = 'COMMON_MAIN'
                         AND ms.reading_type = 'BN03'
                        THEN ms.wh_export
                        ELSE 0
                    END
                ), 0) AS export_wh,

                COALESCE(SUM(
                    CASE
                        WHEN m.meter_serial = 'PV_MAIN'
                         AND ms.reading_type = 'INTERNAL'
                        THEN ms.wh_prod
                        ELSE 0
                    END
                ), 0) AS pv_wh,

                COALESCE(SUM(
                    CASE
                        WHEN m.role = 'consumption_raw'
                         AND ms.reading_type = 'INTERNAL'
                        THEN ms.wh_consumption
                        ELSE 0
                    END
                ), 0) AS internal_consumption_wh

            FROM measurements ms
            JOIN meters m ON m.id = ms.meter_id
            WHERE ms.ts >= %s
              AND ms.ts < %s;
        """

        cur.execute(query, (start_utc_naive, end_utc_naive))
        row = cur.fetchone() or {}
        # Match PV and common exports by interval before calculating the split.
        cur.execute("""
            SELECT ms.ts,
                SUM(CASE WHEN m.meter_serial = 'PV_MAIN' AND ms.reading_type = 'INTERNAL'
                    THEN ms.wh_prod END) AS pv,
                SUM(CASE WHEN m.meter_serial = 'COMMON_MAIN' AND ms.reading_type = 'BN02'
                    THEN ms.wh_export END) AS bn02,
                SUM(CASE WHEN m.meter_serial = 'COMMON_MAIN' AND ms.reading_type = 'BN03'
                    THEN ms.wh_export END) AS bn03
            FROM measurements ms JOIN meters m ON m.id = ms.meter_id
            WHERE ms.ts >= %s AND ms.ts < %s
              AND m.meter_serial IN ('PV_MAIN', 'COMMON_MAIN')
            GROUP BY ms.ts
        """, (start_utc_naive, end_utc_naive))
        split = annual_pv_split(cur.fetchall())
    finally:
        cur.close()
        conn.close()

    return {
        "common": {
            "grid_kwh": round(float(row.get("common_grid_wh") or 0) / 1000, 2),
            "self_used_pv_kwh": split["common_kwh"],
            "export_kwh": round(float(row.get("export_wh") or 0) / 1000, 2),
        },
        "apartments": {
            "grid_kwh": round(float(row.get("apartments_grid_wh") or 0) / 1000, 2),
            "self_used_pv_kwh": split["apartments_kwh"],
            "export_kwh": 0.0,
        },
        "pv_split_complete": split["complete"],
        "grid_kwh": round(float(row.get("grid_wh") or 0) / 1000.0, 2),
        "export_kwh": round(float(row.get("export_wh") or 0) / 1000.0, 2),
        "pv_kwh": round(float(row.get("pv_wh") or 0) / 1000.0, 2),
        "internal_consumption_kwh": round(
            float(row.get("internal_consumption_wh") or 0) / 1000.0,
            2,
        ),
    }


# -------------------------------------------
# O L E M A S S A   O L E V A T   E N D P O I N T I T
# -------------------------------------------

@app.route("/api/energy", methods=["POST"])
def receive_energy():
    data = request.get_json()

    if not data or "energy_kwh" not in data:
        return jsonify({"error": "Missing energy_kwh"}), 400

    try:
        energy_kwh = float(data["energy_kwh"])
    except (TypeError, ValueError):
        return jsonify({"error": "energy_kwh must be numeric"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO han_energy (energy_kwh) VALUES (%s);",
            (energy_kwh,),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return jsonify({"status": "ok", "energy_kwh": energy_kwh}), 200


@app.route("/api/energy/latest", methods=["GET"])
def latest_energy():
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "SELECT ts, energy_kwh "
            "FROM han_energy "
            "ORDER BY id DESC LIMIT 1;"
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    if not row:
        return jsonify({"error": "No data"}), 404

    ts_utc, energy_kwh = row

    # MySQL-connector palauttaa datetime-arvon ilman aikavyöhykettä.
    if ts_utc.tzinfo is None:
        ts_utc = ts_utc.replace(tzinfo=UTC)

    ts_local = ts_utc.astimezone(HELSINKI_TZ)

    return jsonify(
        {
            "ts": ts_local.isoformat(),
            "energy_kwh": float(energy_kwh),
        }
    ), 200


@app.route("/api/energy/quarter-hour", methods=["GET"])
def energy_quarter_hour():
    """
    Palauttaa kulutuskäyrän varttitunnin tarkkuudella yhdelle päivälle.
    Parametri: ?date=YYYY-MM-DD.
    """

    date_str = request.args.get("date")

    if not date_str:
        return jsonify({"error": "Missing date, use ?date=YYYY-MM-DD"}), 400

    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Invalid date format, use YYYY-MM-DD"}), 400

    day_start_local = datetime(
        year=day.year,
        month=day.month,
        day=day.day,
        tzinfo=HELSINKI_TZ,
    )
    day_end_local = day_start_local + timedelta(days=1)

    day_start_utc_naive = (
        day_start_local.astimezone(UTC).replace(tzinfo=None)
    )
    day_end_utc_naive = (
        day_end_local.astimezone(UTC).replace(tzinfo=None)
    )

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        query = """
            WITH readings AS (
                SELECT
                    ts,
                    energy_kwh,
                    LAG(energy_kwh) OVER (ORDER BY ts) AS prev_energy
                FROM han_energy
                WHERE ts >= %s AND ts < %s
            ),
            deltas AS (
                SELECT
                    ts,
                    energy_kwh - prev_energy AS delta_kwh
                FROM readings
                WHERE prev_energy IS NOT NULL
            )
            SELECT
                FROM_UNIXTIME(
                    FLOOR(UNIX_TIMESTAMP(ts) / 900) * 900
                ) AS t_bin,
                SUM(delta_kwh) AS delta_kwh
            FROM deltas
            GROUP BY t_bin
            ORDER BY t_bin;
        """

        cur.execute(query, (day_start_utc_naive, day_end_utc_naive))
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    result = []

    for t_bin_utc, delta_kwh in rows:
        if delta_kwh is None:
            continue

        if t_bin_utc.tzinfo is None:
            t_bin_utc = t_bin_utc.replace(tzinfo=UTC)

        t_bin_local = t_bin_utc.astimezone(HELSINKI_TZ)

        result.append(
            {
                "time": t_bin_local.isoformat(),
                "delta_kwh": float(delta_kwh),
            }
        )

    return jsonify(result), 200


# -------------------------------------------
# /api/sankey
# -------------------------------------------

@app.route("/api/sankey", methods=["GET"])
def sankey():
    """
    Palauttaa yhden päivän Sankey-datan sekä valitun päivän
    kalenterivuoden Grid-, Export- ja PV-yhteenvedon.

    Parametrit: ?date=YYYY-MM-DD&period=day|year (oletus day).
    """

    period = request.args.get("period", "day")
    if period not in ("day", "year"):
        return jsonify({"error": "Invalid period, use day or year"}), 400
    date_str = request.args.get("date")

    if not date_str:
        return jsonify({"error": "Missing date, use ?date=YYYY-MM-DD"}), 400

    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Invalid date format, use YYYY-MM-DD"}), 400

    # Valittu päivä Helsingin ajassa -> UTC-naive rajat MySQL:lle.
    day_start_local = datetime(
        year=day.year,
        month=day.month,
        day=day.day,
        tzinfo=HELSINKI_TZ,
    )
    day_end_local = day_start_local + timedelta(days=1)

    day_start_utc_naive = (
        day_start_local.astimezone(UTC).replace(tzinfo=None)
    )
    day_end_utc_naive = (
        day_end_local.astimezone(UTC).replace(tzinfo=None)
    )

    # Valitun päivän kalenterivuosi Helsingin ajassa.
    year_start_local = datetime(
        year=day.year,
        month=1,
        day=1,
        tzinfo=HELSINKI_TZ,
    )
    year_end_local = datetime(
        year=day.year + 1,
        month=1,
        day=1,
        tzinfo=HELSINKI_TZ,
    )

    year_start_utc_naive = (
        year_start_local.astimezone(UTC).replace(tzinfo=None)
    )
    year_end_utc_naive = (
        year_end_local.astimezone(UTC).replace(tzinfo=None)
    )

    sankey_data = calculate_sankey_data(
        year_start_utc_naive if period == "year" else day_start_utc_naive,
        year_end_utc_naive if period == "year" else day_end_utc_naive,
    )
    annual_totals = calculate_annual_totals(
        year_start_utc_naive,
        year_end_utc_naive,
    )

    return jsonify(
        {
            "date": date_str,
            "period": period,
            "nodes": sankey_data["nodes"],
            "links": sankey_data["links"],
            "meta": sankey_data["meta"],
            "annual": {
                "year": day.year,
                **annual_totals,
            },
        }
    ), 200


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
