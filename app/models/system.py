from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils.dates import now


class AppMeta(Base):
    """Internal metadata: schema version, database identifier."""
    __tablename__ = "app_meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class Setting(Base):
    """Business settings as JSON-encoded key/value pairs."""
    __tablename__ = "business_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Sequence(Base):
    """Gap-free document number counters (invoice, purchase, return)."""
    __tablename__ = "sequences"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False)


class AuditLog(Base):
    """Append-only audit trail. UPDATE/DELETE are blocked by DB triggers."""
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    username: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_audit_created", "created_at"),
        Index("ix_audit_action", "action"),
        Index("ix_audit_user", "user_id"),
    )
