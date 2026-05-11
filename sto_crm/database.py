"""SQLite connection handling, schema creation and migrations."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from . import runtime as _runtime
from .config import APP_VERSION, LOOKUP_LIMIT
from .runtime import clean_multiline, now_iso, parse_int, safe_log


def _seed_demo_data() -> None:
    from .seed import seed_demo_data

    seed_demo_data()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_runtime.RUNTIME.db_path, timeout=30, isolation_level="DEFERRED")
    conn.row_factory = sqlite3.Row
    try:
        conn.create_function("CASEFOLD", 1, lambda value: str(value or "").casefold(), deterministic=True)
    except sqlite3.NotSupportedError:
        conn.create_function("CASEFOLD", 1, lambda value: str(value or "").casefold())
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        if conn.in_transaction:
            conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def write_db() -> Iterator[sqlite3.Connection]:
    """Open a write transaction early to serialize check-then-write business rules."""
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        yield conn


def init_db(seed_demo: bool = False) -> None:
    _runtime.RUNTIME.db_path.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    preferred_channel TEXT NOT NULL DEFAULT 'phone',
                    reminder_consent INTEGER NOT NULL DEFAULT 1,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS vehicles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL REFERENCES customers(id),
                    make TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    year INTEGER NOT NULL DEFAULT 0,
                    plate TEXT NOT NULL DEFAULT '',
                    vin TEXT NOT NULL DEFAULT '',
                    mileage INTEGER NOT NULL DEFAULT 0,
                    mileage_order_id INTEGER,
                    next_service_at TEXT NOT NULL DEFAULT '',
                    next_service_mileage INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    brand TEXT NOT NULL DEFAULT '',
                    unit TEXT NOT NULL DEFAULT 'шт',
                    quantity REAL NOT NULL DEFAULT 0,
                    min_quantity REAL NOT NULL DEFAULT 0,
                    price REAL NOT NULL DEFAULT 0,
                    cost REAL NOT NULL DEFAULT 0,
                    supplier TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    number TEXT NOT NULL UNIQUE,
                    customer_id INTEGER NOT NULL REFERENCES customers(id),
                    vehicle_id INTEGER REFERENCES vehicles(id),
                    status TEXT NOT NULL DEFAULT 'new',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    advisor TEXT NOT NULL DEFAULT '',
                    mechanic TEXT NOT NULL DEFAULT '',
                    promised_at TEXT NOT NULL DEFAULT '',
                    odometer INTEGER NOT NULL DEFAULT 0,
                    complaint TEXT NOT NULL DEFAULT '',
                    diagnosis TEXT NOT NULL DEFAULT '',
                    recommendations TEXT NOT NULL DEFAULT '',
                    discount REAL NOT NULL DEFAULT 0,
                    tax_rate REAL NOT NULL DEFAULT 0,
                    paid REAL NOT NULL DEFAULT 0,
                    payment_method TEXT NOT NULL DEFAULT '',
                    authorized_by TEXT NOT NULL DEFAULT '',
                    authorized_at TEXT NOT NULL DEFAULT '',
                    follow_up_at TEXT NOT NULL DEFAULT '',
                    closed_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL CHECK(kind IN ('service', 'part')),
                    inventory_id INTEGER REFERENCES inventory(id),
                    title TEXT NOT NULL,
                    approval_status TEXT NOT NULL DEFAULT 'approved',
                    quantity REAL NOT NULL DEFAULT 1,
                    unit_price REAL NOT NULL DEFAULT 0,
                    unit_cost REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS appointments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL REFERENCES customers(id),
                    vehicle_id INTEGER REFERENCES vehicles(id),
                    scheduled_at TEXT NOT NULL DEFAULT '',
                    duration_minutes INTEGER NOT NULL DEFAULT 60,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    advisor TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS inspections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL REFERENCES customers(id),
                    vehicle_id INTEGER REFERENCES vehicles(id),
                    order_id INTEGER REFERENCES orders(id),
                    status TEXT NOT NULL DEFAULT 'draft',
                    inspector TEXT NOT NULL DEFAULT '',
                    inspected_at TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS inspection_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inspection_id INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
                    area TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    condition_status TEXT NOT NULL DEFAULT 'ok',
                    approval_status TEXT NOT NULL DEFAULT 'approved',
                    recommendation TEXT NOT NULL DEFAULT '',
                    estimate REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_customers_active_name ON customers(deleted_at, name);
                CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
                CREATE INDEX IF NOT EXISTS idx_vehicles_active_customer ON vehicles(deleted_at, customer_id);
                CREATE INDEX IF NOT EXISTS idx_vehicles_plate ON vehicles(plate);
                CREATE INDEX IF NOT EXISTS idx_inventory_active_name ON inventory(deleted_at, name);
                CREATE INDEX IF NOT EXISTS idx_orders_active_status ON orders(deleted_at, status);
                CREATE INDEX IF NOT EXISTS idx_orders_deleted ON orders(deleted_at);
                CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
                CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
                CREATE INDEX IF NOT EXISTS idx_appointments_schedule ON appointments(deleted_at, scheduled_at);
                CREATE INDEX IF NOT EXISTS idx_appointments_customer ON appointments(customer_id);
                CREATE INDEX IF NOT EXISTS idx_inspections_vehicle ON inspections(deleted_at, vehicle_id, inspected_at);
                CREATE INDEX IF NOT EXISTS idx_inspections_customer ON inspections(customer_id);
                CREATE INDEX IF NOT EXISTS idx_inspection_items_inspection ON inspection_items(inspection_id);
                """
            )
            ensure_schema(conn)
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
    if seed_demo:
        _seed_demo_data()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> bool:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in columns:
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return True


