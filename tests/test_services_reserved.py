import sqlite3
import unittest

from sto_crm.services import reserved_quantity


class TestServicesReserved(unittest.TestCase):
    def test_reserved_quantity_exclude_order(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                number TEXT,
                status TEXT,
                deleted_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                kind TEXT,
                inventory_id INTEGER,
                approval_status TEXT,
                quantity REAL
            )
            """
        )
        # Seed test orders and order items
        conn.execute("INSERT INTO orders (id, number, status, deleted_at) VALUES (1, 'ORD-001', 'approved', NULL)")
        conn.execute("INSERT INTO orders (id, number, status, deleted_at) VALUES (2, 'ORD-002', 'approved', NULL)")
        conn.execute("INSERT INTO order_items (id, order_id, kind, inventory_id, approval_status, quantity) VALUES (1, 1, 'part', 10, 'approved', 5.0)")
        conn.execute("INSERT INTO order_items (id, order_id, kind, inventory_id, approval_status, quantity) VALUES (2, 2, 'part', 10, 'approved', 3.0)")
        
        try:
            self.assertEqual(reserved_quantity(conn, 10), 8.0)
            self.assertEqual(reserved_quantity(conn, 10, exclude_order_id=1), 3.0)
            self.assertEqual(reserved_quantity(conn, 11), 0.0)
        finally:
            conn.close()
