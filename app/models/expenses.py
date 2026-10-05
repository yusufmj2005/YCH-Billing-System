from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
                        String, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.types import Money
from app.models.base import Base, TimestampMixin
from app.utils.dates import now


class ExpenseCategory(TimestampMixin, Base):
    __tablename__ = "expense_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100, collation="NOCASE"), unique=True,
                                      nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("expense_categories.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"))
    method_name: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(String(100))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    payroll_id: Mapped[int | None] = mapped_column(ForeignKey("payroll.id"))
    is_void: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime)
    voided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    void_reason: Mapped[str | None] = mapped_column(Text)

    category = relationship("ExpenseCategory", lazy="joined")
    user = relationship("User", foreign_keys=[user_id], lazy="joined")

    __table_args__ = (
        Index("ix_expenses_date", "expense_date"),
        Index("ix_expenses_category", "category_id"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )
