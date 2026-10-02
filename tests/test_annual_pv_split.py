"""Exercise the pure annual allocation without a running Flask/MySQL service."""
import ast
from pathlib import Path
import unittest

source = ast.parse((Path(__file__).resolve().parents[1] / 'api/app.py').read_text())
function = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == 'annual_pv_split')
namespace = {}
exec(compile(ast.Module(body=[function], type_ignores=[]), 'annual_pv_split', 'exec'), namespace)
split = namespace['annual_pv_split']


class AnnualSplitTests(unittest.TestCase):
    def test_interval_allocation(self):
        result = split([dict(pv=10000, bn02=6000, bn03=2000), dict(pv=4000, bn02=3000, bn03=1000)])
        self.assertEqual(result, dict(common_kwh=5, apartments_kwh=6, complete=True))

    def test_partial_year_not_reported_as_complete(self):
        result = split([dict(pv=10000, bn02=6000, bn03=2000), dict(pv=4000, bn02=None, bn03=1000)])
        self.assertIsNone(result['common_kwh'])
        self.assertIsNone(result['apartments_kwh'])
        self.assertFalse(result['complete'])

    def test_night_without_bn02(self):
        self.assertTrue(split([dict(pv=0, bn02=None, bn03=0)])['complete'])

    def test_invalid_balance(self):
        self.assertFalse(split([dict(pv=100, bn02=200, bn03=0)])['complete'])


if __name__ == '__main__':
    unittest.main()
