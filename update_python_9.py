
with open("/home/zxc/CRM/sto_crm/http_server.py", "r", encoding="utf-8") as f:
    http = f.read()

http = http.replace(
    'import logging; logging.getLogger("sto_crm").error("Unhandled Server Exception", exc_info=True)',
    '''
                import logging
                logging.getLogger("sto_crm").error("Unhandled Server Exception", exc_info=True)'''
)

with open("/home/zxc/CRM/sto_crm/http_server.py", "w", encoding="utf-8") as f:
    f.write(http)

with open("/home/zxc/CRM/sto_crm/services.py", "r", encoding="utf-8") as f:
    srv = f.read()

srv = srv.replace(
    '''from __future__ import annotations
import logging
logger = logging.getLogger("sto_crm")

import sqlite3''',
    '''from __future__ import annotations

import logging
import sqlite3'''
)

srv = srv.replace(    
    '''from .validation import (
    active_appointment_count_for_customer,
    active_appointment_count_for_vehicle,
    active_exists,
    ensure_no_appointment_conflict,
    ensure_unique_active_value,
    generate_order_number,
    item_is_billable,
    normalize_order_money,
    validate_appointment,
    validate_customer,
    validate_inventory,
    validate_order,
    validate_vehicle,
)

''', 
    '''from .validation import (
    active_appointment_count_for_customer,
    active_appointment_count_for_vehicle,
    active_exists,
    ensure_no_appointment_conflict,
    ensure_unique_active_value,
    generate_order_number,
    item_is_billable,
    normalize_order_money,
    validate_appointment,
    validate_customer,
    validate_inventory,
    validate_order,
    validate_vehicle,
)

logger = logging.getLogger("sto_crm")
'''
)

with open("/home/zxc/CRM/sto_crm/services.py", "w", encoding="utf-8") as f:
    f.write(srv)
