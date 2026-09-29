import sys
import types
import unittest
from datetime import datetime
from unittest.mock import Mock

# No live database is needed for mapping and SQL regression tests.
try:
    import mysql.connector
except ImportError:
    mysql = types.ModuleType("mysql")
    mysql.connector = types.ModuleType("mysql.connector")
    sys.modules["mysql"] = mysql
    sys.modules["mysql.connector"] = mysql.connector

import pandas as pd
from tools.import_valkama_interactive import (
    build_common_inserts, build_inserts_for_apartment, build_pv_inserts,
)
from tools.measurement_upsert import upsert_measurement


class ImportTests(unittest.TestCase):
    def test_common_export_and_secondary_header(self):
        frame = pd.DataFrame({
            "a": ["Kiinteistö Hour", "2025-09-01T03:00:00+03:00"],
            "b": ["Cons Käyttö", 1.5], "c": ["Prod Tuotanto", 0.4],
        })
        rows = build_common_inserts(frame, 1, "BN02")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["timestamp"], datetime(2025, 9, 1))
        self.assertEqual(rows[0]["wh_import"], 1500)
        self.assertEqual(rows[1]["wh_export"], 400)
        self.assertEqual(rows[1]["reading_type"], "BN02")
        self.assertNotIn("wh_prod", rows[1])
        self.assertEqual(build_pv_inserts(frame, 2), [])

    def test_apartment_and_internal_pv(self):
        frame = pd.DataFrame({"Hour.1": [datetime(2025, 1, 1)], "Cons.1": [2.0]})
        row = build_inserts_for_apartment(frame, 2, 5, "BN01")[0]
        self.assertEqual((row["reading_type"], row["wh_import"]), ("BN01", 2000))
        pv = build_pv_inserts(frame, 6, "Hour.1", "Cons.1")[0]
        self.assertEqual((pv["reading_type"], pv["wh_prod"]), ("INTERNAL", 2000))

    def test_upsert_preserves_other_channels_and_accepts_zero(self):
        cursor = Mock()
        upsert_measurement(cursor, meter_id=1, timestamp=datetime(2025, 1, 1),
                           reading_type=" bn03 ", wh_export=0)
        sql, params = cursor.execute.call_args.args
        updates = sql.split("ON DUPLICATE KEY UPDATE")[1]
        self.assertIn("wh_export = VALUES(wh_export)", updates)
        self.assertNotIn("wh_import", updates)
        self.assertEqual(params[2], "BN03")
        self.assertEqual(params[4], 0)

    def test_rejects_invalid_energy_and_mapping(self):
        for value in [float("nan"), float("inf"), -1]:
            with self.assertRaises(ValueError):
                upsert_measurement(Mock(), meter_id=1, timestamp=datetime.now(),
                                   reading_type="BN01", wh_import=value)
        with self.assertRaises(ValueError):
            upsert_measurement(Mock(), meter_id=1, timestamp=datetime.now(),
                               reading_type="BN03", wh_prod=10)

    def test_empty_common(self):
        self.assertEqual(build_common_inserts(pd.DataFrame(columns=["a"]), 1), [])


if __name__ == "__main__":
    unittest.main()
