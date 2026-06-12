import time
import unittest
from pathlib import Path

import sto_crm
from sto_crm.seed import seed_demo_data


class TestSeed(unittest.TestCase):
    def test_seed_demo_data(self):
        db_path = Path("test_seed_demo_unittest.sqlite3")
        try:
            sto_crm.RUNTIME = sto_crm.Runtime(
                db_path,
                time.time(),
                "csrftoken",
                "accesstoken",
                "bootstraptoken",
            )
            sto_crm.init_db()
            seed_demo_data()
            with sto_crm.db() as conn:
                count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
                self.assertGreater(count, 0)
        finally:
            if db_path.exists():
                try:
                    db_path.unlink()
                except OSError:
                    pass
