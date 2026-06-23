"""MX Group JSON REST API integration."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .. import config
from . import PartSearchResult, PartsSupplierAdapter


class MXGroupAdapter(PartsSupplierAdapter):
    @property
    def supplier_name(self) -> str:
        return "mx_group"

    def _request(self, path: str, data: dict[str, Any] | None = None) -> Any:
        url = config.MX_GROUP_API_URL.rstrip("/") + path
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {config.MX_GROUP_TOKEN}",
        }
        req_data = json.dumps(data) if data is not None else None
        req_bytes = req_data.encode("utf-8") if req_data is not None else None
        req = urllib.request.Request(
            url,
            data=req_bytes,
            headers=headers,
            method="POST" if data is not None else "GET",
        )
        try:
            from ..runtime import strict_json_loads
            with urllib.request.urlopen(req, timeout=config.PARTS_API_TIMEOUT) as resp:
                resp_payload = resp.read()
                return strict_json_loads(resp_payload.decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"MX Group API Error: {e}") from e

    def search_parts(
        self, oem: str, brand: str | None = None
    ) -> list[PartSearchResult]:
        if not config.MX_GROUP_TOKEN:
            return []

        # A mockable/real MX Group API search endpoint
        params = {"q": oem}
        if brand:
            params["brand"] = brand

        try:
            result = self._request("/api/v1/search", params)
            if not result or not isinstance(result, dict) or "items" not in result:
                return []

            items = result.get("items", [])
            results: list[PartSearchResult] = []
            from . import sanitize_part_search_result
            for item in items:
                sanitized = sanitize_part_search_result(
                    item, self.supplier_name, oem, brand or ""
                )
                if sanitized is not None:
                    results.append(sanitized)
            return results
        except Exception:
            return []

    def order_part(self, oem: str, brand: str, quantity: int) -> str | None:
        if not config.MX_GROUP_TOKEN:
            raise ValueError("MX Group token is not configured.")

        params = {"oem": oem, "brand": brand, "quantity": quantity}
        try:
            result = self._request("/api/v1/orders", params)
            if result and result.get("order_id"):
                return str(result["order_id"])
            return None
        except Exception as e:
            raise RuntimeError(f"MX Group order failure: {e}") from e
