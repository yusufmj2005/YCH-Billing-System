"""Date range helpers used by reports and filters (local time)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def day_start(d: date) -> datetime:
    return datetime.combine(d, time.min)


def day_end_exclusive(d: date) -> datetime:
    return datetime.combine(d + timedelta(days=1), time.min)


def preset_range(name: str, today: date | None = None) -> tuple[date, date]:
    """Return inclusive (start, end) dates for a named preset."""
    today = today or date.today()
    if name == "today":
        return today, today
    if name == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if name == "this_week":
        start = today - timedelta(days=today.weekday())
        return start, today
    if name == "this_month":
        return today.replace(day=1), today
    if name == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    if name == "last_30":
        return today - timedelta(days=29), today
    if name == "this_year":
        return today.replace(month=1, day=1), today
    raise ValueError(f"Unknown preset {name}")


def fmt_dt(value: datetime | None) -> str:
    return value.strftime("%d-%m-%Y %H:%M") if value else ""


def fmt_date(value: date | None) -> str:
    return value.strftime("%d-%m-%Y") if value else ""
