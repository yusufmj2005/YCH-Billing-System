"""Tabular report container shared by the UI table, CSV and PDF exporters."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from app.utils.dates import fmt_date, fmt_dt
from app.utils.money import fmt_money, fmt_qty


@dataclass
class Col:
    key: str
    label: str
    kind: str = "text"  # text | money | qty | int | date | datetime | pct | bool

    @property
    def numeric(self) -> bool:
        return self.kind in ("money", "qty", "int", "pct")


@dataclass
class ReportResult:
    title: str
    columns: list[Col]
    rows: list[dict] = field(default_factory=list)
    totals: dict | None = None
    notes: list[str] = field(default_factory=list)
    subtitle: str = ""
    summary: list[tuple[str, str]] = field(default_factory=list)  # label/value pairs


def format_value(value, kind: str) -> str:
    if value is None or value == "":
        return ""
    if kind == "money":
        return fmt_money(value)
    if kind == "qty":
        return fmt_qty(value)
    if kind == "int":
        return str(int(value))
    if kind == "pct":
        return f"{Decimal(value):.2f}%"
    if kind == "datetime" and isinstance(value, datetime):
        return fmt_dt(value)
    if kind == "date" and isinstance(value, (date, datetime)):
        return fmt_date(value if isinstance(value, date) else value.date())
    if kind == "bool":
        return "Yes" if value else "No"
    return str(value)
