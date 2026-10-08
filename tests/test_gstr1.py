"""GSTR-1 working reports: sections are correct and reconcile with the tax summary."""
from datetime import date
from decimal import Decimal as D

import pytest

from app.config.constants import PaymentKind
from app.reports.exporters import export_csv
from app.services.errors import ValidationError
from app.services.gst_returns import state_of
from app.services.return_service import ReturnLineRequest, ReturnRequest
from app.services.sales_service import PaymentRequest, SaleLineRequest, SaleRequest

TODAY = date.today()


def _sale(services, admin, methods, lines, **kw):
    req = SaleRequest(lines=[SaleLineRequest(p, D(q)) for p, q in lines], **kw)
    with services.db.session() as s:
        from app.services.settings_service import get_settings
        total = services.sales.build_cart(s, req, get_settings(s))[2].grand_total
    req.payments = [PaymentRequest(methods[PaymentKind.CASH], total)]
    return services.sales.create_sale(admin, req)


def _return(services, admin, methods, sale_id, idx, qty):
    item = services.sales.get_sale(admin, sale_id)["items"][idx]
    line = [ReturnLineRequest(item["id"], D(qty))]
    refund = services.returns.preview(admin, sale_id, line)["refund_total"]
    return services.returns.create_return(admin, ReturnRequest(
        sale_id, line, "gst test", [PaymentRequest(methods[PaymentKind.CASH], refund)]))


@pytest.fixture()
def month(services, admin, make_product, methods, taxes):
    services.settings.update(admin, {"business_gstin": "33ABCDE1234F1Z5"})
    yarn = make_product(price="224", stock="50", tax_id=taxes["Test GST 12"], inclusive=True,
                        hsn_code="5109", unit="ball")
    hook = make_product(price="100", stock="50", tax_id=taxes["Test GST 5"], inclusive=False,
                        hsn_code="7319")
    kit = make_product(price="300", stock="50")                     # no HSN, no tax
    tn = services.partners.save_customer(admin, None, {"name": "Chennai Crafts",
                                                       "gstin": "33AAAAA1111A1Z1"})
    ka = services.partners.save_customer(admin, None, {"name": "Bengaluru Knits",
                                                       "gstin": "29BBBBB2222B1Z2"})
    walkin = services.partners.save_customer(admin, None, {"name": "Walk-in Regular"})
    s = {
        "b2b_intra": _sale(services, admin, methods, [(yarn, 2), (hook, 1)], customer_id=tn),
        "b2b_inter": _sale(services, admin, methods, [(yarn, 1)], customer_id=ka,
                           tax_mode="INTER"),
        "b2c_1": _sale(services, admin, methods, [(yarn, 3), (kit, 1)]),
        "b2c_2": _sale(services, admin, methods, [(hook, 4)], customer_id=walkin),
        "b2c_inter": _sale(services, admin, methods, [(hook, 1)], tax_mode="INTER"),
        "void": _sale(services, admin, methods, [(yarn, 1)]),
    }
    services.sales.void_sale(admin, s["void"]["sale_id"], "mistake")
    _return(services, admin, methods, s["b2b_intra"]["sale_id"], 0, 1)    # B2B credit note
    _return(services, admin, methods, s["b2c_2"]["sale_id"], 0, 2)        # B2C return
    return s


def _r(services, admin, section):
    return services.reports.gstr1(admin, section, TODAY, TODAY)


def test_state_codes():
    assert state_of("33ABCDE1234F1Z5") == "33-Tamil Nadu"
    assert state_of("29BBBBB2222B1Z2") == "29-Karnataka"
    assert state_of("") == state_of(None) == state_of("99XXXXX") == ""


def test_sections_reconcile_with_tax_summary(services, admin, month):
    b2b, b2c, cdnr, hsn = (_r(services, admin, k) for k in ("b2b", "b2c", "cdnr", "hsn"))
    tax = services.reports.tax_summary(admin, TODAY, TODAY).totals
    for k in ("taxable", "igst", "cgst", "sgst"):
        assert b2b.totals[k] + b2c.totals[k] - cdnr.totals[k] == tax[k], k
        assert hsn.totals[k] == tax[k], k


