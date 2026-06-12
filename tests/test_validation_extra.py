import unittest
import sqlite3
from sto_crm.validation import validate_customer, validate_vehicle

class TestValidationExtra(unittest.TestCase):
    def test_validate_customer_missing_name(self):
        with self.assertRaisesRegex(ValueError, "имя клиента"):
            validate_customer({})

    def test_validate_customer_invalid_channel(self):
        with self.assertRaisesRegex(ValueError, "канал связи"):
            validate_customer({"name": "Test", "preferred_channel": "pigeon"})

    def test_validate_customer_invalid_email(self):
        with self.assertRaisesRegex(ValueError, "email"):
            validate_customer({"name": "Test", "email": "not-an-email"})

    def test_validate_vehicle_missing_customer(self):
        conn = sqlite3.connect(":memory:")
        try:
            with self.assertRaisesRegex(ValueError, "Выберите действующего клиента"):
                validate_vehicle(conn, {})
        finally:
            conn.close()
