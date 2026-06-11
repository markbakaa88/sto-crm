import pytest
import sqlite3
from sto_crm.validation import validate_customer, validate_vehicle


def test_validate_customer_missing_name():
    with pytest.raises(ValueError, match="имя клиента"):
        validate_customer({})


def test_validate_customer_invalid_channel():
    with pytest.raises(ValueError, match="канал связи"):
        validate_customer({"name": "Test", "preferred_channel": "pigeon"})


def test_validate_customer_invalid_email():
    with pytest.raises(ValueError, match="email"):
        validate_customer({"name": "Test", "email": "not-an-email"})


def test_validate_vehicle_missing_customer():
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError, match="Выберите действующего клиента"):
            validate_vehicle(conn, {})
    finally:
        conn.close()
