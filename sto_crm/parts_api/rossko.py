"""Rossko API integration.

SOAP or REST interfaces can be used. We'll implement a clean, lightweight REST/JSON equivalent
using standard urllib.request targeting ROSSKO_API_URL.
Rossko API requires RosskoKey1 and RosskoKey2 for authorization.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .. import config
from . import PartSearchResult, PartsSupplierAdapter


class RosskoAdapter(PartsSupplierAdapter):
    @property
    def supplier_name(self) -> str:
        return "rossko"

    def _request(self, path: str, data: dict[str, Any] | None = None) -> Any:
        url = config.ROSSKO_API_URL.rstrip("/") + path
        # Inject Rossko keys
        payload = {
            "key1": config.ROSSKO_KEY1,
            "key2": config.ROSSKO_KEY2,
        }
        if data:
            payload.update(data)

        headers = {
            "Content-Type": "application/json; charset=utf-8",
        }
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
        try:
            from ..runtime import strict_json_loads
            with urllib.request.urlopen(req, timeout=config.PARTS_API_TIMEOUT) as resp:
                resp_payload = resp.read()
                return strict_json_loads(resp_payload.decode("utf-8"))
        except Exception as e:
            # Propagate or log
            raise RuntimeError(f"Rossko API Error: {e}") from e

    def search_parts(
        self, oem: str, brand: str | None = None
    ) -> list[PartSearchResult]:
        if not config.ROSSKO_KEY1 or not config.ROSSKO_KEY2:
            return []

        # A mocked/real API contract for Rossko search
        # E.g. POST /api/v1/search
        params = {"oem": oem}
        if brand:
            params["brand"] = brand

        try:
            result = self._request("/api/v1/search", params)
            if not result or "success" not in result or not result.get("success"):
                return []

            parts = result.get("parts", [])
            results: list[PartSearchResult] = []
            from . import sanitize_part_search_result
            for p in parts:
                sanitized = sanitize_part_search_result(
                    p, self.supplier_name, oem, brand or ""
                )
                if sanitized is not None:
                    results.append(sanitized)
            return results
        except Exception:
            return []

    def order_part(self, oem: str, brand: str, quantity: int) -> str | None:
        if not config.ROSSKO_KEY1 or not config.ROSSKO_KEY2:
            raise ValueError("Rossko API keys are not configured.")

        params = {"oem": oem, "brand": brand, "quantity": quantity}
        try:
            result = self._request("/api/v1/order", params)
            if result and result.get("success") and "order_id" in result:
                return str(result["order_id"])
            return None
        except Exception as e:
            raise RuntimeError(f"Rossko order failure: {e}") from e
