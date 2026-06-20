"""TM Parts REST API integration."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .. import config
from . import PartSearchResult, PartsSupplierAdapter


class TMPartsAdapter(PartsSupplierAdapter):
    @property
    def supplier_name(self) -> str:
        return "tm_parts"

    def _request(self, path: str, query_params: dict[str, str] | None = None, data: dict[str, Any] | None = None) -> Any:
        url = config.TM_PARTS_API_URL.rstrip("/") + path
        if query_params:
            url += "?" + urllib.parse.urlencode(query_params)

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-Api-Key": config.TM_PARTS_KEY,
        }

        req_data = json.dumps(data) if data is not None else None
        req_bytes = req_data.encode("utf-8") if req_data is not None else None
        req = urllib.request.Request(
            url,
            data=req_bytes,
            headers=headers,
            method="POST" if data is not None else "GET"
        )
        try:
            with urllib.request.urlopen(req, timeout=config.PARTS_API_TIMEOUT) as resp:
                resp_payload = resp.read()
                return json.loads(resp_payload.decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"TM Parts API Error: {e}") from e

    def search_parts(self, oem: str, brand: str | None = None) -> list[PartSearchResult]:
        if not config.TM_PARTS_KEY:
            return []

        query_params = {"oem": oem}
        if brand:
            query_params["brand"] = brand

        try:
            result = self._request("/api/v2/search", query_params=query_params)
            if not result or not isinstance(result, list):
                return []

            results: list[PartSearchResult] = []
            for item in result:
                results.append({
                    "oem": str(item.get("oem", oem)),
                    "brand": str(item.get("brand", brand or "")),
                    "name": str(item.get("name", "Запчасть TM Parts")),
                    "price": float(item.get("price", 0.0)),
                    "stock": int(item.get("stock", 0)),
                    "delivery_days": int(item.get("delivery_days", 1)),
                    "supplier": self.supplier_name
                })
            return results
        except Exception:
            return []

    def order_part(self, oem: str, brand: str, quantity: int) -> str | None:
        if not config.TM_PARTS_KEY:
            raise ValueError("TM Parts API Key is not configured.")

        params = {
            "oem": oem,
            "brand": brand,
            "qty": quantity
        }
        try:
            result = self._request("/api/v2/orders", data=params)
            if result and result.get("id"):
                return str(result["id"])
            return None
        except Exception as e:
            raise RuntimeError(f"TM Parts order failure: {e}") from e
