"""SQLite engine / session management.

* Foreign keys are enforced (``PRAGMA foreign_keys=ON``).
* Every transaction starts with ``BEGIN IMMEDIATE`` so the write lock is
  taken up-front. Combined with the short-lived ``session()`` unit of work
  this makes multi-step operations (sale -> items -> payments -> stock ->
  invoice number) atomic: either everything commits or everything rolls back.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger(__name__)


class Database:
    def __init__(self, db_file: Path):
        self.db_file = Path(db_file)
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = self._create_engine()
        self._factory = sessionmaker(bind=self.engine, expire_on_commit=False,
                                     autoflush=True)

    def _create_engine(self) -> Engine:
        engine = create_engine(
            f"sqlite:///{self.db_file.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 15},
        )

        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_conn, _record):
            # Let SQLAlchemy (not pysqlite) control transaction boundaries.
            dbapi_conn.isolation_level = None
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=FULL")
            cur.execute("PRAGMA busy_timeout=15000")
            cur.close()

        @event.listens_for(engine, "begin")
        def _on_begin(conn):
            conn.exec_driver_sql("BEGIN IMMEDIATE")

        return engine

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Unit of work: commits on success, rolls back on any exception."""
        s = self._factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def dispose(self) -> None:
        self.engine.dispose()

    def reopen(self) -> None:
        self.engine.dispose()
        self.engine = self._create_engine()
        self._factory.configure(bind=self.engine)

    def integrity_check(self) -> str:
        con = sqlite3.connect(self.db_file)
        try:
            return con.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            con.close()