def active_duplicate_values(conn: sqlite3.Connection, table: str, column: str, limit: int = 5) -> list[sqlite3.Row]:
    allowed_columns = {
        ("inventory", "sku"),
        ("vehicles", "vin"),
        ("vehicles", "plate"),
    }
    if (table, column) not in allowed_columns:
        raise ValueError("Некорректная проверка дублей.")
    return conn.execute(
        f"""
        SELECT CASEFOLD({column}) AS key, MIN({column}) AS value, COUNT(*) AS count, GROUP_CONCAT(id) AS ids
        FROM {table}
        WHERE deleted_at IS NULL AND {column} <> ''
        GROUP BY CASEFOLD({column})
        HAVING COUNT(*) > 1
        ORDER BY count DESC, value COLLATE NOCASE
        LIMIT ?
        """,
        (max(parse_int(limit, 5), 1),),
    ).fetchall()


def resolve_active_duplicate_values(conn: sqlite3.Connection, table: str, column: str, label: str) -> int:
    resolved = 0
    stamp = now_iso()
    for duplicate in active_duplicate_values(conn, table, column, LOOKUP_LIMIT):
        rows = conn.execute(
            f"""
            SELECT id, {column} AS value, notes
            FROM {table}
            WHERE deleted_at IS NULL AND {column} <> '' AND CASEFOLD({column}) = ?
            ORDER BY id
            """,
            (duplicate["key"],),
        ).fetchall()
        if len(rows) < 2:
            continue
        kept_id = int(rows[0]["id"])
        kept_value = str(rows[0]["value"] or "")
        for row in rows[1:]:
            original_value = str(row["value"] or "")
            note = (
                f"Системная миграция {APP_VERSION}: очищено дублирующее значение поля «{label}» "
                f"({original_value}); исходное значение оставлено у записи id {kept_id} ({kept_value})."
            )
            notes = clean_multiline("\n".join(part for part in [str(row["notes"] or "").strip(), note] if part), 2000)
            conn.execute(f"UPDATE {table} SET {column} = '', notes = ?, updated_at = ? WHERE id = ?", (notes, stamp, int(row["id"])))
            resolved += 1
    return resolved


def ensure_unique_index(conn: sqlite3.Connection, statement: str, table: str, column: str, label: str) -> None:
    try:
        conn.execute(statement)
    except sqlite3.IntegrityError as exc:
        resolved = resolve_active_duplicate_values(conn, table, column, label)
        if resolved:
            safe_log(f"Исправлены активные дубли поля «{label}»: очищено значений у записей: {resolved}.")
            conn.execute(statement)
            return
        duplicates = active_duplicate_values(conn, table, column)
        details = "; ".join(
            f"{row['value']} — {row['count']} записей (id: {row['ids']})" for row in duplicates
        ) or str(exc)
        raise RuntimeError(
            f"Невозможно включить защиту уникальности для поля «{label}»: найдены активные дубли. "
            f"Объедините или удалите дублирующиеся записи и перезапустите CRM. Примеры: {details}."
        ) from exc


