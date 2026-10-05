from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.types import Money, Quantity, Rate
from app.models.base import Base
from app.utils.dates import now


class Purchase(Base):
    __tablename__ = "purchases"
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    supplier_invoice_no: Mapped[str | None] = mapped_column(String(64))
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    discount_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    grand_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(Money(), nullable=False, default=Decimal(0))
    payment_status: Mapped[str] = mapped_column(String(16), nullable=False)
    update_cost_prices: Mapped[bool] = mapped_column(default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["PurchaseItem"]] = relationship(
        back_populates="purchase", lazy="selectin", cascade="all, delete-orphan",
        order_by="PurchaseItem.id")
    supplier = relationship("Supplier", lazy="joined")
    payments = relationship("Payment", primaryjoin="Payment.purchase_id == Purchase.id",
                            lazy="selectin", viewonly=True, order_by="Payment.id")

    __table_args__ = (
        Index("ix_purchases_date", "purchase_date"),
        Index("ix_purchases_supplier", "supplier_id"),
        Index("ix_purchases_status", "status"),
    )


class PurchaseItem(Base):
    __tablename__ = "purchase_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Rate(), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)

    purchase: Mapped[Purchase] = relationship(back_populates="items")

    __table_args__ = (
        Index("ix_purchase_items_purchase", "purchase_id"),
        Index("ix_purchase_items_product", "product_id"),
        CheckConstraint("quantity > 0", name="qty_positive"),
    )
