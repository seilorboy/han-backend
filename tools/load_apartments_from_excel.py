import os
import mysql.connector
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# ---------------------------------
# LADATAAN .env -TIEDOSTO
# ---------------------------------

# Etsitään .env projektin juuresta: /han-backend/.env
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(ENV_PATH)

# ---------------------------------
# LUETAAN YMPÄRISTÖMUUTTUJAT
# ---------------------------------

DB_HOST = os.getenv("DB_HOST","localhost") #tässä pitää olla localhost jos aiotaan ajaa suoraan hostilla, muutoin voi olla db
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

if not DB_USER or not DB_PASSWORD or not DB_NAME:
    raise RuntimeError("Ympäristömuuttujat DB_USER, DB_PASSWORD tai DB_NAME puuttuvat .env-tiedostosta!")

EXCEL_PATH = "Valkamakatu.xlsx"
EXCEL_SHEET = "Taul1"
NUM_APARTMENTS = 24


# ---------------------------------
# APUMETODIT
# ---------------------------------

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )


def load_excel(path, sheet_name):
    print(f"Ladataan Excel: {path}")
    df = pd.read_excel(path, sheet_name=sheet_name)
    print(f"Luettu {len(df)} riviä, {len(df.columns)} saraketta.")
    return df


def get_meter_id_for_apartment(cursor, apartment_index):
    meter_serial = f"APT{apartment_index}"
    cursor.execute(
        "SELECT id FROM meters WHERE meter_serial = %s AND role = 'load';",
        (meter_serial,),
    )
    row = cursor.fetchone()
    if not row:
        raise RuntimeError(f"Mittaria {meter_serial} ei löytynyt taulusta 'meters'.")
    return row[0]


def build_inserts_for_apartment(df, apartment_index, meter_id):
    if apartment_index == 1:
        hour_col = "Hour"
        cons_col = "Cons"
    else:
        suffix = f".{apartment_index - 1}"
        hour_col = f"Hour{suffix}"
        cons_col = f"Cons{suffix}"

    if hour_col not in df.columns or cons_col not in df.columns:
        print(f"VAROITUS: Sarakkeet {hour_col} / {cons_col} puuttuvat. Ohitetaan Apartment{apartment_index}.")
        return []

    inserts = []
    for ts, kwh in zip(df[hour_col], df[cons_col]):
        if pd.isna(ts) or pd.isna(kwh):
            continue

        # Muunna datetime-objektiksi
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)

        wh_import = float(kwh) * 1000.0  # kWh → Wh

        inserts.append((meter_id, ts, wh_import, 0.0, 0.0))

    print(f"Apartment{apartment_index}: {len(inserts)} riviä.")
    return inserts


# ---------------------------------
# PÄÄOHJELMA
# ---------------------------------

def main():
    df = load_excel(EXCEL_PATH, EXCEL_SHEET)

    conn = get_db_connection()
    cur = conn.cursor()

    batch = []

    for apt in range(1, NUM_APARTMENTS + 1):
        meter_id = get_meter_id_for_apartment(cur, apt)
        rows = build_inserts_for_apartment(df, apt, meter_id)
        batch.extend(rows)

    print(f"Lisätään yhteensä {len(batch)} mittausta.")

    if batch:
        cur.executemany(
            """
            INSERT INTO measurements (meter_id, ts, wh_import, wh_export, wh_prod)
            VALUES (%s, %s, %s, %s, %s)
            """,
            batch,
        )
        conn.commit()
        print("Data tallennettu onnistuneesti!")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
