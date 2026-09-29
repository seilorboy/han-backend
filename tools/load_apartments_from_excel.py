"""Import apartment Datahub series from the legacy Hour/Cons Excel layout."""

import argparse

try:
    from .import_valkama_interactive import (
        build_inserts_for_apartment, get_db_config, get_db_connection,
        get_meter_id_for_apartment, load_env, load_excel,
    )
    from .measurement_upsert import upsert_measurement
except ImportError:
    from import_valkama_interactive import (
        build_inserts_for_apartment, get_db_config, get_db_connection,
        get_meter_id_for_apartment, load_env, load_excel,
    )
    from measurement_upsert import upsert_measurement


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="Valkamakatu.xlsx")
    parser.add_argument("--sheet", default="Taul1")
    parser.add_argument("--apartments", type=int, default=24)
    parser.add_argument("--reading-type", type=str.upper, choices=("BN01", "BN02", "BN03"), default="BN03")
    args = parser.parse_args()
    if args.apartments < 1:
        parser.error("--apartments must be positive")
    load_env()
    config = get_db_config()
    df = load_excel(args.path, args.sheet)
    print(f"Tuodaan {args.reading_type}; aikaleimat tulkitaan UTC-ajaksi.")
    conn = get_db_connection(config)
    cur = conn.cursor()
    try:
        count = 0
        for apt in range(1, args.apartments + 1):
            meter_id, _ = get_meter_id_for_apartment(cur, apt)
            rows = build_inserts_for_apartment(df, apt, meter_id, args.reading_type)
            for row in rows:
                upsert_measurement(cur, **row)
            count += len(rows)
        conn.commit()
        print(f"Tallennettu {count} mittausta ({args.reading_type}).")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
