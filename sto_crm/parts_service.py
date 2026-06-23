"""Aggregation / querying and caching services for supplier parts."""

from __future__ import annotations

import threading
from typing import Any

from .config import PARTS_CACHE_TTL_SECONDS
from .database import db, write_db
from .parts_api import PartSearchResult
from .parts_api.aggregator import PartsAggregator
from .runtime import now_iso

_LOCKS = [threading.Lock() for _ in range(1024)]


def get_lock_for_query(oem: str, brand: str | None) -> threading.Lock:
    h = hash((oem, brand))
    return _LOCKS[h % 1024]


def search_supplier_parts(
    oem: str, brand: str | None = None, force_refresh: bool = False
) -> list[PartSearchResult]:
    """Search code across DB cache.

    If cache is absent or older than cache TTL (2 hours), queries API providers,
    populates cache, and returns merged data.
    """
    oem_clean = oem.strip().upper()
    brand_clean = brand.strip().upper() if brand else None

    lock = get_lock_for_query(oem_clean, brand_clean)
    with lock:
        # Check database cache first
        cached_results = _get_cached_parts(oem_clean, brand_clean)
        if cached_results:
            from datetime import datetime

            try:
                cached_at_str = cached_results[0]["cached_at"]
                cached_at = datetime.fromisoformat(cached_at_str)
                age = (datetime.now() - cached_at).total_seconds()
                # Coalesce concurrent requests: if cache was updated < 5 seconds ago,
                # reuse it even if force_refresh is True.
                if age < PARTS_CACHE_TTL_SECONDS and (not force_refresh or age < 5.0):
                    return [
                        {
                            "oem": r["oem"],
                            "brand": r["brand"],
                            "name": r["name"],
                            "price": r["price"],
                            "stock": r["stock"],
                            "delivery_days": r["delivery_days"],
                            "supplier": r["supplier"],
                        }
                        for r in cached_results
                    ]
            except Exception:
                pass  # fallback to refresh

        # Query API providers
        aggregator = PartsAggregator()
        api_items = aggregator.query_all(oem_clean, brand_clean)

        # Store them in cache database
        _update_parts_cache(oem_clean, brand_clean, api_items)

        return api_items


def place_supplier_order(
    oem: str, brand: str, supplier: str, quantity: int, price: float
) -> str:
    """Validate requested part is currently cached, perform order on provider API,

    and record order in sqlite database.
    """
    oem_clean = oem.strip().upper()
    brand_clean = brand.strip().upper()

    # 1. Validate matching part is in cache (or verify cache exists)
    cached_results = _get_cached_parts(oem_clean, brand_clean)
    # Check if there is stock available for the requested supplier
    matching_cached = [c for c in cached_results if c["supplier"] == supplier]
    if not matching_cached:
        raise ValueError(
            f"Запрошенная запчасть {oem_clean} ({brand_clean}) от поставщика {supplier} отсутствует в кэше. Сначала выполните поиск."
        )

    # Validate stock quantity
    total_stock = sum(c["stock"] for c in matching_cached)
    if total_stock < quantity:
        raise ValueError(
            f"Недостаточно деталей в наличии у поставщика {supplier}. Доступно: {total_stock}, запрошено: {quantity}"
        )

    # 2. Place order calling supplier API
    aggregator = PartsAggregator()
    order_tracking_id = aggregator.order_closest_part(
        oem_clean, brand_clean, supplier, quantity
    )
    if not order_tracking_id:
        raise RuntimeError(
            f"Поставщик {supplier} отклонил заказ или вернул пустой идентификатор отслеживания."
        )

    # 3. Add order transaction in SQLite (with retries and immediate writes)
    stamp = now_iso()
    with write_db() as conn:
        conn.execute(
            """
            INSERT INTO supplier_orders
            (oem, brand, supplier, quantity, price, order_tracking_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'created', ?)
            """,
            (
                oem_clean,
                brand_clean,
                supplier,
                quantity,
                price,
                order_tracking_id,
                stamp,
            ),
        )
        # Deduct quantity from cache
        for cache_row in matching_cached:
            if cache_row["stock"] >= quantity:
                new_stock = cache_row["stock"] - quantity
                conn.execute(
                    "UPDATE supplier_parts_cache SET stock = ? WHERE id = ?",
                    (new_stock, cache_row["id"]),
                )
                break
            else:
                quantity -= cache_row["stock"]
                conn.execute(
                    "UPDATE supplier_parts_cache SET stock = 0 WHERE id = ?",
                    (cache_row["id"],),
                )

    return order_tracking_id


def _get_cached_parts(oem: str, brand: str | None = None) -> list[dict[str, Any]]:
    # RetryingConnection (db readonly=True)
    with db(readonly=True) as conn:
        if brand:
            rows = conn.execute(
                """
                SELECT id, oem, brand, name, price, stock, delivery_days, supplier, cached_at
                FROM supplier_parts_cache
                WHERE CASEFOLD(oem) = CASEFOLD(?) AND CASEFOLD(brand) = CASEFOLD(?)
                """,
                (oem, brand),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, oem, brand, name, price, stock, delivery_days, supplier, cached_at
                FROM supplier_parts_cache
                WHERE CASEFOLD(oem) = CASEFOLD(?)
                """,
                (oem,),
            ).fetchall()
        return [dict(r) for r in rows]


def _update_parts_cache(
    oem: str, brand: str | None, items: list[PartSearchResult]
) -> None:
    stamp = now_iso()
    # RetryingConnection with Immediate Write
    with write_db() as conn:
        # Clear existing keys in cache
        if brand:
            conn.execute(
                "DELETE FROM supplier_parts_cache WHERE CASEFOLD(oem) = CASEFOLD(?) AND CASEFOLD(brand) = CASEFOLD(?)",
                (oem, brand),
            )
        else:
            conn.execute(
                "DELETE FROM supplier_parts_cache WHERE CASEFOLD(oem) = CASEFOLD(?)",
                (oem,),
            )

        # Bulk insert
        for item in items:
            conn.execute(
                """
                INSERT INTO supplier_parts_cache (oem, brand, name, price, stock, delivery_days, supplier, cached_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["oem"],
                    item["brand"],
                    item["name"],
                    item["price"],
                    item["stock"],
                    item["delivery_days"],
                    item["supplier"],
                    stamp,
                ),
            )
