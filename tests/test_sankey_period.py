"""Check endpoint period selection without requiring a database connection."""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import Mock
from zoneinfo import ZoneInfo


class SankeyPeriodTests(TestCase):
    def call_route(self, args):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'api/app.py').read_text())
        route = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'sankey')
        route.decorator_list = []
        calculate = Mock(return_value=dict(nodes=[], links=[], meta={}))
        date_range = Mock(return_value=dict(
            start_date='2025-09-01', end_date='2026-09-30'))
        env = dict(request=SimpleNamespace(args=args), jsonify=lambda x: x,
                   datetime=datetime, timedelta=timedelta, UTC=timezone.utc,
                   HELSINKI_TZ=ZoneInfo('Europe/Helsinki'),
                   calculate_sankey_data=calculate,
                   calculate_annual_totals=Mock(return_value={}),
                   get_measurement_date_range=date_range)
        exec(compile(ast.Module(body=[route], type_ignores=[]), 'sankey', 'exec'), env)
        return env['sankey'](), calculate, date_range

    def test_year_uses_helsinki_calendar_boundaries(self):
        (body, status), calc, date_range = self.call_route(dict(date='2025-09-01', period='year'))
        self.assertEqual(status, 200)
        self.assertEqual(body['period'], 'year')
        self.assertEqual(body['available_data'], dict(
            start_date='2025-09-01', end_date='2026-09-30'))
        calc.assert_called_once_with(datetime(2024, 12, 31, 22), datetime(2025, 12, 31, 22))
        date_range.assert_called_once_with()

    def test_day_is_default(self):
        (body, status), calc, _ = self.call_route(dict(date='2025-09-01'))
        self.assertEqual(body['period'], 'day')
        calc.assert_called_once_with(datetime(2025, 8, 31, 21), datetime(2025, 9, 1, 21))

    def test_hour_uses_selected_helsinki_hour(self):
        (body, status), calc, _ = self.call_route(dict(
            date='2025-09-01', period='hour', hour='13'))
        self.assertEqual(status, 200)
        self.assertEqual(body['period'], 'hour')
        self.assertEqual(body['hour'], 13)
        calc.assert_called_once_with(datetime(2025, 9, 1, 10), datetime(2025, 9, 1, 11))

    def test_invalid_hour(self):
        (_, status), calc, date_range = self.call_route(dict(
            date='2025-09-01', period='hour', hour='24'))
        self.assertEqual(status, 400)
        calc.assert_not_called()
        date_range.assert_not_called()

    def test_invalid_period(self):
        (_, status), calc, date_range = self.call_route(dict(date='2025-09-01', period='month'))
        self.assertEqual(status, 400)
        calc.assert_not_called()
        date_range.assert_not_called()


if __name__ == '__main__':
    main()
