from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.types import Money, Quantity, Rate
from app.models.base import Base, TimestampMixin


class Category(TimestampMixin, Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100, collation="NOCASE"), unique=True,
                                      nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class TaxRate(TimestampMixin, Base):
    """A tax rate configured by the business. No rate is ever hard-coded."""
    __tablename__ = "tax_rates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64, collation="NOCASE"), unique=True,
                                      nullable=False)
    rate: Mapped[Decimal] = mapped_column(Rate(), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Supplier(TimestampMixin, Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    contact_person: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(150))
    address: Mapped[str | None] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(String(15))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (Index("ix_suppliers_name", "name"),)


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(150))
    address: Mapped[str | None] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(String(15))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (Index("ix_customers_name", "name"), Index("ix_customers_phone", "phone"))


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(64, collation="NOCASE"))
    barcode: Mapped[str | None] = mapped_column(String(64), unique=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    brand: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    hsn_code: Mapped[str | None] = mapped_column(String(16))
    purchase_price: Mapped[Decimal] = mapped_column(Money(), nullable=False, default=Decimal(0))
    selling_price: Mapped[Decimal] = mapped_column(Money(), nullable=False, default=Decimal(0))
    tax_rate_id: Mapped[int | None] = mapped_column(ForeignKey("tax_rates.id"))
    price_includes_tax: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    current_stock: Mapped[Decimal] = mapped_column(Quantity(), nullable=False, default=Decimal(0))
    min_stock_level: Mapped[Decimal | None] = mapped_column(Quantity())
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="pcs")
    allow_fractional_qty: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    image_path: Mapped[str | None] = mapped_column(String(255))

    category: Mapped[Category | None] = relationship(lazy="joined")
    supplier: Mapped[Supplier | None] = relationship(lazy="joined")
    tax_rate: Mapped[TaxRate | None] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_products_name", "name"),
        Index("ix_products_sku", "sku"),
        Index("ix_products_category", "category_id"),
        Index("ix_products_active", "is_active"),
    )
