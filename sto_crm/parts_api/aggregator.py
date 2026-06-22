"""A unified facade/aggregator for querying all supplier APIs in parallel."""

from __future__ import annotations

import concurrent.futures

from ..runtime import safe_log
from . import PartSearchResult, PartsSupplierAdapter
from .mxgroup import MXGroupAdapter
from .rossko import RosskoAdapter
from .tmparts import TMPartsAdapter


class PartsAggregator:
    def __init__(self) -> None:
        self.adapters = [
            RosskoAdapter(),
            MXGroupAdapter(),
            TMPartsAdapter(),
        ]

    def query_all(self, oem: str, brand: str | None = None) -> list[PartSearchResult]:
        """Query all suppliers in parallel. Handles timeouts, connection errors and 429/503.

        Standard concurrent.futures is used to run the blocking urllib requests concurrently.
        """
        results: list[PartSearchResult] = []

        def query_one(adapter: PartsSupplierAdapter) -> list[PartSearchResult]:
            try:
                res = adapter.search_parts(oem, brand)
                # Cast or slice to satisfy mypy that we are returning list[PartSearchResult]
                return res
            except Exception as e:
                safe_log(
                    f"Ошибка при запросе к поставщику {adapter.supplier_name}: {e}"
                )
                return []

        # Use ThreadPoolExecutor to run tasks concurrently
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(self.adapters)
        ) as executor:
            futures = {
                executor.submit(query_one, adapter): adapter.supplier_name
                for adapter in self.adapters
            }
            # Wait with a timeout (plus a safe margin of 2 seconds over standard HTTP timeout)
            from ..config import PARTS_API_TIMEOUT

            done, not_done = concurrent.futures.wait(
                futures, timeout=PARTS_API_TIMEOUT + 2
            )

            for future in done:
                try:
                    res = future.result()
                    results.extend(res)
                except Exception as e:
                    supplier_name = futures[future]
                    safe_log(
                        f"Пул потоков выбросил исключение для {supplier_name}: {e}"
                    )

            # Log any timed out calls
            for future in not_done:
                supplier_name = futures[future]
                safe_log(f"Запрос к {supplier_name} отменен по таймауту агрегатора.")

        return results

    def order_closest_part(
        self, oem: str, brand: str, supplier: str, quantity: int
    ) -> str | None:
        """Find the matching supplier adapter and place an order."""
        for adapter in self.adapters:
            if adapter.supplier_name == supplier:
                return adapter.order_part(oem, brand, quantity)
        raise ValueError(f"Неизвестный поставщик: {supplier}")
