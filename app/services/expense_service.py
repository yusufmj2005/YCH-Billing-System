"""Expenses and expense categories."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config.constants import Perm
from app.database.database import Database
from app.models import Expense, ExpenseCategory, PaymentMethod
from app.security.auth import CurrentUser, require
from app.services import audit_service
from app.services.errors import NotFound, ValidationError
from app.services.sales_service import clean_reference
from app.utils.dates import now
from app.utils.money import ZERO
from app.validators import common as v


def add_expense(s: Session, actor: CurrentUser, data: dict, payroll_id: int | None = None) -> Expense:
    cat = s.get(ExpenseCategory, data.get("category_id"))
    if cat is None or not cat.is_active:
        raise ValidationError("Please choose an expense category.")
    amount = v.amount(data.get("amount"), "Amount", positive=True)
    method = None
    if data.get("payment_method_id"):
        method = s.get(PaymentMethod, data["payment_method_id"])
        if method is None:
            raise ValidationError("Payment method not found.")
    e = Expense(
        category_id=cat.id, amount=amount,
        expense_date=v.as_date(data.get("expense_date"), "Expense date"),
        payment_method_id=method.id if method else None,
        method_name=method.name if method else None,
        description=v.text(data.get("description"), "Description", max_len=1000),
        reference=clean_reference(data.get("reference")),
        user_id=actor.id, payroll_id=payroll_id)
    if e.expense_date > date.today():
        raise ValidationError("Expense date cannot be in the future.")
    s.add(e)
    s.flush()
    audit_service.record(s, actor, "EXPENSE_CREATED", "expense", e.id,
                         {"category": cat.name, "amount": str(amount),
                          "date": str(e.expense_date)})
    return e


class ExpenseService:
    def __init__(self, db: Database):
        self.db = db

    def list_categories(self, include_inactive: bool = False) -> list[dict]:
        with self.db.session() as s:
            q = select(ExpenseCategory).order_by(ExpenseCategory.name)
            if not include_inactive:
                q = q.where(ExpenseCategory.is_active.is_(True))
            return [{"id": c.id, "name": c.name, "is_active": c.is_active} for c in s.scalars(q)]

    def save_category(self, actor: CurrentUser, cat_id: int | None, data: dict) -> int:
        require(actor, Perm.VOID_EXPENSE)
        name = v.text(data.get("name"), "Category name", required=True, max_len=100)
        with self.db.session() as s:
            dup = s.scalar(select(ExpenseCategory.id).where(ExpenseCategory.name == name))
            if dup and dup != cat_id:
                raise ValidationError("An expense category with this name already exists.")
            if cat_id is None:
                c = ExpenseCategory(name=name)
                s.add(c)
            else:
                c = s.get(ExpenseCategory, cat_id)
                if c is None:
                    raise NotFound("Category not found.")
                c.name = name
            if "is_active" in data:
                c.is_active = bool(data["is_active"])
            s.flush()
            audit_service.record(s, actor, "EXPENSE_CATEGORY_SAVED", "expense_category", c.id,
                                 {"name": name, "active": c.is_active})
            return c.id

    def create_expense(self, actor: CurrentUser, data: dict) -> int:
        require(actor, Perm.CREATE_EXPENSE)
        with self.db.session() as s:
            return add_expense(s, actor, data).id

    def void_expense(self, actor: CurrentUser, expense_id: int, reason: str) -> None:
        require(actor, Perm.VOID_EXPENSE)
        reason = v.text(reason, "Reason", required=True, max_len=500)
        with self.db.session() as s:
            e = s.get(Expense, expense_id)
            if e is None:
                raise NotFound("Expense not found.")
            if e.is_void:
                raise ValidationError("This expense is already void.")
            if e.payroll_id:
                raise ValidationError("This expense was created from payroll; cancel it there.")
            e.is_void, e.voided_at, e.voided_by, e.void_reason = True, now(), actor.id, reason
            audit_service.record(s, actor, "EXPENSE_VOIDED", "expense", e.id,
                                 {"amount": str(e.amount), "reason": reason})

    def list_expenses(self, actor: CurrentUser, *, date_from: date | None = None,
                      date_to: date | None = None, category_id: int | None = None,
                      include_void: bool = False, search: str = "", limit: int = 300,
                      offset: int = 0) -> tuple[list[dict], int, object]:
        require(actor, Perm.VIEW_EXPENSES)
        with self.db.session() as s:
            q = select(Expense).join(ExpenseCategory)
            if date_from:
                q = q.where(Expense.expense_date >= date_from)
            if date_to:
                q = q.where(Expense.expense_date <= date_to)
            if category_id:
                q = q.where(Expense.category_id == category_id)
            if not include_void:
                q = q.where(Expense.is_void.is_(False))
            if search:
                like = f"%{search}%"
                q = q.where(or_(Expense.description.ilike(like), Expense.reference.ilike(like)))
            sub = q.subquery()
            total = s.scalar(select(func.count()).select_from(sub))
            amount_sum = s.scalar(select(func.sum(Expense.amount)).where(
                Expense.id.in_(select(sub.c.id)), Expense.is_void.is_(False))) or ZERO
            rows = s.scalars(q.order_by(Expense.expense_date.desc(), Expense.id.desc())
                             .limit(limit).offset(offset)).all()
            return [{
                "id": e.id, "expense_date": e.expense_date, "category": e.category.name,
                "amount": e.amount, "method": e.method_name or "",
                "description": e.description or "", "reference": e.reference or "",
                "user": e.user.username if e.user else "", "is_void": e.is_void,
                "void_reason": e.void_reason or "", "from_payroll": bool(e.payroll_id),
            } for e in rows], total, amount_sum
