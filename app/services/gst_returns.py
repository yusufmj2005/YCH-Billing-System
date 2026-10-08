"""GSTR-1 working reports for the accountant.

These group the tax already recorded on every invoice line into the sections
of the GSTR-1 return. They do not recalculate anything, and they are not the
portal's JSON upload; the accountant reviews them and files the return.

Sections:
  b2b        invoices to customers with a GSTIN (one row per invoice and rate)
  b2c        all other sales, summarised by supply type and rate, net of returns
  cdnr       credit notes (returns) against B2B invoices
  hsn        HSN summary (B2B / B2C), net of returns
  docs       documents issued: invoice and return number ranges, cancelled count
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import case, func, select

from app.config.constants import SaleStatus, TaxMode
from app.models import ReturnItem, Sale, SaleItem, SaleReturn
from app.reports.base import Col, ReportResult
from app.services.settings_service import get_settings
from app.utils.dates import day_end_exclusive, day_start
from app.utils.money import ZERO

STATE_CODES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan",
    "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu",
    "34": "Puducherry", "35": "Andaman & Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory",
}

NOTE = ("Working report built from recorded invoices for your accountant; it is not the GST "
        "portal's upload file. Check every figure before filing.")
_TAX_KEYS = ("taxable", "igst", "cgst", "sgst")


def state_of(gstin: str | None) -> str:
    """'33-Tamil Nadu' from a GSTIN's first two digits ('' if unknown)."""
    code = (gstin or "")[:2]
    return f"{code}-{STATE_CODES[code]}" if code in STATE_CODES else ""


def _rng(date_from: date, date_to: date):
    return day_start(date_from), day_end_exclusive(date_to)


def _home_state(s) -> str:
    return state_of(get_settings(s).get("business_gstin")) or "Business state"


def _tax_cols() -> list[Col]:
    return [Col("taxable", "Taxable value", "money"), Col("igst", "IGST", "money"),
            Col("cgst", "CGST", "money"), Col("sgst", "SGST", "money")]


def _totals(rows: list[dict], label_key: str, label: str, extra=()) -> dict:
    t = {label_key: label}
    for k in (*_TAX_KEYS, *extra):
        t[k] = sum((r[k] for r in rows), ZERO)
    return t


def _completed(start, end):
    return (Sale.status == SaleStatus.COMPLETED, Sale.created_at >= start,
            Sale.created_at < end)


def b2b(s, date_from: date, date_to: date) -> ReportResult:
    start, end = _rng(date_from, date_to)
    data = s.execute(
        select(Sale.customer_gstin, Sale.customer_name, Sale.invoice_no, Sale.created_at,
               Sale.grand_total, Sale.tax_mode, SaleItem.tax_rate,
               func.sum(SaleItem.taxable_amount), func.sum(SaleItem.igst_amount),
               func.sum(SaleItem.cgst_amount), func.sum(SaleItem.sgst_amount))
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .where(*_completed(start, end), func.coalesce(Sale.customer_gstin, "") != "")
        .group_by(Sale.id, SaleItem.tax_rate)
        .order_by(Sale.invoice_number, SaleItem.tax_rate)).all()
    rows = [{"gstin": g, "customer": n or "", "invoice_no": no, "date": dt.date(),
             "value": val, "pos": state_of(g),
             "type": "Inter-state" if mode == TaxMode.INTER else "Intra-state",
             "rate": rate, "taxable": tx or ZERO, "igst": ig or ZERO, "cgst": cg or ZERO,
             "sgst": sg or ZERO}
            for g, n, no, dt, val, mode, rate, tx, ig, cg, sg in data]
    return ReportResult("GSTR-1: B2B invoices", [
        Col("gstin", "Customer GSTIN"), Col("customer", "Customer"),
        Col("invoice_no", "Invoice"), Col("date", "Date", "date"),
        Col("value", "Invoice value", "money"), Col("pos", "Place of supply"),
        Col("type", "Supply"), Col("rate", "Rate", "pct"), *_tax_cols()], rows,
        _totals(rows, "gstin", "Total"),
        notes=[NOTE, "Sales to customers with a GSTIN on the invoice. One row per invoice and "
                     "tax rate. Invoice value is repeated on each rate row of the same invoice."])


