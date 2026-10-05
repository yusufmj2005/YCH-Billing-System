from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.types import Money, Quantity
from app.models.base import Base
from app.utils.dates import now


class InventoryMovement(Base):
    """Immutable stock ledger. Every change to ``products.current_stock``
    has exactly one movement row (UPDATE/DELETE blocked by triggers)."""
    __tablename__ = "inventory_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(24), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)  # signed
    balance_after: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Money())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reference_type: Mapped[str | None] = mapped_column(String(24))
    reference_id: Mapped[int | None] = mapped_column(Integer)
    reference_no: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)

    product = relationship("Product", lazy="joined")
    user = relationship("User", lazy="joined")

    __table_args__ = (
        Index("ix_movements_product_date", "product_id", "created_at"),
        Index("ix_movements_date", "created_at"),
        Index("ix_movements_ref", "reference_type", "reference_id"),
    )
