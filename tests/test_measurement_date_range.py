"""Test measurement coverage conversion without a running database."""
import ast
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase, main
from zoneinfo import ZoneInfo


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.closed = False

    def execute(self, query):
        self.query = query

    def fetchone(self):
        return self.row

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, row):
        self.cursor_instance = FakeCursor(row)
        self.closed = False

    def cursor(self, dictionary=False):
        assert dictionary
        return self.cursor_instance

    def close(self):
        self.closed = True


tree = ast.parse((Path(__file__).resolve().parents[1] / "api/app.py").read_text())
functions = {
    node.name: node for node in tree.body
    if isinstance(node, ast.FunctionDef)
    and node.name in {"get_measurement_date_range", "get_energy_date_range"}
}


class MeasurementDateRangeTests(TestCase):
    def call_function(self, row, function_name="get_measurement_date_range"):
        connection = FakeConnection(row)
        namespace = {
            "get_db_connection": lambda: connection,
            "UTC": timezone.utc,
            "HELSINKI_TZ": ZoneInfo("Europe/Helsinki"),
        }
        exec(
            compile(
                ast.Module(body=[functions[function_name]], type_ignores=[]),
                "date_range",
                "exec",
            ),
            namespace,
        )
        return namespace[function_name](), connection

    def test_converts_utc_timestamps_to_helsinki_dates(self):
        result, connection = self.call_function({
            "first_ts": datetime(2025, 8, 31, 21, 0),
            "last_ts": datetime(2026, 9, 30, 20, 0),
        })
        self.assertEqual(result, {
            "start_date": "2025-09-01",
            "end_date": "2026-09-30",
        })
        self.assertIn("MIN(ts)", connection.cursor_instance.query)
        self.assertTrue(connection.cursor_instance.closed)
        self.assertTrue(connection.closed)

    def test_empty_table_returns_null_dates(self):
        result, _ = self.call_function({"first_ts": None, "last_ts": None})
        self.assertEqual(result, {"start_date": None, "end_date": None})

    def test_energy_range_uses_han_energy_table(self):
        result, connection = self.call_function({
            "first_ts": datetime(2025, 1, 1, 0, 0),
            "last_ts": datetime(2025, 1, 2, 0, 0),
        }, "get_energy_date_range")
        self.assertEqual(result, {
            "start_date": "2025-01-01",
            "end_date": "2025-01-02",
        })
        self.assertIn("FROM han_energy", connection.cursor_instance.query)


if __name__ == "__main__":
    main()