def b2c(s, date_from: date, date_to: date) -> ReportResult:
    start, end = _rng(date_from, date_to)
    home = _home_state(s)
    no_gstin = func.coalesce(Sale.customer_gstin, "") == ""
    sold = s.execute(
        select(Sale.tax_mode, SaleItem.tax_rate, func.sum(SaleItem.taxable_amount),
               func.sum(SaleItem.igst_amount), func.sum(SaleItem.cgst_amount),
               func.sum(SaleItem.sgst_amount))
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .where(*_completed(start, end), no_gstin)
        .group_by(Sale.tax_mode, SaleItem.tax_rate)).all()
    returned = s.execute(
        select(Sale.tax_mode, SaleItem.tax_rate, func.sum(ReturnItem.taxable_amount),
               func.sum(ReturnItem.igst_amount), func.sum(ReturnItem.cgst_amount),
               func.sum(ReturnItem.sgst_amount))
        .select_from(ReturnItem).join(SaleItem, ReturnItem.sale_item_id == SaleItem.id)
        .join(SaleReturn, ReturnItem.return_id == SaleReturn.id)
        .join(Sale, SaleReturn.sale_id == Sale.id)
        .where(SaleReturn.created_at >= start, SaleReturn.created_at < end, no_gstin)
        .group_by(Sale.tax_mode, SaleItem.tax_rate)).all()
    acc: dict = {}
    for sign, data in ((1, sold), (-1, returned)):
        for mode, rate, *vals in data:
            r = acc.setdefault((mode, rate), {
                "type": "Inter-state" if mode == TaxMode.INTER else "Intra-state",
                "pos": "Other state (not recorded)" if mode == TaxMode.INTER else home,
                "rate": rate, **{k: ZERO for k in _TAX_KEYS}})
            for k, val in zip(_TAX_KEYS, vals):
                r[k] += sign * (val or ZERO)
    rows = [acc[k] for k in sorted(acc, key=lambda k: (k[0], k[1]))]
    return ReportResult("GSTR-1: B2C summary", [
        Col("type", "Supply"), Col("pos", "Place of supply"), Col("rate", "Rate", "pct"),
        *_tax_cols()], rows, _totals(rows, "type", "Total"),
        notes=[NOTE, "Sales without a customer GSTIN, net of returns made in the period.",
               "Inter-state B2C invoices above the large-invoice limit (currently Rs 1 lakh) "
               "must be reported invoice-wise; find them in the Sales register with tax type "
               "Inter-state."])


def credit_notes_b2b(s, date_from: date, date_to: date) -> ReportResult:
    start, end = _rng(date_from, date_to)
    data = s.execute(
        select(Sale.customer_gstin, Sale.customer_name, SaleReturn.return_no,
               SaleReturn.created_at, Sale.invoice_no, Sale.created_at, SaleReturn.refund_total,
               SaleItem.tax_rate, func.sum(ReturnItem.taxable_amount),
               func.sum(ReturnItem.igst_amount), func.sum(ReturnItem.cgst_amount),
               func.sum(ReturnItem.sgst_amount))
        .select_from(ReturnItem).join(SaleItem, ReturnItem.sale_item_id == SaleItem.id)
        .join(SaleReturn, ReturnItem.return_id == SaleReturn.id)
        .join(Sale, SaleReturn.sale_id == Sale.id)
        .where(SaleReturn.created_at >= start, SaleReturn.created_at < end,
               func.coalesce(Sale.customer_gstin, "") != "")
        .group_by(SaleReturn.id, SaleItem.tax_rate)
        .order_by(SaleReturn.id, SaleItem.tax_rate)).all()
    rows = [{"gstin": g, "customer": n or "", "note_no": rno, "note_date": rdt.date(),
             "invoice_no": ino, "invoice_date": idt.date(), "value": val, "pos": state_of(g),
             "rate": rate, "taxable": tx or ZERO, "igst": ig or ZERO, "cgst": cg or ZERO,
             "sgst": sg or ZERO}
            for g, n, rno, rdt, ino, idt, val, rate, tx, ig, cg, sg in data]
    return ReportResult("GSTR-1: Credit notes (B2B)", [
        Col("gstin", "Customer GSTIN"), Col("customer", "Customer"),
        Col("note_no", "Credit note"), Col("note_date", "Note date", "date"),
        Col("invoice_no", "Original invoice"), Col("invoice_date", "Invoice date", "date"),
        Col("value", "Note value", "money"), Col("pos", "Place of supply"),
        Col("rate", "Rate", "pct"), *_tax_cols()], rows, _totals(rows, "gstin", "Total"),
        notes=[NOTE, "Returns against invoices issued to customers with a GSTIN. Returns from "
                     "other customers are already netted in the B2C summary. Note value "
                     "includes any invoice round-off refunded."])


