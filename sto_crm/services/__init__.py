"""Transactional operations facade for STO CRM."""

from __future__ import annotations

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
