"""Schema versioning.

Fresh database  -> create the current schema, install protective triggers,
                   stamp ``schema_version = SCHEMA_VERSION``.
Older database  -> call ``before_upgrade`` (the app makes a backup), then
                   apply each migration ``N`` (upgrading from N-1 to N) in its
                   own transaction and bump the stamped version.
Newer database  -> refuse to open (an older app must not touch newer data).

To change the schema in a future release:
  1. edit the models,
  2. add ``def _m0002(conn): conn.exec_driver_sql("ALTER TABLE ...")`` here,
  3. register it in ``MIGRATIONS`` and bump ``SCHEMA_VERSION`` in constants.
The installer only replaces program files, so the database survives updates
and is upgraded in place on first launch.
"""
from __future__ import annotations

import logging
import uuid
from typing import Callable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.config.constants import DB_IDENTIFIER, SCHEMA_VERSION
from app.database.database import Database
from app.models import Base

log = logging.getLogger(__name__)


class SchemaError(Exception):
    pass


# Tables whose rows are financial / historical records and may never be deleted.
_NO_DELETE_TABLES = ["sales", "sale_items", "payments", "returns", "return_items",
                     "inventory_movements", "expenses", "audit_logs"]
# Tables whose rows may never be modified at all.
_NO_UPDATE_TABLES = ["sale_items", "return_items", "inventory_movements", "audit_logs",
                     "returns"]


def protective_triggers() -> list[str]:
    ddl = []
    for t in _NO_DELETE_TABLES:
        ddl.append(
            f"CREATE TRIGGER IF NOT EXISTS trg_{t}_no_delete BEFORE DELETE ON {t} "
            f"BEGIN SELECT RAISE(ABORT, 'Records in {t} cannot be deleted'); END;")
    for t in _NO_UPDATE_TABLES:
        ddl.append(
            f"CREATE TRIGGER IF NOT EXISTS trg_{t}_no_update BEFORE UPDATE ON {t} "
            f"BEGIN SELECT RAISE(ABORT, 'Records in {t} are read-only'); END;")
    # Purchases: only drafts may be deleted (with their items).
    ddl.append(
        "CREATE TRIGGER IF NOT EXISTS trg_purchases_no_delete BEFORE DELETE ON purchases "
        "WHEN OLD.status <> 'DRAFT' "
        "BEGIN SELECT RAISE(ABORT, 'Only draft purchases can be deleted'); END;")
    ddl.append(
        "CREATE TRIGGER IF NOT EXISTS trg_purchase_items_no_delete BEFORE DELETE ON purchase_items "
        "WHEN (SELECT status FROM purchases WHERE id = OLD.purchase_id) <> 'DRAFT' "
        "BEGIN SELECT RAISE(ABORT, 'Items of a completed purchase cannot be deleted'); END;")
    ddl.append(
        "CREATE TRIGGER IF NOT EXISTS trg_purchase_items_no_update BEFORE UPDATE ON purchase_items "
        "WHEN (SELECT status FROM purchases WHERE id = OLD.purchase_id) <> 'DRAFT' "
        "BEGIN SELECT RAISE(ABORT, 'Items of a completed purchase are read-only'); END;")
    # Stock may never be changed without a ledger entry in the same statement
    # batch: enforced in the service layer; here we at least forbid
    # completed sales being re-opened.
    ddl.append(
        "CREATE TRIGGER IF NOT EXISTS trg_sales_status_guard BEFORE UPDATE OF status ON sales "
        "WHEN OLD.status = 'VOIDED' "
        "BEGIN SELECT RAISE(ABORT, 'A voided sale cannot be changed'); END;")
    ddl.append(
        "CREATE TRIGGER IF NOT EXISTS trg_sales_amount_guard BEFORE UPDATE ON sales "
        "WHEN NEW.grand_total <> OLD.grand_total OR NEW.invoice_no <> OLD.invoice_no "
        "BEGIN SELECT RAISE(ABORT, 'Sale totals and invoice numbers are immutable'); END;")
    ddl.append(
        "CREATE TRIGGER IF NOT EXISTS trg_payments_amount_guard BEFORE UPDATE ON payments "
        "WHEN NEW.amount <> OLD.amount OR NEW.payment_method_id <> OLD.payment_method_id "
        "BEGIN SELECT RAISE(ABORT, 'Recorded payments are immutable'); END;")
    return ddl


# version -> function(conn) that upgrades from version-1
MIGRATIONS: dict[int, Callable[[Connection], None]] = {}


def _get_version(conn: Connection) -> int | None:
    insp = inspect(conn)
    if "app_meta" not in insp.get_table_names():
        return None
    row = conn.execute(text("SELECT value FROM app_meta WHERE key='schema_version'")).fetchone()
    return int(row[0]) if row else None


def _set_meta(conn: Connection, key: str, value: str) -> None:
    conn.execute(text("INSERT INTO app_meta(key, value) VALUES (:k, :v) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value"),
                 {"k": key, "v": value})


def initialize_schema(db: Database,
                      before_upgrade: Callable[[int], None] | None = None) -> bool:
    """Create or upgrade the schema. Returns True if the DB was newly created."""
    with db.engine.connect() as conn:
        version = _get_version(conn)
        tables = inspect(conn).get_table_names()
        conn.rollback()

    if version is None:
        if tables:
            raise SchemaError("The database file is not a BusinessPOS database.")
        log.info("Creating new database schema v%s", SCHEMA_VERSION)
        with db.engine.begin() as conn:
            Base.metadata.create_all(conn)
            for stmt in protective_triggers():
                conn.exec_driver_sql(stmt)
            _set_meta(conn, "schema_version", str(SCHEMA_VERSION))
            _set_meta(conn, "identifier", DB_IDENTIFIER)
            _set_meta(conn, "database_id", uuid.uuid4().hex)
        return True

    if version > SCHEMA_VERSION:
        raise SchemaError(
            "This database was created by a newer version of BusinessPOS. "
            "Please install the latest version.")

    if version < SCHEMA_VERSION:
        log.info("Upgrading database schema v%s -> v%s", version, SCHEMA_VERSION)
        if before_upgrade:
            before_upgrade(version)
        for target in range(version + 1, SCHEMA_VERSION + 1):
            step = MIGRATIONS.get(target)
            if step is None:
                raise SchemaError(f"Missing migration for schema version {target}")
            with db.engine.begin() as conn:
                step(conn)
                _set_meta(conn, "schema_version", str(target))
            log.info("Applied migration v%s", target)

    # Idempotent: (re)install triggers in case a migration recreated a table.
    with db.engine.begin() as conn:
        for stmt in protective_triggers():
            conn.exec_driver_sql(stmt)
    return False


def read_meta(db: Database) -> dict[str, str]:
    with db.engine.connect() as conn:
        rows = conn.execute(text("SELECT key, value FROM app_meta")).fetchall()
        conn.rollback()
    return {k: v for k, v in rows}
