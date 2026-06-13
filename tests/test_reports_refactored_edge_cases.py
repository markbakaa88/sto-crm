import unittest
from datetime import datetime, timedelta

from sto_crm.reports import build_reports, format_vehicle_text, order_vehicle_text


class TestReportsRefactoredEdgeCases(unittest.TestCase):
    def test_format_vehicle_text(self):
        # Test basic format
        self.assertEqual(format_vehicle_text("Toyota", "Camry", 2020, "A123BC77"), "Toyota Camry 2020 A123BC77")
        # Test None and empty string values
        self.assertEqual(format_vehicle_text("Toyota", "", None, "A123BC77"), "Toyota A123BC77")
        # Test only spaces
        self.assertEqual(format_vehicle_text("  Toyota  ", " ", None, " A123BC77 "), "Toyota A123BC77")
        # Test all empty/None values
        self.assertEqual(format_vehicle_text(None, "", "  ", None), "")

    def test_order_vehicle_text(self):
        order = {
            "vehicle_make": "Ford",
            "vehicle_model": "Focus",
            "vehicle_year": 2015,
            "vehicle_plate": "X777XX77"
        }
        self.assertEqual(order_vehicle_text(order), "Ford Focus 2015 X777XX77")

    def test_build_reports_empty_inputs(self):
        # Empty list elements shouldn't blow up and return default valid values
        reports = build_reports(orders=[], inventory=[], vehicles=[], appointments=[])
        self.assertEqual(reports["orders_total"], 0)
        self.assertEqual(reports["active_orders"], 0)
        self.assertEqual(reports["revenue_month"], 0.0)
        self.assertEqual(reports["margin_percent_month"], 0.0)
        self.assertEqual(reports["conversion_rate"], 0.0)
        self.assertEqual(reports["business_health_score"], 100)
        self.assertEqual(reports["business_health_label"], "Отлично")

    def test_build_reports_zero_division_margin_percent(self):
        now = datetime.now()
        month_prefix = now.strftime("%Y-%m")
        # Orders closed in current month with total = 0 and subtotal = 0 (and discount = 0)
        orders = [
            {
                "id": 1,
                "status": "closed",
                "closed_at": f"{month_prefix}-05T12:00",
                "total": "0.0",
                "subtotal": "0.0",
                "discount": "0.0",
                "margin": "100.0"
            }
        ]
        # Should not raise ZeroDivisionError and should return 0.0 margin
        reports = build_reports(orders=orders, inventory=[], vehicles=[], appointments=[])
        self.assertEqual(reports["margin_percent_month"], 0.0)

        # Orders closed in current month with total = 0 and subtotal - discount very close to zero
        orders_tiny = [
            {
                "id": 1,
                "status": "closed",
                "closed_at": f"{month_prefix}-05T12:00",
                "total": "0.0",
                "subtotal": "0.0000000000001",
                "discount": "0.0",
                "margin": "100.0"
            }
        ]
        reports_tiny = build_reports(orders=orders_tiny, inventory=[], vehicles=[], appointments=[])
        self.assertEqual(reports_tiny["margin_percent_month"], 0.0)

    def test_build_reports_timezone_aware_parsing(self):
        now = datetime.now()
        month_prefix = now.strftime("%Y-%m")
        # Testing parsing of promised_at and follow_up_at with timezone tokens
        # closed_at with +03:00 timezone
        orders = [
            {
                "id": 1,
                "status": "closed",
                "closed_at": f"{month_prefix}-05T12:00:00+03:00",
                "total": "100.0",
                "subtotal": "100.0",
                "discount": "0.0",
                "margin": "50.0"
            }
        ]
        reports = build_reports(orders=orders, inventory=[], vehicles=[], appointments=[])
        # Verify that closed_at with timezone is parsed and matched to month_closed
        self.assertEqual(reports["revenue_month"], 100.0)
        self.assertEqual(reports["margin_percent_month"], 50.0)

    def test_build_reports_overdue_promised_dates(self):
        # We set an active order promised in the past
        now = datetime.now()
        past_time = (now - timedelta(days=2)).isoformat()
        orders = [
            {
                "id": 1,
                "status": "in_progress",
                "promised_at": past_time,
                "due": "500.0",
                "total": "500.0",
                "priority": "high"
            }
        ]
        reports = build_reports(orders=orders, inventory=[], vehicles=[], appointments=[])
        self.assertEqual(reports["overdue_orders_count"], 1)
        self.assertEqual(len(reports["overdue_orders"]), 1)
        self.assertEqual(reports["overdue_orders"][0]["id"], 1)

    def test_build_reports_appointments_today_upcoming(self):
        now = datetime.now()
        today_date_str = now.date().isoformat()
        tomorrow_date_str = (now.date() + timedelta(days=1)).isoformat()
        
        appointments = [
            {
                "id": 1,
                "status": "scheduled",
                "scheduled_at": f"{today_date_str}T11:00",
                "customer_name": "John",
                "vehicle_make": "Tesla"
            },
            {
                "id": 2,
                "status": "confirmed",
                "scheduled_at": f"{tomorrow_date_str}T14:00",
                "customer_name": "Alice",
                "vehicle_make": "BMW"
            },
            {
                "id": 3,
                "status": "cancelled", # should be ignored because status is not active
                "scheduled_at": f"{today_date_str}T10:00",
                "customer_name": "Bob"
            }
        ]
        
        reports = build_reports(orders=[], inventory=[], vehicles=[], appointments=appointments)
        self.assertEqual(reports["appointments_today_count"], 1)
        self.assertEqual(reports["appointments_upcoming_count"], 2) # today and tomorrow are both >= today
        self.assertEqual(reports["appointments_today"][0]["id"], 1)
        self.assertEqual(reports["appointments_upcoming"][1]["id"], 2)

    def test_build_reports_service_reminders_date_parsing_edge_cases(self):
        now = datetime.now()
        vehicles = [
            {
                "id": 1,
                "make": "Audi",
                "customer_reminder_consent": 1,
                "customer_preferred_channel": "sms",
                "next_service_at": (now.date() + timedelta(days=5)).isoformat() + "T12:00:00.000Z", # complex format
                "next_service_mileage": 0,
                "mileage": 0
            },
            {
                "id": 2,
                "make": "Opel",
                "customer_reminder_consent": 1,
                "customer_preferred_channel": "none", # should be skipped because of preferred channel
                "next_service_at": (now.date() + timedelta(days=5)).isoformat(),
                "next_service_mileage": 0,
                "mileage": 0
            },
            {
                "id": 3,
                "make": "Peugeot",
                "customer_reminder_consent": 0, # should be skipped because of no consent
                "next_service_at": (now.date() + timedelta(days=5)).isoformat(),
                "next_service_mileage": 0,
                "mileage": 0
            }
        ]
        reports = build_reports(orders=[], inventory=[], vehicles=vehicles, appointments=[])
        self.assertEqual(len(reports["service_reminders"]), 1)
        self.assertEqual(reports["service_reminders"][0]["id"], 1)
