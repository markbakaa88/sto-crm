"""Command-line entrypoint and local server startup helpers."""

from __future__ import annotations

import argparse
import secrets
import signal
import sys
import threading
import time
import webbrowser
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import runtime as _runtime
from .config import APP_NAME, DEFAULT_PORT
from .database import init_db
from .http_server import CRMHandler, CRMServer, CRMServerV6
from .runtime import (
    Runtime,
    app_dir,
    clean_text,
    default_db_path,
    display_path,
    parse_int,
    safe_log,
)


def candidate_ports(preferred: int, attempts: int = 50) -> Iterator[int]:
    """Генерирует предпочтительные порты и безопасный fallback на порт ОС."""
    start = min(max(parse_int(preferred, DEFAULT_PORT), 0), 65_535)
    if start > 0:
        yield from range(start, min(start + max(attempts, 1), 65_536))
    yield 0


def normalize_bind_host(host: str | None) -> str:
    value = clean_text(host, 255, "127.0.0.1").lower()
    aliases = {"", "localhost", "127.0.0.1", "::1"}
    if value not in aliases:
        raise ValueError(
            "СТО CRM можно запускать только на локальном loopback-адресе: 127.0.0.1, localhost или ::1."
        )
    return "::1" if value == "::1" else "127.0.0.1"


def server_class_for_host(host: str) -> type[CRMServer]:
    return CRMServerV6 if host == "::1" else CRMServer


def create_server(preferred_port: int, host: str = "127.0.0.1") -> CRMServer:
    """Создаёт сервер сразу на локальном loopback-адресе, без race между проверкой и bind."""
    bind_host = normalize_bind_host(host)
    last_error: OSError | None = None
    for port in candidate_ports(preferred_port):
        try:
            return server_class_for_host(bind_host)((bind_host, port), CRMHandler)
        except OSError as exc:
            last_error = exc
            continue
    raise OSError("Не удалось запустить локальный сервер CRM.") from last_error


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Локальная CRM для автосервиса")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="локальный адрес сервера: 127.0.0.1, localhost или ::1",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="порт локального сервера"
    )
    parser.add_argument("--db", default=None, help="путь к SQLite базе")
    parser.add_argument(
        "--no-browser", action="store_true", help="не открывать браузер автоматически"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="заполнить новую базу демонстрационными данными",
    )
    args = parser.parse_args(argv)
    if args.port < 0 or args.port > 65_535:
        parser.error(
            "Порт должен быть в диапазоне 0..65535, где 0 означает автоматический выбор свободного порта."
        )
    try:
        args.host = normalize_bind_host(args.host)
    except ValueError as exc:
        parser.error(str(exc))
    if args.db is not None:
        args.db = normalize_db_path(args.db)
    return args


def normalize_db_path(path: str | Path) -> Path:
    raw = str(path)
    resolved = Path(raw).expanduser().resolve()
    app_root = app_dir().resolve()
    if resolved == app_root or resolved.is_dir() or raw.endswith(("/", "\\")):
        return resolved / "sto_crm.sqlite3"
    return resolved


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    db_path = args.db if args.db else default_db_path()
    _runtime.RUNTIME = Runtime(
        db_path=db_path,
        start_time=time.time(),
        csrf_token=secrets.token_urlsafe(32),
        access_token=secrets.token_urlsafe(32),
        bootstrap_token=secrets.token_urlsafe(32),
    )
    init_db(seed_demo=args.demo)
    server = create_server(args.port, args.host)
    host = server.server_address[0]
    port = server.server_port
    url_host = "[::1]" if host == "::1" else "127.0.0.1"
    url = f"http://{url_host}:{port}/"

    shutdown_called = False
    shutdown_lock = threading.Lock()

    def shutdown(*_: Any) -> None:
        nonlocal shutdown_called
        with shutdown_lock:
            if shutdown_called:
                return
            shutdown_called = True
        server.graceful_shutdown_flag = True
        threading.Thread(target=server.shutdown, daemon=True).start()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, shutdown)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, shutdown)

    safe_log(f"{APP_NAME} запущена: http://{url_host}:{port}")
    safe_log(f"База данных: {display_path(_runtime.RUNTIME.db_path)}")
    if not args.no_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    finally:
        server.server_close()
        # Graceful shutdown connection closing lag
        if getattr(server, "graceful_shutdown_flag", False):
            reason = getattr(server, "shutdown_reason", None)
            if reason == "offline":
                lag = 1.0
                safe_log(
                    f"Установка соединения останавливается (мягкое завершение при переходе в оффлайн: {lag}с)..."
                )
                time.sleep(lag)
            elif reason == "reboot":
                lag = 2.0
                safe_log(
                    f"Установка соединения останавливается (мягкое завершение при перезагрузке: {lag}с)..."
                )
                time.sleep(lag)
            else:
                lag = 0.5
                safe_log(
                    f"Установка соединения останавливается (мягкое завершение: {lag}с)..."
                )
                time.sleep(lag)
        if hasattr(server, "wait_for_active_threads"):
            server.wait_for_active_threads(5.0)
        time.sleep(0.1)
    return 0
