import unittest
from datetime import datetime
from unittest.mock import Mock
from tools.generate_bn02_test_data import build_rows, undo


class SyntheticSeriesTests(unittest.TestCase):
    def setUp(self):
        self.meters = [dict(id=1, meter_serial="PV_MAIN", role="pv_raw", active=1),
                       dict(id=2, meter_serial="COMMON_MAIN", role="load", active=1)]
        self.meters += [dict(id=i+2, meter_serial=f"APT{i}", role="load", active=1) for i in range(1, 25)]
        self.source = [dict(meter_id=m['id'], ts=datetime(2025, 9, 1),
                            reading_type="INTERNAL" if m['id'] == 1 else "BN03",
                            wh_import=100, wh_export=200 if m['id'] == 2 else 0,
                            wh_prod=2600 if m['id'] == 1 else 0, wh_consumption=0)
                       for m in self.meters]

    def test_equal_allocation_and_sankey_balance(self):
        rows = build_rows(self.meters, self.source)
        self.assertEqual(len(rows), 25)
        common, *apartments = rows
        self.assertEqual(common[4], 2600)
        self.assertTrue(all(row[3] == 200 for row in apartments))
        # Same formulas as Sankey: common use = PV - BN02 export;
        # apartment use = BN02 export - BN03 export.
        self.assertEqual(2600 - common[4], 0)
        self.assertEqual(common[4] - 200, 24 * 100)
        self.assertTrue(all(row[2] == "BN02" and row[0] != 1 for row in rows))

    def test_missing_source_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing"):
            build_rows(self.meters, self.source[:-1])

    def test_existing_bn02_rejected(self):
        self.source.append(dict(self.source[1], reading_type="BN02"))
        with self.assertRaisesRegex(ValueError, "already exists"):
            build_rows(self.meters, self.source)

    def test_negative_allocation_rejected(self):
        self.source[1]['wh_export'] = 3000
        with self.assertRaisesRegex(ValueError, "exceeds"):
            build_rows(self.meters, self.source)

    def test_undo_refuses_modified_rows(self):
        cursor = Mock()
        row = list(build_rows(self.meters, self.source)[0])
        saved = row.copy()
        saved[1] = saved[1].isoformat()
        row[3] += 1
        cursor.fetchone.return_value = tuple(row)
        with self.assertRaisesRegex(ValueError, "changed"):
            undo(cursor, {'database': 'test', 'rows': [{'id': 123, 'values': saved}]}, 'test')
        self.assertEqual(cursor.execute.call_count, 1)


if __name__ == '__main__':
    unittest.main()
