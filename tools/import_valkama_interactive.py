import os
import glob
from datetime import datetime, timezone

try:
    from .measurement_upsert import normalize_reading_type, upsert_measurement
except ImportError:
    from measurement_upsert import normalize_reading_type, upsert_measurement

import mysql.connector
import pandas as pd

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


# -------------------------------
# .env / ympäristömuuttujat
# -------------------------------

def load_env():
    """
    Lataa .env-tiedoston jos mahdollista, muuten nojaa valmiisiin env-muuttujiin.
    """
    if load_dotenv is None:
        print("Huom: python-dotenv ei ole asennettu, käytetään suoraan ympäristömuuttujia.")
        return

    script_dir = os.path.dirname(__file__)
    candidates = [
        os.path.join(script_dir, ".env"),
        os.path.join(os.path.dirname(script_dir), ".env"),
        "/app/.env",
        "/han-backend/.env",
    ]

    for path in candidates:
        if os.path.exists(path):
            print(f"Ladataan .env: {path}")
            load_dotenv(path)
            return

    print("Varoitus: .env-tiedostoa ei löytynyt, käytetään suoraan ympäristömuuttujia.")


def get_db_config():
    """
    Lukee DB_HOST, DB_USER, DB_PASSWORD, DB_NAME ympäristöstä.
    """
    db_host = os.getenv("DB_HOST", "db")
    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")

    missing = [name for name, val in [
        ("DB_USER", db_user),
        ("DB_PASSWORD", db_pass),
        ("DB_NAME", db_name),
    ] if not val]

    if missing:
        raise RuntimeError(
            f"Puuttuvia DB-asetuksia: {', '.join(missing)}. "
            "Varmista että .env / environment sisältää nämä."
        )

    print(f"Yhdistetään kantaan: host={db_host}, database={db_name}, user={db_user}")
    return {
        "host": db_host,
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": db_user,
        "password": db_pass,
        "database": db_name,
    }


# -------------------------------
# Excel-valinta
# -------------------------------

def choose_excel_file():
    """
    Kysyy käyttäjältä, mitä Excel-tiedostoa käytetään.
    Listaa nykyisen hakemiston .xlsx-tiedostot ja antaa valita niistä.
    """
    cwd = os.getcwd()
    candidates = sorted(glob.glob(os.path.join(cwd, "*.xlsx")))

    print("\n=== Excel-tiedoston valinta ===")
    if candidates:
        print("Löytyi seuraavat .xlsx-tiedostot:")
        for i, path in enumerate(candidates, start=1):
            print(f"  {i}) {os.path.basename(path)}")
        print("  0) Syötä polku käsin")

        choice = input("Valitse numero [1]: ").strip()
        if choice == "":
            choice = "1"

        if choice == "0":
            manual = input("Anna Excel-tiedoston polku: ").strip()
            return manual

        try:
            idx = int(choice)
            if 1 <= idx <= len(candidates):
                return candidates[idx - 1]
        except ValueError:
            pass

        print("Virheellinen valinta, käytetään ensimmäistä tiedostoa.")
        return candidates[0]
    else:
        print("Nykyisessä hakemistossa ei ole .xlsx-tiedostoja.")
        manual = input("Anna Excel-tiedoston polku: ").strip()
        return manual


# -------------------------------
# DB-apufunktiot
# -------------------------------

def get_db_connection(db_config):
    return mysql.connector.connect(**db_config)


def get_meter_id_for_apartment(cursor, apartment_index):
    """
    Apartment1 -> APT1
    Apartment2 -> APT2
    ...
    """
    meter_serial = f"APT{apartment_index}"
    cursor.execute(
        "SELECT id FROM meters WHERE meter_serial = %s AND role = 'load';",
        (meter_serial,),
    )
    row = cursor.fetchone()
    if not row:
        raise RuntimeError(
            f"Mittaria meter_serial='{meter_serial}' ei löytynyt taulusta 'meters'."
        )
    return row[0], meter_serial


def get_meter_id_common(cursor):
    """
    COMMON_MAIN-mittari (kiinteistön kulutus).
    """
    cursor.execute(
        "SELECT id FROM meters WHERE meter_serial = 'COMMON_MAIN' AND role = 'load';"
    )
    row = cursor.fetchone()
    if not row:
        print("VAROITUS: COMMON_MAIN -mittaria ei löytynyt meters-taulusta.")
        return None
    return row[0]


def get_meter_id_pv(cursor):
    """
    PV_MAIN: sisäisen alamittarin kokonaistuotanto (ei Datahub-ylituotanto).
    """
    cursor.execute(
        "SELECT id FROM meters WHERE meter_serial = 'PV_MAIN' AND role = 'pv_raw';"
    )
    row = cursor.fetchone()
    if not row:
        print("VAROITUS: PV_MAIN -mittaria ei löytynyt meters-taulusta.")
        return None
    return row[0]


# -------------------------------
# Excel → measurements logiikka
# -------------------------------

def load_excel(path, sheet_name):
    print(f"\nLadataan Excel: {path} (sheet='{sheet_name}')")
    df = pd.read_excel(path, sheet_name=sheet_name)
    print(f"Luettu {len(df)} riviä ja {len(df.columns)} saraketta.")
    return df


