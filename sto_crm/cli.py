"""Command-line entrypoint and local server startup helpers."""

from __future__ import annotations

import argparse
import secrets
import signal
import socket
import sys
import threading
import time
import webbrowser
from contextlib import closing
from pathlib import Path
from typing import Any, Iterator

from . import runtime as _runtime
from .config import APP_NAME, DEFAULT_PORT
from .database import init_db
from .http_server import CRMHandler, CRMServer, CRMServerV6
from .runtime import Runtime, clean_text, default_db_path, parse_int, safe_log

def candidate_ports(preferred: int, attempts: int = 50) -> Iterator[int]:
    """Генерирует предпочтительные порты и безопасный fallback на порт ОС."""
    start = min(max(parse_int(preferred, DEFAULT_PORT), 0), 65_535)
    if start > 0:
        yield from range(start, min(start + max(attempts, 1), 65_536))
    yield 0


def find_free_port(preferred: int) -> int:
    """Возвращает ближайший свободный порт для обратной совместимости тестов и CLI."""
    for port in candidate_ports(preferred):
        try:
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", port))
                return int(sock.getsockname()[1])
        except OSError:
            continue
    raise OSError("Не удалось найти свободный локальный порт.")


def normalize_bind_host(host: str | None) -> str:
    value = clean_text(host, 255, "127.0.0.1").lower()
    aliases = {"", "localhost", "127.0.0.1", "::1"}
    if value not in aliases:
        raise ValueError("СТО CRM можно запускать только на локальном loopback-адресе: 127.0.0.1, localhost или ::1.")
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
    parser.add_argument("--host", default="127.0.0.1", help="локальный адрес сервера: 127.0.0.1, localhost или ::1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="порт локального сервера")
    parser.add_argument("--db", type=Path, default=None, help="путь к SQLite базе")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер автоматически")
    parser.add_argument("--demo", action="store_true", help="заполнить новую базу демонстрационными данными")
    args = parser.parse_args(argv)
    if args.port < 0 or args.port > 65_535:
        parser.error("Порт должен быть в диапазоне 0..65535, где 0 означает автоматический выбор свободного порта.")
    try:
        args.host = normalize_bind_host(args.host)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    db_path = args.db.resolve() if args.db else default_db_path()
    _runtime.RUNTIME = Runtime(db_path=db_path, start_time=time.time(), csrf_token=secrets.token_urlsafe(32))
    init_db(seed_demo=args.demo)
    server = create_server(args.port, args.host)
    host = server.server_address[0]
    port = server.server_port
    url_host = "[::1]" if host == "::1" else "127.0.0.1"
    url = f"http://{url_host}:{port}"

    def shutdown(*_: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, shutdown)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, shutdown)

    safe_log(f"{APP_NAME} запущена: {url}")
    safe_log(f"База данных: {_runtime.RUNTIME.db_path}")
    if not args.no_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0
