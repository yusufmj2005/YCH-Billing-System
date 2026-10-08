from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
                        String, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.types import Money, Quantity, Rate
from app.models.base import Base, TimestampMixin
from app.utils.dates import now


class PaymentMethod(TimestampMixin, Base):
    __tablename__ = "payment_methods"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # PaymentKind
    name: Mapped[str] = mapped_column(String(64, collation="NOCASE"), unique=True,
                                      nullable=False)
    allows_reference: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    requires_description: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    invoice_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    # Customer snapshot so reprinted invoices never change.
    customer_name: Mapped[str | None] = mapped_column(String(150))
    customer_phone: Mapped[str | None] = mapped_column(String(32))
    customer_gstin: Mapped[str | None] = mapped_column(String(15))
    customer_address: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    tax_mode: Mapped[str] = mapped_column(String(8), nullable=False)
    gross_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    item_discount_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    bill_discount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    bill_discount_percent: Mapped[Decimal | None] = mapped_column(Rate())
    taxable_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    cgst_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    sgst_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    igst_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    round_off: Mapped[Decimal] = mapped_column(Money(), nullable=False, default=Decimal(0))
    grand_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    cost_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime)
    voided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    void_reason: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["SaleItem"]] = relationship(back_populates="sale", lazy="selectin",
                                                   order_by="SaleItem.id")
    payments: Mapped[list["Payment"]] = relationship(
        primaryjoin="Payment.sale_id == Sale.id", lazy="selectin", order_by="Payment.id",
        viewonly=True)
    user = relationship("User", foreign_keys=[user_id], lazy="joined")

    __table_args__ = (
        Index("ix_sales_created", "created_at"),
        Index("ix_sales_customer", "customer_id"),
        Index("ix_sales_status", "status"),
        CheckConstraint("grand_total >= 0", name="grand_total_nonneg"),
    )


class SaleItem(Base):
    __tablename__ = "sale_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(64))
    hsn_code: Mapped[str | None] = mapped_column(String(16))
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    price_includes_tax: Mapped[bool] = mapped_column(Boolean, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    discount_percent: Mapped[Decimal | None] = mapped_column(Rate())
    bill_discount_share: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    tax_rate_id: Mapped[int | None] = mapped_column(ForeignKey("tax_rates.id"))
    tax_name: Mapped[str | None] = mapped_column(String(64))
    tax_rate: Mapped[Decimal] = mapped_column(Rate(), nullable=False)
    cgst_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    sgst_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    igst_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    cost_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)

    sale: Mapped[Sale] = relationship(back_populates="items")

    __table_args__ = (
        Index("ix_sale_items_sale", "sale_id"),
        Index("ix_sale_items_product", "product_id"),
        CheckConstraint("quantity > 0", name="qty_positive"),
    )


class Payment(Base):
    """A recorded payment. Only the method and an optional transaction /
    reference id are stored — never card numbers, CVV, PINs or credentials."""
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    direction: Mapped[str] = mapped_column(String(4), nullable=False)  # IN / OUT
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id"))
    return_id: Mapped[int | None] = mapped_column(ForeignKey("returns.id"))
    purchase_id: Mapped[int | None] = mapped_column(ForeignKey("purchases.id"))
    payment_method_id: Mapped[int] = mapped_column(ForeignKey("payment_methods.id"),
                                                   nullable=False)
    method_name: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_void: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    method = relationship("PaymentMethod", lazy="joined")

    __table_args__ = (
        Index("ix_payments_sale", "sale_id"),
        Index("ix_payments_return", "return_id"),
        Index("ix_payments_purchase", "purchase_id"),
        Index("ix_payments_created", "created_at"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )


class SaleReturn(Base):
    __tablename__ = "returns"
    id: Mapped[int] = mapped_column(primary_key=True)
    return_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    taxable_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    # Invoice round-off given back when this return completes the whole invoice,
    # so that total refunds equal exactly what the customer paid. Included in
    # refund_total (refund_total = taxable_total + tax_total + round_off).
    round_off: Mapped[Decimal] = mapped_column(Money(), nullable=False, default=Decimal(0),
                                               server_default="0")
    refund_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    cost_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)

    items: Mapped[list["ReturnItem"]] = relationship(back_populates="sale_return",
                                                     lazy="selectin")
    sale = relationship("Sale", lazy="joined")
    user = relationship("User", lazy="joined")

    __table_args__ = (Index("ix_returns_sale", "sale_id"), Index("ix_returns_created", "created_at"))


class ReturnItem(Base):
    __tablename__ = "return_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("returns.id"), nullable=False)
    sale_item_id: Mapped[int] = mapped_column(ForeignKey("sale_items.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    cgst_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    sgst_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    igst_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    refund_amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    restocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    unit_cost: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    cost_total: Mapped[Decimal] = mapped_column(Money(), nullable=False)

    sale_return: Mapped[SaleReturn] = relationship(back_populates="items")

    __table_args__ = (
        Index("ix_return_items_sale_item", "sale_item_id"),
        CheckConstraint("quantity > 0", name="qty_positive"),
    )
