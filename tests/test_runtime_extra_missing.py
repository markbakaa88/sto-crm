import unittest
from pathlib import Path

from sto_crm.runtime import csv_cell, ensure_private_file_created


class TestRuntimeExtraMissing(unittest.TestCase):
    def test_ensure_private_file_created_symlink(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            real_file = Path(tmpdir) / "real.txt"
            real_file.touch()
            sym_file = Path(tmpdir) / "sym.txt"
            os.symlink(real_file, sym_file)
            with self.assertRaises(OSError) as ctx:
                ensure_private_file_created(sym_file)
            self.assertIn(
                "Файл не может быть символической ссылкой", str(ctx.exception)
            )

    def test_csv_cell_float_or_int(self):
        self.assertEqual(csv_cell(123), 123)
        self.assertEqual(csv_cell(45.67), 45.67)
