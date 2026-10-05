"""Logging configuration.

Logs go to ``<data dir>/logs/businesspos.log`` (rotating). A filter scrubs
values of keys that look like secrets in case one is ever passed in by
mistake; code must still never log passwords or payment credentials.
"""
from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SECRET_RE = re.compile(r"(?i)(password|passwd|pwd|pin|cvv|card_number)(\s*[=:]\s*)(\S+)")


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if _SECRET_RE.search(msg):
            record.msg = _SECRET_RE.sub(r"\1\2***", msg)
            record.args = ()
        return True


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    fh = RotatingFileHandler(logs_dir / "businesspos.log", maxBytes=2_000_000,
                             backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(_RedactFilter())
    root.addHandler(fh)

    if sys.stderr is not None and not getattr(sys, "frozen", False):
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh.addFilter(_RedactFilter())
        root.addHandler(sh)

    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