def test_b2b_rows(services, admin, month):
    rows = _r(services, admin, "b2b").rows
    assert {r["invoice_no"] for r in rows} == {month["b2b_intra"]["invoice_no"],
                                               month["b2b_inter"]["invoice_no"]}
    intra = [r for r in rows if r["invoice_no"] == month["b2b_intra"]["invoice_no"]]
    assert len(intra) == 2                                   # one row per rate (5% and 12%)
    assert all(r["pos"] == "33-Tamil Nadu" and r["igst"] == 0 and r["cgst"] > 0 for r in intra)
    inter = next(r for r in rows if r["invoice_no"] == month["b2b_inter"]["invoice_no"])
    assert inter["pos"] == "29-Karnataka" and inter["type"] == "Inter-state"
    assert inter["igst"] > 0 and inter["cgst"] == inter["sgst"] == 0
    assert inter["taxable"] == D("200.00") and inter["igst"] == D("24.00")


def test_b2c_is_net_of_returns_and_excludes_voids(services, admin, month):
    rows = _r(services, admin, "b2c").rows
    hook5 = next(r for r in rows if r["type"] == "Intra-state" and r["rate"] == D(5))
    assert hook5["taxable"] == D("200.00")                  # 4 sold, 2 returned
    assert hook5["pos"] == "33-Tamil Nadu"
    yarn12 = next(r for r in rows if r["type"] == "Intra-state" and r["rate"] == D(12))
    assert yarn12["taxable"] == D("600.00")                 # 3 x 200; voided sale excluded
    inter = next(r for r in rows if r["type"] == "Inter-state")
    assert inter["igst"] == D("5.00") and inter["pos"].startswith("Other state")


def test_credit_notes_only_for_registered_customers(services, admin, month):
    rows = _r(services, admin, "cdnr").rows
    assert len(rows) == 1
    note = rows[0]
    assert note["gstin"] == "33AAAAA1111A1Z1"
    assert note["invoice_no"] == month["b2b_intra"]["invoice_no"]
    assert note["taxable"] == D("200.00") and note["rate"] == D(12)


def test_hsn_summary(services, admin, month):
    rep = _r(services, admin, "hsn")
    by = {(r["supply"], r["hsn"]): r for r in rep.rows}
    assert by[("B2B", "5109")]["qty"] == D(2)               # 2 + 1 sold, 1 returned
    assert by[("B2C", "5109")]["qty"] == D(3)
    assert by[("B2C", "7319")]["qty"] == D(3)               # 4 + 1 sold, 2 returned
    assert by[("B2C", "(no HSN code)")]["taxable"] == D("300.00")
    assert any("no HSN/SAC code" in n for n in rep.notes)


def test_documents_issued(services, admin, month):
    rows = {r["doc"]: r for r in _r(services, admin, "docs").rows}
    inv = rows["Invoices for outward supply"]
    assert (inv["from"], inv["to"]) == ("T-000001", "T-000006")
    assert (inv["total"], inv["cancelled"], inv["net"]) == (6, 1, 5)
    assert rows["Credit notes (returns)"]["total"] == 2


def test_empty_period_and_bad_section(services, admin):
    for k in ("b2b", "b2c", "cdnr", "hsn", "docs"):
        assert _r(services, admin, k).rows == []
    with pytest.raises(ValidationError):
        _r(services, admin, "gstr3b")


def test_exports_to_csv(services, admin, month, tmp_path):
    for k in ("b2b", "b2c", "cdnr", "hsn", "docs"):
        out = export_csv(_r(services, admin, k), tmp_path / f"{k}.csv")
        assert out.exists() and out.stat().st_size > 0


def test_reports_page_runs_gst_reports(services, admin, month):
    from app.ui.pages.reports import R
    keys = [k for k, v in R.items() if v[0] == "GST returns"]
    assert len(keys) == 5
    for k in keys:
        rep = R[k][4](services.reports, admin, {"range": (TODAY, TODAY)})
        assert rep.title.startswith("GSTR-1")
