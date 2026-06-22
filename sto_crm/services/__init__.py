"""Transactional operations facade for STO CRM."""

from __future__ import annotations

from .appointments import (
    create_appointment as create_appointment,
    delete_appointment as delete_appointment,
    get_appointment as get_appointment,
    update_appointment as update_appointment,
)
from .customers import (
    create_customer as create_customer,
    delete_customer as delete_customer,
    get_customer as get_customer,
    update_customer as update_customer,
)
from .inventory import (
    apply_inventory_delta as apply_inventory_delta,
    create_inventory as create_inventory,
    delete_inventory as delete_inventory,
    ensure_inventory_available_for_order as ensure_inventory_available_for_order,
    get_inventory as get_inventory,
    part_quantities as part_quantities,
    reserved_quantity as reserved_quantity,
    update_inventory as update_inventory,
)
from .orders import (
    canonical_closed_order as canonical_closed_order,
    closed_item_signature as closed_item_signature,
    closed_order_signature as closed_order_signature,
    closed_signature_number as closed_signature_number,
    compute_closed_at as compute_closed_at,
    create_order as create_order,
    create_order_tx as create_order_tx,
    delete_order as delete_order,
    ensure_closed_order_not_changed as ensure_closed_order_not_changed,
    ensure_order_status_transition as ensure_order_status_transition,
    insert_order_items as insert_order_items,
    list_order_items as list_order_items,
    status_needs_inventory_availability_check as status_needs_inventory_availability_check,
    status_reserves_inventory as status_reserves_inventory,
    update_order as update_order,
)
from .vehicles import (
    create_vehicle as create_vehicle,
    delete_vehicle as delete_vehicle,
    get_vehicle as get_vehicle,
    reconcile_vehicle_mileage_after_order_change as reconcile_vehicle_mileage_after_order_change,
    sync_vehicle_mileage_from_order as sync_vehicle_mileage_from_order,
    update_vehicle as update_vehicle,
    vehicle_order_mileage_source as vehicle_order_mileage_source,
)
