from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Index, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.types import Money
from app.models.base import Base, TimestampMixin
from app.utils.dates import now


class Employee(TimestampMixin, Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(32, collation="NOCASE"), unique=True,
                                               nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(150))
    role_title: Mapped[str | None] = mapped_column(String(100))
    joining_date: Mapped[date | None] = mapped_column(Date)
    base_salary: Mapped[Decimal | None] = mapped_column(Money())
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Attendance(TimestampMixin, Base):
    __tablename__ = "attendance"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    check_in: Mapped[str | None] = mapped_column(String(5))   # HH:MM
    check_out: Mapped[str | None] = mapped_column(String(5))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    employee = relationship("Employee", lazy="joined")

    __table_args__ = (UniqueConstraint("employee_id", "date", name="uq_attendance_emp_date"),
                      Index("ix_attendance_date", "date"))


class LeaveType(TimestampMixin, Base):
    __tablename__ = "leave_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64, collation="NOCASE"), unique=True,
                                      nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class LeaveRecord(Base):
    __tablename__ = "leave_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("leave_types.id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_note: Mapped[str | None] = mapped_column(Text)

    employee = relationship("Employee", lazy="joined")
    leave_type = relationship("LeaveType", lazy="joined")

    __table_args__ = (Index("ix_leave_employee", "employee_id"), Index("ix_leave_start", "start_date"))


class Payroll(Base):
    """Internal payroll record. No statutory deduction rules are applied."""
    __tablename__ = "payroll"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    base_salary: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    allowances: Mapped[Decimal] = mapped_column(Money(), nullable=False, default=Decimal(0))
    deductions: Mapped[Decimal] = mapped_column(Money(), nullable=False, default=Decimal(0))
    net_salary: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    paid_date: Mapped[date | None] = mapped_column(Date)
    payment_method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"))
    reference: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    employee = relationship("Employee", lazy="joined")

    __table_args__ = (Index("ix_payroll_employee", "employee_id"),
                      Index("ix_payroll_period", "period_start"))
