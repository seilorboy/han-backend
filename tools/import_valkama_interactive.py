import os
import glob
from datetime import datetime

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
    PV_MAIN-mittari (kiinteistön ylituotanto / 'Prod Tuotanto').
    HUOM: role on 'load', ei 'prod', koska enum rajoittaa.
    """
    cursor.execute(
        "SELECT id FROM meters WHERE meter_serial = 'PV_MAIN' AND role = 'load';"
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


def build_inserts_for_apartment(df, apartment_index, meter_id):
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

    inserts = []
    for ts, kwh in zip(df[hour_col], df[cons_col]):
        if pd.isna(ts) or pd.isna(kwh):
            continue

        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)

        wh_import = float(kwh) * 1000.0

        inserts.append((meter_id, ts, wh_import, 0.0, 0.0))

    print(f"  Apartment{apartment_index}: {len(inserts)} riviä")
    return inserts


def find_column_by_value(df, text_substring_list):
    """
    Etsii sarakkeen, jonka ENSIMMÄISEN rivin arvo sisältää annetut tekstipätkät
    (case-insensitive, trimattuna).
    Palauttaa sarakkeen nimen tai None.
    """
    for col in df.columns:
        first_val = df[col].iloc[0]
        if isinstance(first_val, str):
            val = first_val.strip().lower()
            if all(sub.lower() in val for sub in text_substring_list):
                return col
    return None


def build_common_inserts(df, meter_id):
    """
    Common (Kiinteistö) -mittaukset: Cons Käyttö.
    Etsii sarakkeet sekä otsikon että ensimmäisen soluarvon perusteella.
    """

    # 1) yritetään otsikon perusteella
    hour_cols = [c for c in df.columns if "Kiinteistö" in c and "Hour" in c]
    cons_cols = [c for c in df.columns if "Cons" in c and "Käyttö" in c]

    # 2) jos ei löydy, etsitään ensimmäisestä rivistä solun arvon perusteella
    if not hour_cols:
        col = find_column_by_value(df, ["Kiinteistö", "Hour"])
        if col:
            hour_cols = [col]

    if not cons_cols:
        col = find_column_by_value(df, ["Cons", "Käyttö"])
        if col:
            cons_cols = [col]

    # 3) jos EI vieläkään löydy, ohitetaan Common
    if not hour_cols or not cons_cols:
        print("VAROITUS: Common-sarakkeita ei löytynyt (ei otsikon eikä soluarvon perusteella). Ohitetaan Common.")
        return []

    hour_col = hour_cols[0]
    cons_col = cons_cols[0]

    print(f"  Common: käytetään sarakkeita '{hour_col}' ja '{cons_col}'")

    inserts = []
    for ts, kwh in zip(df[hour_col], df[cons_col]):
        if pd.isna(ts) or pd.isna(kwh):
            continue

        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)

        wh_import = float(kwh) * 1000.0
        inserts.append((meter_id, ts, wh_import, 0.0, 0.0))

    print(f"  Common: {len(inserts)} riviä")
    return inserts


def build_pv_inserts(df, meter_id):
    """
    PV_MAIN (Prod Tuotanto) -mittaukset.
    Käytetään samaa aikaleimasaraketta kuin Commonissa (Kiinteistö Hour),
    ja sarake 'Prod Tuotanto' tai sen variantti.
    """

    # Aikaleima: sama logiikka kuin commonissa
    hour_cols = [c for c in df.columns if "Kiinteistö" in c and "Hour" in c]
    if not hour_cols:
        col = find_column_by_value(df, ["Kiinteistö", "Hour"])
        if col:
            hour_cols = [col]
    if not hour_cols:
        print("VAROITUS: PV:lle ei löytynyt aikaleimasaraketta (Kiinteistö Hour). Ohitetaan PV.")
        return []

    hour_col = hour_cols[0]

    # Prod Tuotanto -sarake otsikon perusteella
    prod_cols = [c for c in df.columns if "Prod" in c and "Tuotanto" in c]
    if not prod_cols:
        col = find_column_by_value(df, ["Prod", "Tuotanto"])
        if col:
            prod_cols = [col]

    if not prod_cols:
        print("VAROITUS: PV:lle ei löytynyt 'Prod Tuotanto' -sarake. Ohitetaan PV.")
        return []

    prod_col = prod_cols[0]

    print(f"  PV: käytetään sarakkeita '{hour_col}' ja '{prod_col}'")

    inserts = []
    for ts, kwh in zip(df[hour_col], df[prod_col]):
        if pd.isna(ts) or pd.isna(kwh):
            continue

        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)

        wh_prod = float(kwh) * 1000.0  # kWh -> Wh

        # wh_import = 0, wh_export = 0, wh_prod = ylituotanto
        inserts.append((meter_id, ts, 0.0, 0.0, wh_prod))

    print(f"  PV (Prod Tuotanto): {len(inserts)} riviä")
    return inserts


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

    # Lataa Excel
    df = load_excel(excel_path, sheet_name)

    conn = get_db_connection(db_config)
    cur = conn.cursor()

    all_inserts = []

    # --- APARTMENTS ---
    print("\n--- APARTMENTS ---")
    for apt in range(1, num_apartments + 1):
        meter_id, meter_serial = get_meter_id_for_apartment(cur, apt)
        print(f"Apartment{apt} → {meter_serial} (meter_id={meter_id})")
        inserts = build_inserts_for_apartment(df, apt, meter_id)
        all_inserts.extend(inserts)

    # --- COMMON ---
    print("\n--- COMMON ---")
    common_meter_id = get_meter_id_common(cur)
    if common_meter_id:
        common_inserts = build_common_inserts(df, common_meter_id)
        all_inserts.extend(common_inserts)

    # --- PV (Prod Tuotanto) ---
    print("\n--- PV (Prod Tuotanto) ---")
    pv_meter_id = get_meter_id_pv(cur)
    if pv_meter_id:
        pv_inserts = build_pv_inserts(df, pv_meter_id)
        all_inserts.extend(pv_inserts)

    print(f"\nYhteensä lisättäviä mittauksia: {len(all_inserts)}")

    if not all_inserts:
        print("Ei lisättävää.")
        cur.close()
        conn.close()
        return

    confirm = input("Kirjoitetaanko kantaan? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Peruutettu.")
        cur.close()
        conn.close()
        return

    cur.executemany(
        """
        INSERT INTO measurements (meter_id, ts, wh_import, wh_export, wh_prod)
        VALUES (%s, %s, %s, %s, %s);
        """,
        all_inserts
    )
    conn.commit()

    print("\nValmis! Data kirjoitettu measurements-tauluun.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