def hsn_summary(s, date_from: date, date_to: date) -> ReportResult:
    start, end = _rng(date_from, date_to)
    is_b2b = func.coalesce(Sale.customer_gstin, "") != ""
    sold = s.execute(
        select(is_b2b, SaleItem.hsn_code, SaleItem.unit, SaleItem.tax_rate,
               func.sum(SaleItem.quantity), func.sum(SaleItem.taxable_amount),
               func.sum(SaleItem.igst_amount), func.sum(SaleItem.cgst_amount),
               func.sum(SaleItem.sgst_amount))
        .join(Sale, SaleItem.sale_id == Sale.id).where(*_completed(start, end))
        .group_by(is_b2b, SaleItem.hsn_code, SaleItem.unit, SaleItem.tax_rate)).all()
    returned = s.execute(
        select(is_b2b, SaleItem.hsn_code, SaleItem.unit, SaleItem.tax_rate,
               func.sum(ReturnItem.quantity), func.sum(ReturnItem.taxable_amount),
               func.sum(ReturnItem.igst_amount), func.sum(ReturnItem.cgst_amount),
               func.sum(ReturnItem.sgst_amount))
        .select_from(ReturnItem).join(SaleItem, ReturnItem.sale_item_id == SaleItem.id)
        .join(SaleReturn, ReturnItem.return_id == SaleReturn.id)
        .join(Sale, SaleReturn.sale_id == Sale.id)
        .where(SaleReturn.created_at >= start, SaleReturn.created_at < end)
        .group_by(is_b2b, SaleItem.hsn_code, SaleItem.unit, SaleItem.tax_rate)).all()
    acc: dict = defaultdict(lambda: None)
    for sign, data in ((1, sold), (-1, returned)):
        for b2b_flag, hsn, unit, rate, q, *vals in data:
            key = (bool(b2b_flag), hsn or "", unit or "", rate)
            if acc[key] is None:
                acc[key] = {"supply": "B2B" if b2b_flag else "B2C",
                            "hsn": hsn or "(no HSN code)", "unit": unit or "", "rate": rate,
                            "qty": ZERO, **{k: ZERO for k in _TAX_KEYS}}
            r = acc[key]
            r["qty"] += sign * (q or ZERO)
            for k, val in zip(_TAX_KEYS, vals):
                r[k] += sign * (val or ZERO)
    rows = [acc[k] for k in sorted(acc, key=lambda k: (k[0], k[1], k[3], k[2]))]
    for r in rows:
        r["tax"] = r["igst"] + r["cgst"] + r["sgst"]
    missing = any(r["hsn"] == "(no HSN code)" for r in rows)
    notes = [NOTE, "Net of returns made in the period, split B2B / B2C. Quantity is in each "
                   "product's unit; map units to GST UQC codes (e.g. pcs = NOS) when filing."]
    if missing:
        notes.append("Some products have no HSN/SAC code. Add it in Products so future "
                     "invoices carry it.")
    return ReportResult("GSTR-1: HSN summary", [
        Col("supply", "Supply"), Col("hsn", "HSN/SAC"), Col("unit", "Unit"),
        Col("rate", "Rate", "pct"), Col("qty", "Quantity", "qty"), *_tax_cols(),
        Col("tax", "Total tax", "money")], rows,
        _totals(rows, "supply", "Total", extra=("tax",)), notes=notes)


def documents_issued(s, date_from: date, date_to: date) -> ReportResult:
    start, end = _rng(date_from, date_to)
    rows = []
    inv = s.execute(
        select(func.min(Sale.invoice_number), func.max(Sale.invoice_number), func.count(Sale.id),
               func.sum(case((Sale.status == SaleStatus.VOIDED, 1), else_=0)))
        .where(Sale.created_at >= start, Sale.created_at < end)).one()
    if inv[2]:
        first = s.scalar(select(Sale.invoice_no).where(Sale.invoice_number == inv[0],
                                                       Sale.created_at >= start,
                                                       Sale.created_at < end))
        last = s.scalar(select(Sale.invoice_no).where(Sale.invoice_number == inv[1],
                                                      Sale.created_at >= start,
                                                      Sale.created_at < end))
        rows.append({"doc": "Invoices for outward supply", "from": first, "to": last,
                     "total": inv[2], "cancelled": inv[3] or 0, "net": inv[2] - (inv[3] or 0)})
    ret = s.execute(
        select(func.min(SaleReturn.id), func.max(SaleReturn.id), func.count(SaleReturn.id))
        .where(SaleReturn.created_at >= start, SaleReturn.created_at < end)).one()
    if ret[2]:
        rows.append({"doc": "Credit notes (returns)",
                     "from": s.get(SaleReturn, ret[0]).return_no,
                     "to": s.get(SaleReturn, ret[1]).return_no,
                     "total": ret[2], "cancelled": 0, "net": ret[2]})
    return ReportResult("GSTR-1: Documents issued", [
        Col("doc", "Document"), Col("from", "From"), Col("to", "To"),
        Col("total", "Total", "int"), Col("cancelled", "Cancelled", "int"),
        Col("net", "Net issued", "int")], rows, None,
        notes=[NOTE, "Voided invoices count as cancelled; their numbers are never reused."])
