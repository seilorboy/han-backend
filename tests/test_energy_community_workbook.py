import unittest
from datetime import datetime

from tools.import_energy_community_workbook import (
    Interval,
    database_rows,
    local_to_utc_naive,
)


class EnergyCommunityWorkbookTests(unittest.TestCase):
    def test_helsinki_timestamp_conversion_and_ambiguous_hour(self):
        self.assertEqual(
            local_to_utc_naive(datetime(2025, 9, 1, 0)),
            datetime(2025, 8, 31, 21),
        )
        ambiguous = datetime(2025, 10, 26, 3)
        self.assertIsNone(local_to_utc_naive(ambiguous))
        self.assertEqual(
            local_to_utc_naive(ambiguous, "first"),
            datetime(2025, 10, 26, 0),
        )
        self.assertEqual(
            local_to_utc_naive(ambiguous, "second"),
            datetime(2025, 10, 26, 1),
        )

    def test_nonexistent_spring_hour_is_rejected(self):
        with self.assertRaises(ValueError):
            local_to_utc_naive(datetime(2026, 3, 29, 3))

    def test_interval_creates_complete_meter_series(self):
        interval = Interval(
            timestamp=datetime(2025, 8, 31, 21),
            pv_kwh=10,
            common_bn01_import_kwh=2,
            common_bn01_export_kwh=8,
            common_bn02_import_kwh=1,
            common_bn02_export_kwh=7,
            common_bn03_import_kwh=1,
            common_bn03_export_kwh=3,
            apartment_bn01_kwh=tuple(range(1, 25)),
            apartment_bn03_kwh=tuple(value / 2 for value in range(1, 25)),
        )
        meter_ids = {"PV_MAIN": 1, "COMMON_MAIN": 2}
        meter_ids.update({f"APT{i}": i + 2 for i in range(1, 25)})
        rows = list(database_rows([interval], meter_ids))
        self.assertEqual(len(rows), 76)
        self.assertEqual(rows[0][2:7], ("INTERNAL", 0.0, 0.0, 10000, 0.0))
        apartment_one = [row for row in rows if row[0] == 3]
        self.assertEqual([row[2] for row in apartment_one], ["BN01", "BN02", "BN03"])
        self.assertEqual([row[3] for row in apartment_one], [1000, 1000, 500])


if __name__ == "__main__":
    unittest.main()
