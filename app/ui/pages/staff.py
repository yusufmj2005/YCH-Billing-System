"""Employees, attendance, leave and internal payroll pages."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QInputDialog,
                               QLineEdit, QTableWidget, QTableWidgetItem)

from app.config.constants import ATTENDANCE_STATUSES, LeaveStatus, Perm, PayrollStatus
from app.reports.base import Col
from app.ui.pages.base import Page
from app.ui.styles.theme import C
from app.ui.widgets.common import (DateRangeBar, button, confirm, date_edit, label, pydate,
                                   search_box, show_info, ui_action)
from app.ui.widgets.forms import Field, FormDialog
from app.ui.widgets.table import DataTable

EMP_FIELDS = [
    Field("employee_code", "Employee ID", required=True, max_length=32),
    Field("name", "Name", required=True, max_length=150),
    Field("phone", "Phone", max_length=20), Field("email", "Email", max_length=150),
    Field("role_title", "Role / designation", max_length=100),
    Field("joining_date", "Joining date", "optdate"),
    Field("base_salary", "Base salary", "money", help="Optional; used as the payroll default"),
    Field("notes", "Notes", "multiline"), Field("is_active", "Active", "check"),
]


class EmployeesPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        self.search = search_box("Search name, employee ID or phone…", self.load)
        self.inactive = QCheckBox("Show inactive")
        self.inactive.toggled.connect(self.load)
        bar.addWidget(self.search)
        bar.addWidget(self.inactive)
        bar.addStretch(1)
        bar.addWidget(button("New employee", "primary", self.new))
        self.root.addLayout(bar)
        self.table = DataTable([Col("employee_code", "Employee ID"), Col("name", "Name"),
                                Col("role_title", "Role"), Col("phone", "Phone"),
                                Col("email", "Email"), Col("joining_date", "Joined", "date"),
                                Col("status", "Status")], stretch="name")
        self.table.set_row_color(lambda r: None if r["is_active"] else C["faint"])
        self.table.activated.connect(self.edit)
        self.root.addWidget(self.table, 1)
        act = QHBoxLayout()
        act.addWidget(label("Employee records are separate from login accounts "
                            "(Users & Permissions).", "Faint"))
        act.addStretch(1)
        act.addWidget(button("Edit", None, lambda: self.edit(self.table.selected())))
        self.root.addLayout(act)

    def on_show(self):
        self.load()

    @ui_action
    def load(self):
        rows = self.ctx.services.staff.list_employees(self.ctx.user, self.search.text(),
                                                      self.inactive.isChecked())
        for r in rows:
            r["status"] = "Active" if r["is_active"] else "Inactive"
        self.table.set_rows(rows)

    def new(self):
        if FormDialog(self, "New employee", EMP_FIELDS, {"is_active": True},
                      lambda d: self.ctx.services.staff.save_employee(self.ctx.user, None, d),
                      width=520).exec():
            self.load()

    def edit(self, row):
        if not row:
            show_info(self, "Select an employee first.")
            return
        vals = dict(row)
        vals["base_salary"] = f"{row['base_salary']:.2f}" if row["base_salary"] is not None else ""
        if FormDialog(self, "Edit employee", EMP_FIELDS, vals,
                      lambda d: self.ctx.services.staff.save_employee(self.ctx.user, row["id"], d),
                      width=520).exec():
            self.load()


class AttendancePage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        bar.addWidget(label("Date", "Muted"))
        self.day = date_edit()
        self.day.dateChanged.connect(self.load)
        bar.addWidget(self.day)
        bar.addStretch(1)
        bar.addWidget(button("Save attendance", "primary", self.save))
        bar.addWidget(button("History…", None, self.history))
        self.root.addLayout(bar)
        self.root.addWidget(label("Set the status for each employee and optional check-in / "
                                  "check-out times (HH:MM, 24-hour). Only rows with a status "
                                  "are saved.", "Faint", wrap=True))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Employee ID", "Name", "Status", "Check-in",
                                              "Check-out", "Notes"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.root.addWidget(self.table, 1)
        self.rows = []

    def on_show(self):
        self.load()

    @ui_action
    def load(self):
        self.rows = self.ctx.services.staff.attendance_for_date(self.ctx.user,
                                                                pydate(self.day.date()))
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            for c, text in ((0, r["employee_code"]), (1, r["name"])):
                it = QTableWidgetItem(text)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(i, c, it)
            st = QComboBox()
            st.addItem("—", "")
            for s in ATTENDANCE_STATUSES:
                st.addItem(s, s)
            st.setCurrentIndex(max(0, st.findData(r["status"])))
            self.table.setCellWidget(i, 2, st)
            for c, key in ((3, "check_in"), (4, "check_out"), (5, "notes")):
                e = QLineEdit(r[key] or "")
                if c < 5:
                    e.setPlaceholderText("HH:MM")
                    e.setMaxLength(5)
                self.table.setCellWidget(i, c, e)
        if not self.rows:
            self.table.setRowCount(0)

    @ui_action
    def save(self):
        day = pydate(self.day.date())
        saved = 0
        for i, r in enumerate(self.rows):
            status = self.table.cellWidget(i, 2).currentData()
            if not status:
                continue
            self.ctx.services.staff.save_attendance(self.ctx.user, r["employee_id"], day, {
                "status": status, "check_in": self.table.cellWidget(i, 3).text(),
                "check_out": self.table.cellWidget(i, 4).text(),
                "notes": self.table.cellWidget(i, 5).text()})
            saved += 1
        self.ctx.toast(f"Attendance saved for {saved} employee(s)")
        self.load()

    @ui_action
    def history(self):
        from app.ui.dialogs.simple_list_dialog import ListDialog
        from app.utils.dates import preset_range
        a, b = preset_range("this_month")
        rows = self.ctx.services.staff.attendance_history(self.ctx.user, None, a, b)
        ListDialog(self, "Attendance — this month", [
            Col("date", "Date", "date"), Col("employee_code", "ID"), Col("employee", "Name"),
            Col("status", "Status"), Col("check_in", "In"), Col("check_out", "Out"),
            Col("notes", "Notes")], rows, stretch="notes").exec()


class LeavePage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        self.status = QComboBox()
        self.status.addItem("All statuses", None)
        for s in (LeaveStatus.PENDING, LeaveStatus.APPROVED, LeaveStatus.REJECTED):
            self.status.addItem(s, s)
        self.status.currentIndexChanged.connect(self.load)
        bar.addWidget(self.status)
        bar.addStretch(1)
        if ctx.can(Perm.MANAGE_LEAVE):
            bar.addWidget(button("New leave", "primary", self.new))
        if ctx.can(Perm.APPROVE_LEAVE):
            bar.addWidget(button("Leave types", None, self.types))
        self.root.addLayout(bar)
        self.table = DataTable([Col("employee", "Employee"), Col("leave_type", "Type"),
                                Col("start_date", "From", "date"), Col("end_date", "To", "date"),
                                Col("days", "Days", "int"), Col("reason", "Reason"),
                                Col("status", "Status"), Col("decision_note", "Note")],
                               stretch="reason")
        self.table.set_row_color(lambda r: C["warning"] if r["status"] == LeaveStatus.PENDING
                                 else C["faint"] if r["status"] == LeaveStatus.REJECTED else None)
        self.root.addWidget(self.table, 1)
        if ctx.can(Perm.APPROVE_LEAVE):
            act = QHBoxLayout()
            act.addStretch(1)
            act.addWidget(button("Approve", "success", lambda: self.decide(True)))
            act.addWidget(button("Reject", "danger", lambda: self.decide(False)))
            self.root.addLayout(act)

    def on_show(self):
        self.load()

    @ui_action
    def load(self):
        self.table.set_rows(self.ctx.services.staff.list_leave(self.ctx.user,
                                                               self.status.currentData()))

    @ui_action
    def new(self):
        emps = [(e["name"], e["id"]) for e in self.ctx.services.staff.list_employees(self.ctx.user)]
        types = [(t["name"], t["id"]) for t in self.ctx.services.staff.list_leave_types()]
        if not emps:
            show_info(self, "Add employees first (Employees page).")
            return
        if not types:
            show_info(self, "No leave types are configured yet. Ask an administrator or manager "
                            "to add leave types (Leave › Leave types).")
            return
        if FormDialog(self, "New leave", [
                Field("employee_id", "Employee", "combo", required=True, options=emps),
                Field("leave_type_id", "Leave type", "combo", required=True, options=types),
                Field("start_date", "From", "date", required=True),
                Field("end_date", "To", "date", required=True),
                Field("reason", "Reason", "multiline")],
                {"start_date": date.today(), "end_date": date.today()},
                lambda d: self.ctx.services.staff.create_leave(self.ctx.user, d)).exec():
            self.load()

    @ui_action
    def decide(self, approve: bool):
        r = self.table.selected()
        if not r:
            show_info(self, "Select a leave request first.")
            return
        note, ok = QInputDialog.getText(self, "Approve" if approve else "Reject",
                                        "Optional note:")
        if ok:
            self.ctx.services.staff.decide_leave(self.ctx.user, r["id"], approve, note)
            self.load()

    def types(self):
        from app.ui.dialogs.simple_list_dialog import ListDialog
        ctx = self.ctx

        class _Types(ListDialog):
            def __init__(self, parent):
                rows = ctx.services.staff.list_leave_types(include_inactive=True)
                for r in rows:
                    r["status"] = "Active" if r["is_active"] else "Inactive"
                super().__init__(parent, "Leave types", [Col("name", "Leave type"),
                                                         Col("status", "Status")], rows,
                                 subtitle="Configure the leave types your business uses. "
                                          "Double-click to edit.")
                self.t = self.findChild(DataTable)
                self.t.activated.connect(self.edit)
                self.layout().insertWidget(2, button("New leave type", "primary",
                                                     lambda: self.edit(None)))

            def edit(self, row):
                if FormDialog(self, "Leave type", [Field("name", "Name", required=True),
                                                   Field("is_active", "Active", "check")],
                              row or {"is_active": True},
                              lambda d: ctx.services.staff.save_leave_type(
                                  ctx.user, row["id"] if row else None, d)).exec():
                    rows = ctx.services.staff.list_leave_types(include_inactive=True)
                    for r in rows:
                        r["status"] = "Active" if r["is_active"] else "Inactive"
                    self.t.set_rows(rows)
        _Types(self).exec()


class PayrollPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.root.addWidget(label(
            "Internal Payroll Management — records the amounts you enter. It does not "
            "calculate statutory deductions (PF, ESI, professional tax, TDS) or produce "
            "statutory filings.", "Warning", wrap=True))
        bar = QHBoxLayout()
        self.range = DateRangeBar("this_year")
        self.range.changed.connect(self.load)
        bar.addWidget(self.range)
        bar.addStretch(1)
        bar.addWidget(button("New payroll entry", "primary", self.new))
        self.root.addLayout(bar)
        self.table = DataTable([
            Col("employee", "Employee"), Col("period_start", "From", "date"),
            Col("period_end", "To", "date"), Col("base_salary", "Base", "money"),
            Col("allowances", "Allowances", "money"), Col("deductions", "Deductions", "money"),
            Col("net_salary", "Net", "money"), Col("status", "Status"),
            Col("paid_date", "Paid on", "date"), Col("method", "Paid by"),
            Col("reference", "Reference")], stretch="employee")
        self.table.set_row_color(lambda r: C["faint"] if r["status"] == PayrollStatus.CANCELLED
                                 else C["warning"] if r["status"] == PayrollStatus.UNPAID else None)
        self.root.addWidget(self.table, 1)
        act = QHBoxLayout()
        self.total = label("", "SectionTitle")
        act.addWidget(self.total)
        act.addStretch(1)
        act.addWidget(button("Mark as paid", "success", self.mark_paid))
        act.addWidget(button("Cancel entry", "danger", self.cancel))
        self.root.addLayout(act)

    def on_show(self):
        self.load()

    @ui_action
    def load(self):
        a, b = self.range.range()
        rows = self.ctx.services.staff.list_payroll(self.ctx.user, a, b)
        self.table.set_rows(rows)
        self.total.setText(f"Total net (excluding cancelled): "
                           f"{self.ctx.money(self.ctx.services.staff.payroll_total(rows))}")

    @ui_action
    def new(self):
        emps = self.ctx.services.staff.list_employees(self.ctx.user)
        if not emps:
            show_info(self, "Add employees first.")
            return
        a, b = self.range.range()
        from app.utils.dates import preset_range
        ms, me = preset_range("this_month")
        base_by_emp = {e["id"]: e["base_salary"] for e in emps}
        first = emps[0]
        dlg = FormDialog(self, "New payroll entry", [
            Field("employee_id", "Employee", "combo", required=True,
                  options=[(e["name"], e["id"]) for e in emps]),
            Field("period_start", "Period from", "date", required=True),
            Field("period_end", "Period to", "date", required=True),
            Field("base_salary", "Base salary", "money", required=True),
            Field("allowances", "Allowances", "money"),
            Field("deductions", "Deductions", "money",
                  help="Enter any deductions yourself; none are calculated automatically."),
            Field("notes", "Notes", "multiline")],
            {"period_start": ms, "period_end": me,
             "base_salary": f"{first['base_salary']:.2f}" if first["base_salary"] else ""},
            lambda d: self.ctx.services.staff.create_payroll(self.ctx.user, d))
        combo = dlg.widgets["employee_id"]
        combo.currentIndexChanged.connect(lambda: dlg.widgets["base_salary"].setText(
            f"{base_by_emp.get(combo.currentData()):.2f}"
            if base_by_emp.get(combo.currentData()) is not None else ""))
        if dlg.exec():
            self.load()

    @ui_action
    def mark_paid(self):
        r = self.table.selected()
        if not r:
            show_info(self, "Select a payroll entry first.")
            return
        if r["status"] != PayrollStatus.UNPAID:
            show_info(self, "Only unpaid entries can be marked as paid.")
            return
        methods = [("— Not specified —", None)] + [
            (m["name"], m["id"]) for m in self.ctx.services.payment_methods.list()]
        cats = [(c["name"], c["id"]) for c in self.ctx.services.expenses.list_categories()]
        salaries = next((cid for name, cid in cats if name == "Salaries"), None)
        fields = [Field("paid_date", "Paid on", "date", required=True),
                  Field("method", "Paid by", "combo", options=methods),
                  Field("reference", "Reference")]
        can_exp = self.ctx.can(Perm.CREATE_EXPENSE)
        if can_exp:
            fields += [Field("record_expense", "Record as expense", "check",
                             help="Adds the net salary to Expenses so profit/loss includes it."),
                       Field("category", "Expense category", "combo", options=cats)]
        FormDialog(self, f"Mark paid — {r['employee']}", fields,
                   {"paid_date": date.today(), "record_expense": can_exp, "category": salaries},
                   lambda d: self.ctx.services.staff.mark_payroll_paid(
                       self.ctx.user, r["id"], paid_date=d["paid_date"],
                       payment_method_id=d["method"], reference=d["reference"],
                       record_expense=bool(d.get("record_expense")),
                       expense_category_id=d.get("category"))).exec()
        self.load()

    @ui_action
    def cancel(self):
        r = self.table.selected()
        if not r:
            show_info(self, "Select a payroll entry first.")
            return
        if confirm(self, f"Cancel the payroll entry for {r['employee']}? Any linked expense "
                         "will be marked void.", danger=True, yes_text="Cancel entry"):
            self.ctx.services.staff.cancel_payroll(self.ctx.user, r["id"])
            self.load()
