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

    def test_csv_export_returns_generator_and_streams_correctly(self):
        from sto_crm.export import csv_export
        import types

        filename, content_gen = csv_export("customers")
        self.assertEqual(filename, "customers.csv")
        self.assertIsInstance(content_gen, types.GeneratorType)

        chunks = list(content_gen)
        self.assertTrue(len(chunks) > 0)
        self.assertTrue(chunks[0].startswith("\ufeff"))
        full_content = "".join(chunks)
        self.assertIn("id;name;phone;email;source;preferred_channel;reminder_consent;vehicles_count;orders_count;notes", full_content)

    def test_csv_export_orders_streams_totals_and_items(self):
        from sto_crm.export import csv_export
        filename, content_gen = csv_export("orders")
        self.assertEqual(filename, "orders.csv")
        full_content = "".join(content_gen)
        self.assertIn("id;number;status;customer_name;vehicle_plate;vehicle_make;vehicle_model;authorized_by;authorized_at;follow_up_at;total;paid;due;created_at;updated_at", full_content)

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
