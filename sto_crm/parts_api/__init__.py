"""Abstract Base Class for all outer auto-parts supplier API adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypedDict


class PartSearchResult(TypedDict):
    oem: str
    brand: str
    name: str  # part description
    price: float
    stock: int
    delivery_days: int
    supplier: str  # 'rossko', 'mx_group', or 'tm_parts'


def sanitize_part_search_result(
    p: Any, supplier: str, default_oem: str = "", default_brand: str = ""
) -> PartSearchResult | None:
    if not isinstance(p, dict):
        return None
    try:
        import math

        from ..config import MAX_FINANCIAL_TOTAL, SQLITE_INTEGER_MAX

        # OEM & Brand
        oem_val = p.get("oem")
        oem = str(oem_val).strip() if oem_val is not None else default_oem

        brand_val = p.get("brand")
        brand = str(brand_val).strip() if brand_val is not None else default_brand

        name_val = p.get("name")
        name = str(name_val).strip() if name_val is not None else ""

        # Truncate string inputs to prevent SQLite problems
        if len(oem) > 100:
            oem = oem[:100]
        if len(brand) > 140:
            brand = brand[:140]
        if len(name) > 500:
            name = name[:500]
        if not name:
            # Map suppliers to their naming convention
            supplier_display = {
                "rossko": "Rossko",
                "mx_group": "MX Group",
                "tm_parts": "TM Parts",
            }.get(supplier, supplier)
            name = f"Запчасть {supplier_display}"

        # Price validation
        price_val = p.get("price")
        if price_val is None:
            price = 0.0
        else:
            price = float(price_val)
            if not math.isfinite(price) or price < 0.0 or price > MAX_FINANCIAL_TOTAL:
                return None

        # Stock validation
        stock_val = p.get("stock")
        if stock_val is None:
            stock_val = p.get("quantity")
        if stock_val is None:
            stock = 0
        else:
            stock = int(stock_val)
            if stock < 0 or stock > SQLITE_INTEGER_MAX:
                return None

        # Delivery days validation
        days_val = p.get("delivery_days")
        if days_val is None:
            days_val = p.get("days")
        if days_val is None:
            delivery_days = 1
        else:
            delivery_days = int(days_val)
            if delivery_days < 0 or delivery_days > SQLITE_INTEGER_MAX:
                return None

        return {
            "oem": oem,
            "brand": brand,
            "name": name,
            "price": price,
            "stock": stock,
            "delivery_days": delivery_days,
            "supplier": supplier,
        }
    except (ValueError, TypeError, OverflowError):
        return None


class PartsSupplierAdapter(ABC):
    @property
    @abstractmethod
    def supplier_name(self) -> str:
        """Return distinct supplier name key."""
        pass

    @abstractmethod
    def search_parts(
        self, oem: str, brand: str | None = None
    ) -> list[PartSearchResult]:
        """Perform search query on supplier API via standard urllib query."""
        pass

    @abstractmethod
    def order_part(self, oem: str, brand: str, quantity: int) -> str | None:
        """Place order for given part. Returns order tracking ID or None on failure."""
        pass
