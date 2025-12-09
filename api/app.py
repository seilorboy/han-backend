from flask import Flask, request, jsonify
import mysql.connector
import os
from datetime import datetime, date, timedelta, timezone

UTC = timezone.utc
HELSINKI_TZ = timezone(timedelta(hours=2)) # Helsinki ~ UTC + 2

app = Flask(__name__)

DB_CONFIG = {
    "host": os.environ["DB_HOST"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "database": os.environ["DB_NAME"],
}

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

# Luodaan taulu tarvittaessa
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS han_energy (
            id INT AUTO_INCREMENT PRIMARY KEY,
            ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            energy_kwh DOUBLE NOT NULL
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

@app.route("/api/energy", methods=["POST"])
def receive_energy():
    data = request.get_json()
    if not data or "energy_kwh" not in data:
        return jsonify({"error": "Missing energy_kwh"}), 400

    energy_kwh = float(data["energy_kwh"])

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO han_energy (energy_kwh) VALUES (%s);",
        (energy_kwh,)
    )
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"status": "ok", "energy_kwh": energy_kwh}), 200

@app.route("/api/energy/latest", methods=["GET"])
def latest_energy():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT ts, energy_kwh FROM han_energy ORDER BY id DESC LIMIT 1;")
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({"error": "No data"}), 404

    ts_utc, energy_kwh = row

    # MySQL-connector antama datetime-olio tulkitaa UTC:ksi

    if ts_utc.tzinfo is None:
        ts_utc = ts_utc.replace(tzinfo=UTC)

    ts_local = ts_utc.astimezone(HELSINKI_TZ)

    return jsonify({"ts": ts_local.isoformat(), "energy_kwh": float(energy_kwh)}), 200

@app.route("/api/energy/quarter-hour", methods=["GET"])
def energy_quarter_hour():
    """
    Palauttaa kulutuskayran varttitunnin tarkkuudella yhdelle paivalle.
    Parametri: ?date=YYYY-MM-DD (esim. 2025-12-02)
    Helsingin aikavyöhykkeellä
    """

    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "Missing date, use ?date=YYYY-MM-DD"}), 400

    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Invalid date format, use YYYY-MM-DD"}), 400

    # Tulkitse Helsingin ajan mukaan mutta haetaan kannasta UTC:ssa

    day_start_local = datetime(
        year=day.year,
        month=day.month,
        day=day.day,
        hour=0,
        minute=0,
        second=0,
        tzinfo=HELSINKI_TZ,
    )

    day_end_local = day_start_local + timedelta(days=1)

    day_start_utc = day_start_local.astimezone(UTC)
    day_end_utc = day_end_local.astimezone(UTC)

    # Poistetaan tzinfo koska sitä ei käytetä MySQL:lle

    day_start_utc_naive = day_start_utc.replace(tzinfo=None)
    day_end_utc_naive = day_end_utc.replace(tzinfo=None)

    conn = get_db_connection()
    cur = conn.cursor()

    # 1) Lasketaan perakkäisille mittauksille delta (kWh)
    # 2) Allokoidaan delta sen rivin aikaleimalle (ts)
    # 3) Ryhmitellaan 15 minuutin jaksoihin (900 s) ja summataan deltat
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
            FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(ts) / 900) * 900) AS t_bin,
            SUM(delta_kwh) AS delta_kwh
        FROM deltas
        GROUP BY t_bin
        ORDER BY t_bin;
    """

    cur.execute(query, (day_start_utc_naive, day_end_utc_naive))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = []
    for t_bin_utc, delta_kwh in rows:
        if delta_kwh is None:
            continue

        # t_bin_utc tulee myös MySQL:stä naivena joten merkitään se UTC:ksi

        if t_bin_utc.tzinfo is None:
            t_bin_utc = t_bin_utc.replace(tzinfo=UTC)

        t_bin_local = t_bin_utc.astimezone(HELSINKI_TZ)

        result.append({
            "time": t_bin_local.isoformat(), # paikallinen aika
            "delta_kwh": float(delta_kwh)
        })

    return jsonify(result), 200

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
