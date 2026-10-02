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
        env = dict(request=SimpleNamespace(args=args), jsonify=lambda x: x,
                   datetime=datetime, timedelta=timedelta, UTC=timezone.utc,
                   HELSINKI_TZ=ZoneInfo('Europe/Helsinki'),
                   calculate_sankey_data=calculate, calculate_annual_totals=Mock(return_value={}))
        exec(compile(ast.Module(body=[route], type_ignores=[]), 'sankey', 'exec'), env)
        return env['sankey'](), calculate

    def test_year_uses_helsinki_calendar_boundaries(self):
        (body, status), calc = self.call_route(dict(date='2025-09-01', period='year'))
        self.assertEqual(status, 200)
        self.assertEqual(body['period'], 'year')
        calc.assert_called_once_with(datetime(2024, 12, 31, 22), datetime(2025, 12, 31, 22))

    def test_day_is_default(self):
        (body, status), calc = self.call_route(dict(date='2025-09-01'))
        self.assertEqual(body['period'], 'day')
        calc.assert_called_once_with(datetime(2025, 8, 31, 21), datetime(2025, 9, 1, 21))

    def test_invalid_period(self):
        (_, status), calc = self.call_route(dict(date='2025-09-01', period='month'))
        self.assertEqual(status, 400)
        calc.assert_not_called()


if __name__ == '__main__':
    main()