def ensure_schema(conn: sqlite3.Connection) -> None:
    ensure_column(conn, "customers", "phone", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "customers", "email", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "customers", "source", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "customers", "preferred_channel", "TEXT NOT NULL DEFAULT 'phone'")
    ensure_column(conn, "customers", "reminder_consent", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "customers", "notes", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "customers", "created_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "customers", "updated_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "customers", "deleted_at", "TEXT")

    ensure_column(conn, "vehicles", "make", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "model", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "year", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "vehicles", "plate", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "vin", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "mileage", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "vehicles", "mileage_order_id", "INTEGER")
    ensure_column(conn, "vehicles", "next_service_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "next_service_mileage", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "vehicles", "notes", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "created_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "updated_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "deleted_at", "TEXT")

    ensure_column(conn, "inventory", "sku", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inventory", "brand", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inventory", "unit", "TEXT NOT NULL DEFAULT 'шт'")
    ensure_column(conn, "inventory", "quantity", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "inventory", "min_quantity", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "inventory", "price", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "inventory", "cost", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "inventory", "supplier", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inventory", "notes", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inventory", "created_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inventory", "updated_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inventory", "deleted_at", "TEXT")

    ensure_column(conn, "orders", "priority", "TEXT NOT NULL DEFAULT 'normal'")
    ensure_column(conn, "orders", "advisor", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "mechanic", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "promised_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "odometer", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "orders", "complaint", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "diagnosis", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "recommendations", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "discount", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "orders", "tax_rate", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "orders", "paid", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "orders", "payment_method", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "authorized_by", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "authorized_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "follow_up_at", "TEXT NOT NULL DEFAULT ''")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}
    if "closed_at" not in columns:
        conn.execute("ALTER TABLE orders ADD COLUMN closed_at TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
        UPDATE orders
        SET closed_at = COALESCE(NULLIF(updated_at, ''), created_at)
        WHERE status = 'closed' AND COALESCE(closed_at, '') = ''
        """
    )
    ensure_column(conn, "order_items", "approval_status", "TEXT NOT NULL DEFAULT 'approved'")
    ensure_column(conn, "appointments", "scheduled_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "appointments", "duration_minutes", "INTEGER NOT NULL DEFAULT 60")
    ensure_column(conn, "appointments", "status", "TEXT NOT NULL DEFAULT 'scheduled'")
    ensure_column(conn, "appointments", "advisor", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "appointments", "reason", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "appointments", "notes", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "appointments", "created_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "appointments", "updated_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "appointments", "deleted_at", "TEXT")

    ensure_column(conn, "inspections", "order_id", "INTEGER REFERENCES orders(id)")
    ensure_column(conn, "inspections", "status", "TEXT NOT NULL DEFAULT 'draft'")
    ensure_column(conn, "inspections", "inspector", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inspections", "inspected_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inspections", "summary", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inspections", "created_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inspections", "updated_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inspections", "deleted_at", "TEXT")

    ensure_column(conn, "inspection_items", "area", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inspection_items", "condition_status", "TEXT NOT NULL DEFAULT 'ok'")
    ensure_column(conn, "inspection_items", "approval_status", "TEXT NOT NULL DEFAULT 'approved'")
    ensure_column(conn, "inspection_items", "recommendation", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inspection_items", "estimate", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "inspection_items", "created_at", "TEXT NOT NULL DEFAULT ''")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_closed_at ON orders(closed_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_follow_up_at ON orders(follow_up_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vehicles_next_service ON vehicles(next_service_at, next_service_mileage)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_order_items_inventory ON order_items(inventory_id)")
    unique_indexes = (
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_sku_active ON inventory(CASEFOLD(sku)) WHERE deleted_at IS NULL AND sku <> ''",
            "inventory",
            "sku",
            "артикул склада",
        ),
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_vehicles_vin_active ON vehicles(CASEFOLD(vin)) WHERE deleted_at IS NULL AND vin <> ''",
            "vehicles",
            "vin",
            "VIN автомобиля",
        ),
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_vehicles_plate_active ON vehicles(CASEFOLD(plate)) WHERE deleted_at IS NULL AND plate <> ''",
            "vehicles",
            "plate",
            "госномер автомобиля",
        ),
    )
    for statement, table, column, label in unique_indexes:
        ensure_unique_index(conn, statement, table, column, label)
