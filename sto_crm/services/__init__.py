"""Transactional operations facade for STO CRM."""

from __future__ import annotations

import logging
import sys
import types
from typing import Any

from sto_crm import config as _config
from sto_crm import database as _database
from sto_crm import runtime as _runtime
from sto_crm import validation as _validation

# Legacy helper imports for backwards compatibility with tests and outer layers
from sto_crm.config import (
    APPOINTMENT_ACTIVE_STATUSES as APPOINTMENT_ACTIVE_STATUSES,
)
from sto_crm.config import (
    CONSUMING_STATUSES as CONSUMING_STATUSES,
)
from sto_crm.config import (
    ORDER_STATUS_TRANSITIONS as ORDER_STATUS_TRANSITIONS,
)
from sto_crm.database import (
    RetryingConnection as RetryingConnection,
)
from sto_crm.database import (
    write_db as write_db,
)
from sto_crm.runtime import (
    now_iso as now_iso,
)
from sto_crm.runtime import (
    parse_float as parse_float,
)
from sto_crm.runtime import (
    parse_int as parse_int,
)
from sto_crm.validation import (
    active_appointment_count_for_customer as active_appointment_count_for_customer,
)
from sto_crm.validation import (
    active_appointment_count_for_vehicle as active_appointment_count_for_vehicle,
)
from sto_crm.validation import (
    active_exists as active_exists,
)
from sto_crm.validation import (
    ensure_no_appointment_conflict as ensure_no_appointment_conflict,
)
from sto_crm.validation import (
    ensure_unique_active_value as ensure_unique_active_value,
)
from sto_crm.validation import (
    generate_order_number as generate_order_number,
)
from sto_crm.validation import (
    item_is_billable as item_is_billable,
)
from sto_crm.validation import (
    normalize_order_money as normalize_order_money,
)
from sto_crm.validation import (
    validate_appointment as validate_appointment,
)
from sto_crm.validation import (
    validate_customer as validate_customer,
)
from sto_crm.validation import (
    validate_inventory as validate_inventory,
)
from sto_crm.validation import (
    validate_order as validate_order,
)
from sto_crm.validation import (
    validate_vehicle as validate_vehicle,
)

# For proxying setattr/delattr to submodules
from . import appointments as _appointments
from . import customers as _customers
from . import inventory as _inventory
from . import orders as _orders
from . import vehicles as _vehicles
from .appointments import (
    create_appointment as create_appointment,
)
from .appointments import (
    delete_appointment as delete_appointment,
)
from .appointments import (
    get_appointment as get_appointment,
)
from .appointments import (
    update_appointment as update_appointment,
)
from .customers import (
    create_customer as create_customer,
)
from .customers import (
    delete_customer as delete_customer,
)
from .customers import (
    get_customer as get_customer,
)
from .customers import (
    update_customer as update_customer,
)
from .inventory import (
    apply_inventory_delta as apply_inventory_delta,
)
from .inventory import (
    create_inventory as create_inventory,
)
from .inventory import (
    delete_inventory as delete_inventory,
)
from .inventory import (
    ensure_inventory_available_for_order as ensure_inventory_available_for_order,
)
from .inventory import (
    get_inventory as get_inventory,
)
from .inventory import (
    part_quantities as part_quantities,
)
from .inventory import (
    reserved_quantity as reserved_quantity,
)
from .inventory import (
    update_inventory as update_inventory,
)
from .orders import (
    canonical_closed_order as canonical_closed_order,
)
from .orders import (
    closed_item_signature as closed_item_signature,
)
from .orders import (
    closed_order_signature as closed_order_signature,
)
from .orders import (
    closed_signature_number as closed_signature_number,
)
from .orders import (
    compute_closed_at as compute_closed_at,
)
from .orders import (
    create_order as create_order,
)
from .orders import (
    create_order_tx as create_order_tx,
)
from .orders import (
    delete_order as delete_order,
)
from .orders import (
    ensure_closed_order_not_changed as ensure_closed_order_not_changed,
)
from .orders import (
    ensure_order_status_transition as ensure_order_status_transition,
)
from .orders import (
    insert_order_items as insert_order_items,
)
from .orders import (
    list_order_items as list_order_items,
)
from .orders import (
    status_needs_inventory_availability_check as status_needs_inventory_availability_check,
)
from .orders import (
    status_reserves_inventory as status_reserves_inventory,
)
from .orders import (
    update_order as update_order,
)
from .vehicles import (
    create_vehicle as create_vehicle,
)
from .vehicles import (
    delete_vehicle as delete_vehicle,
)
from .vehicles import (
    get_vehicle as get_vehicle,
)
from .vehicles import (
    reconcile_vehicle_mileage_after_order_change as reconcile_vehicle_mileage_after_order_change,
)
from .vehicles import (
    sync_vehicle_mileage_from_order as sync_vehicle_mileage_from_order,
)
from .vehicles import (
    update_vehicle as update_vehicle,
)
from .vehicles import (
    vehicle_order_mileage_source as vehicle_order_mileage_source,
)

logger = logging.getLogger("sto_crm")


class _ServicesFacade(types.ModuleType):
    """Facade module proxy that propagates monkeypatching/mocking to submodules."""

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "_originals" and name not in self.__dict__.setdefault("_originals", {}):
            orig = None
            # Find the original value to preserve it for cleanup
            for module in (_appointments, _customers, _inventory, _orders, _vehicles, _validation, _database, _runtime, _config):
                if hasattr(module, name):
                    orig = getattr(module, name)
                    break
            self.__dict__["_originals"][name] = orig

        # Route assignments to submodules to sync mock overrides
        for module in (_appointments, _customers, _inventory, _orders, _vehicles, _validation, _database, _runtime, _config):
            if hasattr(module, name):
                setattr(module, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        originals = self.__dict__.setdefault("_originals", {})
        if name in originals:
            orig_val = originals[name]
            for module in (_appointments, _appointments, _customers, _inventory, _orders, _vehicles, _validation, _database, _runtime, _config):
                if hasattr(module, name):
                    if orig_val is None:
                        try:
                            delattr(module, name)
                        except AttributeError:
                            pass
                    else:
                        setattr(module, name, orig_val)
            del originals[name]
        try:
            super().__delattr__(name)
        except AttributeError:
            pass


sys.modules[__name__].__class__ = _ServicesFacade
