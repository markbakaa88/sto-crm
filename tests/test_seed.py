import pytest
import sto_crm
from sto_crm.seed import seed_demo_data

def test_seed_demo_data(tmp_path):
    import time
    from pathlib import Path
    sto_crm.RUNTIME = sto_crm.Runtime(
        Path(tmp_path) / "test_seed.sqlite3",
        time.time(),
        "csrftoken",
        "accesstoken",
        "bootstraptoken"
    )
    sto_crm.init_db()
    seed_demo_data()
    # verify
    with sto_crm.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] > 0
