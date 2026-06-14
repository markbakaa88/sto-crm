import tempfile
import time
import unittest
from pathlib import Path

from sto_crm import runtime as _runtime
from sto_crm.database import init_db
from sto_crm.export import bootstrap_payload
from sto_crm.runtime import Runtime


class TestExportExtra(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.runtime_db = Path(self.tmpdir.name) / "test_export_extra.sqlite3"
        self.orig_runtime = _runtime.RUNTIME
        _runtime.RUNTIME = Runtime(
            db_path=self.runtime_db,
            start_time=time.time(),
            csrf_token="test_csrf",
            access_token="test_access",
            bootstrap_token="test_bootstrap",
        )
        init_db(seed_demo=True)

    def tearDown(self) -> None:
        _runtime.RUNTIME = self.orig_runtime
        self.tmpdir.cleanup()

    def test_bootstrap_payload_invalid_status(self):
        with self.assertRaises(ValueError) as ctx:
            bootstrap_payload(status="invalid_status_val")
        self.assertEqual(str(ctx.exception), "Некорректный статус заказа.")

    def test_csv_cell_escapes_formula_prefixes(self):
        from sto_crm.runtime import csv_cell
        self.assertEqual(csv_cell("=1+2"), "'=1+2")
        self.assertEqual(csv_cell("+79991112233"), "'+79991112233")
        self.assertEqual(csv_cell("-50"), "'-50")
        self.assertEqual(csv_cell("@username"), "'@username")
        self.assertEqual(csv_cell("|cmd"), "'|cmd")
        self.assertEqual(csv_cell("%50"), "'%50")
        self.assertEqual(csv_cell("normal text"), "normal text")
        self.assertEqual(csv_cell(123), 123)
        self.assertEqual(csv_cell(None), "")