def build_inserts_for_apartment(df, apartment_index, meter_id, reading_type="BN03"):
    """
    Apartment-sarakkeiden luku (Hour / Cons, Hour.1 / Cons.1, ...).
    """
    if apartment_index == 1:
        hour_col = "Hour"
        cons_col = "Cons"
    else:
        suffix = f".{apartment_index - 1}"
        hour_col = f"Hour{suffix}"
        cons_col = f"Cons{suffix}"

    if hour_col not in df.columns or cons_col not in df.columns:
        print(f"VAROITUS: Apartment{apartment_index} ei löydy ({hour_col}, {cons_col})")
        return []

    return build_series_rows(df, hour_col, cons_col, meter_id, reading_type, "wh_import")


def build_series_rows(df, hour_col, value_col, meter_id, reading_type, channel):
    """Excel timestamps are UTC; explicit offsets are converted to naive UTC."""
    rows = []
    for index, (ts, kwh) in enumerate(zip(df[hour_col], df[value_col])):
        # The legacy workbook may contain a second header in its first row.
        if (index == 0 and isinstance(ts, str)
                and "hour" in ts.casefold()):
            continue
        if pd.isna(ts) or pd.isna(kwh):
            continue
        if not isinstance(ts, (str, datetime)):
            raise ValueError(f"Invalid timestamp in {hour_col}, row {index + 2}: {ts!r}")
        timestamp = pd.Timestamp(ts).to_pydatetime()
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
        rows.append(dict(meter_id=meter_id, timestamp=timestamp,
                         reading_type=reading_type, **{channel: float(kwh) * 1000.0}))
    return rows


def find_column_by_value(df, text_substring_list):
    """
    Etsii sarakkeen, jonka ENSIMMÄISEN rivin arvo sisältää annetut tekstipätkät
    (case-insensitive, trimattuna).
    Palauttaa sarakkeen nimen tai None.
    """
    if df.empty:
        return None
    for col in df.columns:
        first_val = df[col].iloc[0]
        if isinstance(first_val, str):
            val = first_val.strip().lower()
            if all(sub.lower() in val for sub in text_substring_list):
                return col
    return None


def find_column(df, words):
    for col in df.columns:
        if all(word.casefold() in str(col).casefold() for word in words):
            return col
    return find_column_by_value(df, words)


def build_common_inserts(df, meter_id, reading_type="BN03"):
    """Datahub consumption and surplus both belong to COMMON_MAIN."""
    hour = find_column(df, ["Kiinteistö", "Hour"])
    if hour is None:
        print("VAROITUS: Kiinteistön aikaleimasarake puuttuu. Ohitetaan Common.")
        return []
    rows = []
    for words, channel in [(["Cons", "Käyttö"], "wh_import"),
                           (["Prod", "Tuotanto"], "wh_export")]:
        column = find_column(df, words)
        if column is not None:
            rows.extend(build_series_rows(df, hour, column, meter_id, reading_type, channel))
    return rows


def build_pv_inserts(df, meter_id, hour_col=None, production_col=None):
    """Only an explicitly selected internal submeter column is gross PV."""
    if hour_col is None or production_col is None:
        return []
    return build_series_rows(df, hour_col, production_col, meter_id, "INTERNAL", "wh_prod")


# -------------------------------
# Pääohjelma
# -------------------------------

def main():
    load_env()
    db_config = get_db_config()

    excel_path = choose_excel_file()
    sheet_name = input("Anna Excel-välilehden nimi [Taul1]: ").strip() or "Taul1"

    num_apartments_str = input("Kuinka monta asuntoa (Apartment1..ApartmentN) [24]: ").strip()
    num_apartments = int(num_apartments_str) if num_apartments_str else 24

    if num_apartments < 1:
        raise ValueError("Asuntojen lukumäärän on oltava positiivinen")
    reading_type = normalize_reading_type(
        input("Datahub-sarjatyyppi [BN03] (BN01/BN02/BN03): ").strip() or "BN03"
    )
    if reading_type == "INTERNAL":
        raise ValueError("Asuntojen ja kiinteistön Datahub-sarjan on oltava BN01, BN02 tai BN03")
    df = load_excel(excel_path, sheet_name)
    print("Aikaleimat tulkitaan UTC-ajaksi. Aikavyöhykkeen sisältävät ajat muunnetaan UTC:ksi.")
    print("Prod Tuotanto tuodaan COMMON_MAIN-mittarin verkkovientinä.")
    pv_column = input("Sisäisen PV-alamittarin tuotantosarake (tyhjä = ohita): ").strip()
    pv_hour = input("Sisäisen PV-alamittarin aikaleimasarake: ").strip() if pv_column else None

    conn = get_db_connection(db_config)
    cur = conn.cursor()
    try:
        rows = []
        for apt in range(1, num_apartments + 1):
            meter_id, _ = get_meter_id_for_apartment(cur, apt)
            rows.extend(build_inserts_for_apartment(df, apt, meter_id, reading_type))
        common_id = get_meter_id_common(cur)
        if common_id is not None:
            rows.extend(build_common_inserts(df, common_id, reading_type))
        if pv_column:
            pv_id = get_meter_id_pv(cur)
            if pv_id is None:
                raise RuntimeError("PV_MAIN-mittari roolilla pv_raw puuttuu")
            rows.extend(build_pv_inserts(df, pv_id, pv_hour, pv_column))
        print(f"Lisättäviä/päivitettäviä arvoja: {len(rows)}; Datahub-sarja: {reading_type}")
        if not rows or input("Kirjoitetaanko kantaan? [y/N]: ").strip().lower() != "y":
            print("Ei kirjoitettu.")
            return
        for row in rows:
            upsert_measurement(cur, **row)
        conn.commit()
        print("Valmis! Mittaukset tallennettu.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
