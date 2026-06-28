"""Reports, catalog, parts lookup/order, print forms and CSV export routing."""

from __future__ import annotations

import secrets

from .. import runtime as _runtime
from ..runtime import clean_text, parse_int_field, redact_sensitive_query
from ..validation import (
    ensure_finite_money,
    require_non_negative_float,
    require_non_negative_int,
)
from .base import BaseAPIHandler


def handle_reports(
    handler: BaseAPIHandler,
    method: str,
    path: str,
    query: dict[str, list[str]],
    path_parts: list[str],
) -> bool:
    from ..database import db
    from ..export import bootstrap_payload, csv_export
    from ..printing import print_order_html
    from ..queries import get_order

    if path.startswith("/print/order/"):
        if method != "GET":
            handler.send_error_json(405, "Метод не поддерживается.")
            return True
        handler.validate_local_request_context()
        handler.require_access_token()
        token = (
            handler.headers.get("X-CSRF-Token")
            or handler.headers.get("X-CRM-CSRF-Token")
            or ""
        )
        if not token or not secrets.compare_digest(token, _runtime.RUNTIME.csrf_token):
            raise PermissionError("Печатная форма доступна только из интерфейса CRM.")
        order_id = parse_int_field(path.rsplit("/", 1)[-1], "номер заказ-наряда")
        with db(readonly=True) as conn:
            handler.send_html(print_order_html(get_order(conn, order_id)))
        return True

    if path == "/api/bootstrap":
        if method != "GET":
            handler.send_error_json(405, "Метод не поддерживается.")
            return True
        handler.validate_local_request_context()
        # Bootstrap token escape hatch
        bootstrap_token_vals = query.get("bootstrap_token")
        token_valid = False
        if bootstrap_token_vals:
            token_valid = _runtime.consume_bootstrap_token(bootstrap_token_vals[0])
        if not token_valid:
            handler.require_access_token()
        q = clean_text((query.get("q") or [""])[0], 120)
        status = clean_text((query.get("status") or ["all"])[0], 40, "all")
        handler.send_json(bootstrap_payload(q, status))
        return True

    if path in {"/api/catalog", "/api/car-catalog"}:
        if method != "GET":
            handler.send_error_json(405, "Метод не поддерживается.")
            return True
        handler.validate_local_request_context()
        from ..catalog import car_catalog_payload

        handler.send_json(car_catalog_payload())
        return True

    if path.startswith("/api/parts/search"):
        if method == "GET":
            # Check for force query parameter: unauthorized/unsecured force-refresh attempts are rejected!
            force_vals = query.get("force", [])
            force_refresh = force_vals[0] == "true" if force_vals else False
            if force_refresh:
                handler.send_error_json(
                    400,
                    "Для выполнения принудительного обновления необходимо использовать POST-запрос с защитой CSRF."
                )
                return True

            handler.validate_local_request_context()
            handler.require_access_token()

            # OEM query parameter is required
            q_vals = query.get("q", [])
            if not q_vals or not q_vals[0].strip():
                handler.send_error_json(
                    400, "Параметр поиска q (OEM номер) является обязательным."
                )
                return True
            oem = q_vals[0]

            brand_vals = query.get("brand", [])
            brand = brand_vals[0] if brand_vals else None

            from ..parts_service import search_supplier_parts
            try:
                parts = search_supplier_parts(oem, brand, force_refresh=False)
                handler.send_json({"ok": True, "parts": parts})
            except Exception as exc:
                import logging
                logging.getLogger("sto_crm").error(
                    f"Search parts exception: {redact_sensitive_query(str(exc))}",
                    exc_info=True,
                )
                handler.send_error_json(500, "Ошибка при проценке запчастей.")
            return True

        elif method == "POST":
            handler.validate_local_request_context()
            handler.require_access_token()
            handler.require_csrf_token()
            handler.require_json_content_type()

            try:
                payload = handler.read_json()
            except Exception as exc:
                handler.send_error_json(400, f"Некорректный JSON: {exc}")
                return True

            oem_raw = payload.get("q") or payload.get("oem")
            oem = str(oem_raw) if oem_raw is not None else ""
            if not oem.strip():
                handler.send_error_json(
                    400, "Параметр поиска q (OEM номер) является обязательным."
                )
                return True

            brand_raw = payload.get("brand")
            brand = str(brand_raw) if brand_raw is not None else None

            force_refresh = payload.get("force", True)
            if not isinstance(force_refresh, bool):
                force_refresh = str(force_refresh).lower() == "true"

            # If force_refresh is True, we acquire search lock for the (oem, brand) pair non-blocking:
            if force_refresh:
                from ..parts_service import get_lock_for_query
                lock = get_lock_for_query(oem.strip().upper(), brand.strip().upper() if brand else None)
                if not lock.acquire(blocking=False):
                    handler.send_error_json(
                        429, "Запрос проценки уже выполняется. Пожалуйста, подождите."
                    )
                    return True
                try:
                    from ..parts_service import search_supplier_parts
                    parts = search_supplier_parts(oem, brand, force_refresh=True)
                    handler.send_json({"ok": True, "parts": parts})
                finally:
                    lock.release()
            else:
                from ..parts_service import search_supplier_parts
                try:
                    parts = search_supplier_parts(oem, brand, force_refresh=False)
                    handler.send_json({"ok": True, "parts": parts})
                except Exception as exc:
                    import logging
                    logging.getLogger("sto_crm").error(
                        f"Search parts exception: {redact_sensitive_query(str(exc))}",
                        exc_info=True,
                    )
                    handler.send_error_json(500, "Ошибка при проценке запчастей.")
            return True

        else:
            handler.send_error_json(405, "Метод не поддерживается.")
            return True

    if path == "/api/parts/order":
        if method != "POST":
            handler.send_error_json(405, "Метод не поддерживается.")
            return True
        handler.validate_local_request_context()
        handler.require_access_token()
        handler.require_csrf_token()
        handler.require_json_content_type()

        payload = handler.read_json()

        oem_raw = payload.get("oem")
        oem = str(oem_raw) if oem_raw is not None else ""
        brand_raw = payload.get("brand")
        brand = str(brand_raw) if brand_raw is not None else ""
        supplier_raw = payload.get("supplier")
        supplier = str(supplier_raw) if supplier_raw is not None else ""
        quantity_raw = payload.get("quantity")
        price_raw = payload.get("price")

        if (
            not oem
            or not brand
            or not supplier
            or quantity_raw is None
            or price_raw is None
        ):
            handler.send_error_json(
                400,
                "Поля oem, brand, supplier, quantity и price являются обязательными.",
            )
            return True

        try:
            quantity = require_non_negative_int(quantity_raw, "Количество")
            from ..config import SQLITE_INTEGER_MAX
            if quantity <= 0 or quantity > SQLITE_INTEGER_MAX:
                raise ValueError("Количество должно быть положительным и в пределах допустимого диапазона.")
        except (ValueError, TypeError) as exc:
            handler.send_error_json(
                400, f"Количество должно быть положительным целым числом: {exc}"
            )
            return True

        try:
            price = require_non_negative_float(price_raw, "Цена")
            ensure_finite_money(price, "Цена")
            if price <= 0.0:
                raise ValueError("Цена должна быть положительным числом.")
        except (ValueError, TypeError) as exc:
            handler.send_error_json(
                400, f"Цена должна быть положительным числом: {exc}"
            )
            return True

        from ..parts_service import place_supplier_order

        try:
            order_tracking_id = place_supplier_order(
                oem, brand, supplier, quantity, price
            )
            handler.send_json({"ok": True, "order_tracking_id": order_tracking_id})
        except ValueError as exc:
            handler.send_error_json(400, str(exc))
        except Exception as exc:
            import logging

            logging.getLogger("sto_crm").error(
                f"Order part exception: {redact_sensitive_query(str(exc))}",
                exc_info=True,
            )
            handler.send_error_json(500, "Ошибка при оформлении заказа.")
        return True

    if path.startswith("/api/export/"):
        if method != "GET":
            handler.send_error_json(405, "Метод не поддерживается.")
            return True
        handler.validate_local_request_context()
        handler.require_access_token()
        token = (
            handler.headers.get("X-CSRF-Token")
            or handler.headers.get("X-CRM-CSRF-Token")
            or ""
        )
        if not secrets.compare_digest(token, _runtime.RUNTIME.csrf_token):
            raise PermissionError("Экспорт доступен только из интерфейса CRM.")
        entity = path.rsplit("/", 1)[-1].removesuffix(".csv")
        try:
            filename, generator = csv_export(entity)
        except KeyError:
            handler.send_error_json(400, "Некорректная сущность экспорта.")
            return True
        handler.close_connection = True
        handler.send_response(200)
        handler.send_header("Content-Type", "text/csv; charset=utf-8")
        handler.send_header("Transfer-Encoding", "chunked")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("X-Frame-Options", "DENY")
        handler.send_header("Referrer-Policy", "no-referrer")
        handler.send_header(
            "Permissions-Policy", "geolocation=(), camera=(), microphone=()"
        )
        handler.send_header("Cross-Origin-Opener-Policy", "same-origin")
        handler.send_header("Cross-Origin-Resource-Policy", "same-origin")
        handler.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
        )
        handler.send_header("Connection", "close")
        handler.send_header(
            "Content-Disposition", f'attachment; filename="{filename}"'
        )
        handler.end_headers()

        try:
            for chunk in generator:
                data = chunk.encode("utf-8")
                if not data:
                    continue
                handler.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
                handler.wfile.write(data)
                handler.wfile.write(b"\r\n")
            handler.wfile.write(b"0\r\n\r\n")
        except (
            BrokenPipeError,
            ConnectionResetError,
            ConnectionAbortedError,
        ) as err:
            handler.close_connection = True
            raise BrokenPipeError from err
        return True

    return False
