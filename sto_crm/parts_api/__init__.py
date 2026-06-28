"""Abstract Base Class for all outer auto-parts supplier API adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .utils import PartSearchResult as PartSearchResult
from .utils import sanitize_part_search_result as sanitize_part_search_result


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
