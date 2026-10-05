"""Employees, attendance, leave and internal payroll.

Payroll is *Internal Payroll Management*: it records amounts entered by the
business. It does not calculate statutory deductions (PF, ESI, PT, TDS, ...).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select

from app.config.constants import ATTENDANCE_STATUSES, LeaveStatus, PayrollStatus, Perm
from app.database.database import Database
from app.models import (Attendance, Employee, Expense, ExpenseCategory, LeaveRecord, LeaveType,
                        PaymentMethod, Payroll)
from app.security.auth import CurrentUser, require
from app.services import audit_service
from app.services.errors import NotFound, ValidationError
from app.services.expense_service import add_expense
from app.utils.dates import now
from app.utils.money import ZERO
from app.validators import common as v


def _emp(e: Employee) -> dict:
    return {"id": e.id, "employee_code": e.employee_code, "name": e.name, "phone": e.phone or "",
            "email": e.email or "", "role_title": e.role_title or "",
            "joining_date": e.joining_date, "base_salary": e.base_salary,
            "notes": e.notes or "", "is_active": e.is_active}


class StaffService:
    def __init__(self, db: Database):
        self.db = db

    # ---- employees -----------------------------------------------------------------
    def list_employees(self, actor: CurrentUser, search: str = "",
                       include_inactive: bool = False) -> list[dict]:
        if not actor.has_any(Perm.MANAGE_EMPLOYEES, Perm.MANAGE_ATTENDANCE, Perm.MANAGE_LEAVE,
                             Perm.MANAGE_PAYROLL, Perm.APPROVE_LEAVE):
            require(actor, Perm.MANAGE_EMPLOYEES)
        with self.db.session() as s:
            q = select(Employee)
            if not include_inactive:
                q = q.where(Employee.is_active.is_(True))
            if search:
                like = f"%{search}%"
                q = q.where(or_(Employee.name.ilike(like), Employee.employee_code.ilike(like),
                                Employee.phone.ilike(like)))
            return [_emp(e) for e in s.scalars(q.order_by(Employee.name))]

    def save_employee(self, actor: CurrentUser, emp_id: int | None, data: dict) -> int:
        require(actor, Perm.MANAGE_EMPLOYEES)
        fields = {
            "employee_code": v.text(data.get("employee_code"), "Employee ID", required=True,
                                    max_len=32),
            "name": v.text(data.get("name"), "Name", required=True, max_len=150),
            "phone": v.phone(data.get("phone")),
            "email": v.email(data.get("email")),
            "role_title": v.text(data.get("role_title"), "Role", max_len=100),
            "joining_date": v.as_date(data.get("joining_date"), "Joining date", required=False),
            "base_salary": v.amount(data.get("base_salary"), "Base salary", required=False),
            "notes": v.text(data.get("notes"), "Notes", max_len=2000),
        }
        with self.db.session() as s:
            dup = s.scalar(select(Employee.id).where(
                Employee.employee_code == fields["employee_code"]))
            if dup and dup != emp_id:
                raise ValidationError("Another employee already has this Employee ID.")
            if emp_id is None:
                e = Employee(**fields)
                s.add(e)
                action = "EMPLOYEE_CREATED"
            else:
                e = s.get(Employee, emp_id)
                if e is None:
                    raise NotFound("Employee not found.")
                for k, val in fields.items():
                    setattr(e, k, val)
                action = "EMPLOYEE_UPDATED"
            if "is_active" in data:
                e.is_active = bool(data["is_active"])
            s.flush()
            audit_service.record(s, actor, action, "employee", e.id,
                                 {"code": e.employee_code, "name": e.name, "active": e.is_active})
            return e.id

    # ---- attendance ----------------------------------------------------------------
    def attendance_for_date(self, actor: CurrentUser, day: date) -> list[dict]:
        require(actor, Perm.MANAGE_ATTENDANCE)
        with self.db.session() as s:
            records = {a.employee_id: a for a in s.scalars(
                select(Attendance).where(Attendance.date == day))}
            out = []
            for e in s.scalars(select(Employee).where(Employee.is_active.is_(True))
                               .order_by(Employee.name)):
                a = records.get(e.id)
                out.append({"employee_id": e.id, "employee_code": e.employee_code,
                            "name": e.name, "attendance_id": a.id if a else None,
                            "status": a.status if a else "", "check_in": a.check_in if a else "",
                            "check_out": a.check_out if a else "", "notes": a.notes if a else ""})
            return out

    def save_attendance(self, actor: CurrentUser, employee_id: int, day: date, data: dict) -> None:
        require(actor, Perm.MANAGE_ATTENDANCE)
        status = data.get("status")
        if status not in ATTENDANCE_STATUSES:
            raise ValidationError("Please choose an attendance status.")
        check_in = v.hhmm(data.get("check_in"), "Check-in")
        check_out = v.hhmm(data.get("check_out"), "Check-out")
        if check_in and check_out and check_out < check_in:
            raise ValidationError("Check-out must be after check-in.")
        if day > date.today():
            raise ValidationError("Attendance cannot be recorded for a future date.")
        with self.db.session() as s:
            if s.get(Employee, employee_id) is None:
                raise NotFound("Employee not found.")
            a = s.scalar(select(Attendance).where(Attendance.employee_id == employee_id,
                                                  Attendance.date == day))
            if a is None:
                a = Attendance(employee_id=employee_id, date=day)
                s.add(a)
            a.status, a.check_in, a.check_out = status, check_in, check_out
            a.notes = v.text(data.get("notes"), "Notes", max_len=500)
            a.recorded_by = actor.id
            s.flush()
            audit_service.record(s, actor, "ATTENDANCE_SAVED", "attendance", a.id,
                                 {"employee_id": employee_id, "date": str(day), "status": status})

    def attendance_history(self, actor: CurrentUser, employee_id: int | None, date_from: date,
                           date_to: date) -> list[dict]:
        require(actor, Perm.MANAGE_ATTENDANCE)
        with self.db.session() as s:
            q = select(Attendance).where(Attendance.date >= date_from, Attendance.date <= date_to)
            if employee_id:
                q = q.where(Attendance.employee_id == employee_id)
            return [{"date": a.date, "employee": a.employee.name,
                     "employee_code": a.employee.employee_code, "status": a.status,
                     "check_in": a.check_in or "", "check_out": a.check_out or "",
                     "notes": a.notes or ""}
                    for a in s.scalars(q.order_by(Attendance.date.desc(), Attendance.id))]

    # ---- leave ---------------------------------------------------------------------
    def list_leave_types(self, include_inactive: bool = False) -> list[dict]:
        with self.db.session() as s:
            q = select(LeaveType).order_by(LeaveType.name)
            if not include_inactive:
                q = q.where(LeaveType.is_active.is_(True))
            return [{"id": t.id, "name": t.name, "is_active": t.is_active} for t in s.scalars(q)]

    def save_leave_type(self, actor: CurrentUser, type_id: int | None, data: dict) -> int:
        require(actor, Perm.APPROVE_LEAVE)
        name = v.text(data.get("name"), "Leave type", required=True, max_len=64)
        with self.db.session() as s:
            dup = s.scalar(select(LeaveType.id).where(LeaveType.name == name))
            if dup and dup != type_id:
                raise ValidationError("This leave type already exists.")
            t = LeaveType(name=name) if type_id is None else s.get(LeaveType, type_id)
            if t is None:
                raise NotFound("Leave type not found.")
            t.name = name
            if "is_active" in data:
                t.is_active = bool(data["is_active"])
            s.add(t)
            s.flush()
            audit_service.record(s, actor, "LEAVE_TYPE_SAVED", "leave_type", t.id, {"name": name})
            return t.id

    def create_leave(self, actor: CurrentUser, data: dict) -> int:
        require(actor, Perm.MANAGE_LEAVE)
        start = v.as_date(data.get("start_date"), "Start date")
        end = v.as_date(data.get("end_date"), "End date")
        if end < start:
            raise ValidationError("End date must be on or after the start date.")
        with self.db.session() as s:
            emp = s.get(Employee, data.get("employee_id"))
            if emp is None:
                raise ValidationError("Please choose an employee.")
            lt = s.get(LeaveType, data.get("leave_type_id"))
            if lt is None or not lt.is_active:
                raise ValidationError("Please choose a leave type.")
            overlap = s.scalar(select(LeaveRecord.id).where(
                LeaveRecord.employee_id == emp.id, LeaveRecord.status != LeaveStatus.REJECTED,
                LeaveRecord.start_date <= end, LeaveRecord.end_date >= start).limit(1))
            if overlap:
                raise ValidationError("This employee already has leave recorded for these dates.")
            r = LeaveRecord(employee_id=emp.id, leave_type_id=lt.id, start_date=start,
                            end_date=end, reason=v.text(data.get("reason"), "Reason", max_len=1000),
                            status=LeaveStatus.PENDING, created_by=actor.id)
            s.add(r)
            s.flush()
            audit_service.record(s, actor, "LEAVE_CREATED", "leave", r.id,
                                 {"employee": emp.name, "type": lt.name,
                                  "from": str(start), "to": str(end)})
            return r.id

    def decide_leave(self, actor: CurrentUser, leave_id: int, approve: bool, note: str = "") -> None:
        require(actor, Perm.APPROVE_LEAVE)
        with self.db.session() as s:
            r = s.get(LeaveRecord, leave_id)
            if r is None:
                raise NotFound("Leave record not found.")
            if r.status != LeaveStatus.PENDING:
                raise ValidationError("Only pending leave requests can be approved or rejected.")
            r.status = LeaveStatus.APPROVED if approve else LeaveStatus.REJECTED
            r.decided_by, r.decided_at = actor.id, now()
            r.decision_note = v.text(note, "Note", max_len=500)
            audit_service.record(s, actor, "LEAVE_" + r.status.upper(), "leave", r.id,
                                 {"employee": r.employee.name})

    def list_leave(self, actor: CurrentUser, status: str | None = None,
                   employee_id: int | None = None) -> list[dict]:
        if not actor.has_any(Perm.MANAGE_LEAVE, Perm.APPROVE_LEAVE):
            require(actor, Perm.MANAGE_LEAVE)
        with self.db.session() as s:
            q = select(LeaveRecord)
            if status:
                q = q.where(LeaveRecord.status == status)
            if employee_id:
                q = q.where(LeaveRecord.employee_id == employee_id)
            return [{"id": r.id, "employee": r.employee.name, "leave_type": r.leave_type.name,
                     "start_date": r.start_date, "end_date": r.end_date,
                     "days": (r.end_date - r.start_date).days + 1, "reason": r.reason or "",
                     "status": r.status, "decision_note": r.decision_note or ""}
                    for r in s.scalars(q.order_by(LeaveRecord.start_date.desc()))]

    # ---- payroll -------------------------------------------------------------------
    def create_payroll(self, actor: CurrentUser, data: dict) -> int:
        require(actor, Perm.MANAGE_PAYROLL)
        start = v.as_date(data.get("period_start"), "Period start")
        end = v.as_date(data.get("period_end"), "Period end")
        if end < start:
            raise ValidationError("Period end must be on or after period start.")
        base = v.amount(data.get("base_salary"), "Base salary")
        allowances = v.amount(data.get("allowances") or 0, "Allowances")
        deductions = v.amount(data.get("deductions") or 0, "Deductions")
        net = base + allowances - deductions
        if net < 0:
            raise ValidationError("Deductions cannot exceed base salary plus allowances.")
        with self.db.session() as s:
            emp = s.get(Employee, data.get("employee_id"))
            if emp is None:
                raise ValidationError("Please choose an employee.")
            dup = s.scalar(select(Payroll.id).where(
                Payroll.employee_id == emp.id, Payroll.status != PayrollStatus.CANCELLED,
                Payroll.period_start <= end, Payroll.period_end >= start).limit(1))
            if dup:
                raise ValidationError("A payroll entry already exists for this employee and period.")
            p = Payroll(employee_id=emp.id, period_start=start, period_end=end, base_salary=base,
                        allowances=allowances, deductions=deductions, net_salary=net,
                        status=PayrollStatus.UNPAID,
                        notes=v.text(data.get("notes"), "Notes", max_len=1000),
                        created_by=actor.id)
            s.add(p)
            s.flush()
            audit_service.record(s, actor, "PAYROLL_CREATED", "payroll", p.id,
                                 {"employee": emp.name, "period": f"{start}..{end}",
                                  "net": str(net)})
            return p.id

    def mark_payroll_paid(self, actor: CurrentUser, payroll_id: int, *, paid_date: date,
                          payment_method_id: int | None, reference: str | None,
                          record_expense: bool, expense_category_id: int | None = None) -> None:
        require(actor, Perm.MANAGE_PAYROLL)
        with self.db.session() as s:
            p = s.get(Payroll, payroll_id)
            if p is None:
                raise NotFound("Payroll entry not found.")
            if p.status != PayrollStatus.UNPAID:
                raise ValidationError("Only unpaid payroll entries can be marked as paid.")
            paid_date = v.as_date(paid_date, "Paid date")
            if payment_method_id and s.get(PaymentMethod, payment_method_id) is None:
                raise ValidationError("Payment method not found.")
            p.status, p.paid_date = PayrollStatus.PAID, paid_date
            p.payment_method_id = payment_method_id
            p.reference = v.text(reference, "Reference", max_len=100)
            if record_expense and p.net_salary > 0:
                if not actor.has(Perm.CREATE_EXPENSE):
                    raise ValidationError("You need permission to record expenses.")
                cat_id = expense_category_id or s.scalar(
                    select(ExpenseCategory.id).where(ExpenseCategory.name == "Salaries"))
                if not cat_id:
                    raise ValidationError("Choose an expense category for salary payments.")
                add_expense(s, actor, {
                    "category_id": cat_id, "amount": p.net_salary, "expense_date": paid_date,
                    "payment_method_id": payment_method_id, "reference": p.reference,
                    "description": f"Salary: {p.employee.name} "
                                   f"({p.period_start:%d-%m-%Y} to {p.period_end:%d-%m-%Y})",
                }, payroll_id=p.id)
            audit_service.record(s, actor, "PAYROLL_PAID", "payroll", p.id,
                                 {"employee": p.employee.name, "net": str(p.net_salary),
                                  "expense_recorded": record_expense})

    def cancel_payroll(self, actor: CurrentUser, payroll_id: int) -> None:
        require(actor, Perm.MANAGE_PAYROLL)
        with self.db.session() as s:
            p = s.get(Payroll, payroll_id)
            if p is None:
                raise NotFound("Payroll entry not found.")
            if p.status == PayrollStatus.CANCELLED:
                raise ValidationError("Already cancelled.")
            for e in s.scalars(select(Expense).where(Expense.payroll_id == p.id,
                                                     Expense.is_void.is_(False))):
                e.is_void, e.voided_at, e.voided_by = True, now(), actor.id
                e.void_reason = "Payroll entry cancelled"
            p.status = PayrollStatus.CANCELLED
            audit_service.record(s, actor, "PAYROLL_CANCELLED", "payroll", p.id,
                                 {"employee": p.employee.name})

    def list_payroll(self, actor: CurrentUser, date_from: date | None = None,
                     date_to: date | None = None, employee_id: int | None = None) -> list[dict]:
        require(actor, Perm.MANAGE_PAYROLL)
        with self.db.session() as s:
            q = select(Payroll)
            if date_from:
                q = q.where(Payroll.period_end >= date_from)
            if date_to:
                q = q.where(Payroll.period_start <= date_to)
            if employee_id:
                q = q.where(Payroll.employee_id == employee_id)
            methods = {m.id: m.name for m in s.scalars(select(PaymentMethod))}
            return [{"id": p.id, "employee": p.employee.name,
                     "employee_code": p.employee.employee_code,
                     "period_start": p.period_start, "period_end": p.period_end,
                     "base_salary": p.base_salary, "allowances": p.allowances,
                     "deductions": p.deductions, "net_salary": p.net_salary,
                     "status": p.status, "paid_date": p.paid_date,
                     "method": methods.get(p.payment_method_id, ""),
                     "reference": p.reference or "", "notes": p.notes or ""}
                    for p in s.scalars(q.order_by(Payroll.period_start.desc(), Payroll.id.desc()))]

    def payroll_total(self, rows: list[dict]):
        return sum((r["net_salary"] for r in rows if r["status"] != PayrollStatus.CANCELLED), ZERO)
