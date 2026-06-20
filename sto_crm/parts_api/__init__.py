"""Abstract Base Class for all outer auto-parts supplier API adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict


class PartSearchResult(TypedDict):
    oem: str
    brand: str
    name: str  # part description
    price: float
    stock: int
    delivery_days: int
    supplier: str  # 'rossko', 'mx_group', or 'tm_parts'


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
