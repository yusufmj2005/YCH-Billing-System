"""Invoice / return-note PDF generation (A4 and 80 mm receipt)."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from app.config.constants import TaxMode
from app.printing.fonts import currency, fonts
from app.utils.dates import fmt_dt
from app.utils.money import ZERO, fmt_money, fmt_qty
from app.utils.words import amount_in_words

INK = colors.HexColor("#1F2328")
MUTED = colors.HexColor("#6B7280")
LINE = colors.HexColor("#D0D5DD")
HEAD_BG = colors.HexColor("#F2F4F7")


def _esc(text) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br/>"))


def _styles(base_size: float = 9):
    reg, bold, _ = fonts()
    return {
        "n": ParagraphStyle("n", fontName=reg, fontSize=base_size, leading=base_size * 1.3,
                            textColor=INK),
        "m": ParagraphStyle("m", fontName=reg, fontSize=base_size - 1,
                            leading=(base_size - 1) * 1.3, textColor=MUTED),
        "b": ParagraphStyle("b", fontName=bold, fontSize=base_size, leading=base_size * 1.3,
                            textColor=INK),
        "r": ParagraphStyle("r", fontName=reg, fontSize=base_size, leading=base_size * 1.3,
                            alignment=TA_RIGHT, textColor=INK),
        "rb": ParagraphStyle("rb", fontName=bold, fontSize=base_size, leading=base_size * 1.3,
                             alignment=TA_RIGHT, textColor=INK),
        "c": ParagraphStyle("c", fontName=reg, fontSize=base_size, leading=base_size * 1.3,
                            alignment=TA_CENTER, textColor=INK),
        "cb": ParagraphStyle("cb", fontName=bold, fontSize=base_size + 3,
                             leading=(base_size + 3) * 1.25, alignment=TA_CENTER, textColor=INK),
        "title": ParagraphStyle("title", fontName=bold, fontSize=base_size + 7,
                                leading=(base_size + 7) * 1.2, textColor=INK),
        "h": ParagraphStyle("h", fontName=bold, fontSize=base_size + 4,
                            leading=(base_size + 4) * 1.2, alignment=TA_RIGHT, textColor=INK),
    }


def _business_lines(settings: dict) -> list[str]:
    lines = []
    if settings.get("business_address"):
        lines.append(_esc(settings["business_address"]))
    contact = " | ".join(x for x in (settings.get("business_phone"),
                                     settings.get("business_email")) if x)
    if contact:
        lines.append(_esc(contact))
    if settings.get("business_gstin"):
        lines.append(f"GSTIN: {_esc(settings['business_gstin'])}")
    return lines


def _tax_breakdown(sale: dict) -> list[tuple[Decimal, Decimal, Decimal, Decimal, Decimal]]:
    groups: dict[Decimal, list[Decimal]] = {}
    for it in sale["items"]:
        g = groups.setdefault(it["tax_rate"], [ZERO, ZERO, ZERO, ZERO])
        g[0] += it["taxable_amount"]
        g[1] += it["cgst_amount"]
        g[2] += it["sgst_amount"]
        g[3] += it["igst_amount"]
    return [(rate, *vals) for rate, vals in sorted(groups.items())]


def build_invoice_pdf(sale: dict, settings: dict, out_path: Path,
                      logo: Path | None = None, paper: str | None = None) -> Path:
    paper = paper or settings.get("invoice_paper") or "A4"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if paper == "RECEIPT_80MM":
        return _build_receipt(sale, settings, out_path)
    return _build_a4(sale, settings, out_path, logo)


def _build_a4(sale: dict, settings: dict, out_path: Path, logo: Path | None) -> Path:
    st = _styles(9)
    cur = currency(settings.get("currency_symbol") or "")
    m = lambda v: fmt_money(v)  # noqa: E731
    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=14 * mm,
                            rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
                            title=f"Invoice {sale['invoice_no']}",
                            author=settings.get("business_name") or "")
    width = A4[0] - 28 * mm
    story = []

    # ---- header -----------------------------------------------------------------
    left = []
    if logo and Path(logo).is_file():
        try:
            img = Image(str(logo))
            ratio = img.imageWidth / float(img.imageHeight or 1)
            h = 16 * mm
            img.drawHeight, img.drawWidth = h, min(h * ratio, 50 * mm)
            img.hAlign = "LEFT"
            left.append(img)
            left.append(Spacer(1, 2 * mm))
        except Exception:
            pass
    left.append(Paragraph(_esc(settings.get("business_name")), st["title"]))
    left += [Paragraph(x, st["m"]) for x in _business_lines(settings)]
    title = settings.get("invoice_title") or "Invoice"
    right = [Paragraph(_esc(title), st["h"]), Spacer(1, 2 * mm),
             Paragraph(f"Invoice No: <b>{_esc(sale['invoice_no'])}</b>", st["r"]),
             Paragraph(f"Date: {fmt_dt(sale['created_at'])}", st["r"])]
    if sale.get("cashier"):
        right.append(Paragraph(f"Billed by: {_esc(sale['cashier'])}", st["r"]))
    if sale["tax_mode"] == TaxMode.INTER:
        right.append(Paragraph("Supply: Inter-state (IGST)", st["r"]))
    header = Table([[left, right]], colWidths=[width * 0.6, width * 0.4])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [header, Spacer(1, 5 * mm)]

    if sale["status"] == "VOIDED":
        story.append(Paragraph(f"<b>VOID</b> - this invoice was cancelled on "
                               f"{fmt_dt(sale.get('voided_at'))}. Reason: "
                               f"{_esc(sale.get('void_reason'))}", ParagraphStyle(
                                   "void", parent=st["b"], textColor=colors.HexColor("#C92A2A"))))
        story.append(Spacer(1, 3 * mm))

    # ---- bill to -------------------------------------------------------------------
    if sale.get("customer_name"):
        cust = [Paragraph("BILL TO", st["m"]), Paragraph(_esc(sale["customer_name"]), st["b"])]
        for key, label in (("customer_address", ""), ("customer_phone", "Phone: "),
                           ("customer_gstin", "GSTIN: ")):
            if sale.get(key):
                cust.append(Paragraph(label + _esc(sale[key]), st["n"]))
        story += cust + [Spacer(1, 4 * mm)]

    # ---- items ---------------------------------------------------------------------
    any_disc = any(it["discount_amount"] or it["bill_discount_share"] for it in sale["items"])
    head = ["#", "Item", "Qty", "Rate", "Discount", "Taxable", "Tax", "Amount"]
    widths = [8 * mm, None, 16 * mm, 22 * mm, 20 * mm, 24 * mm, 24 * mm, 26 * mm]
    if not any_disc:
        head.pop(4)
        widths.pop(4)
    fixed = sum(w for w in widths if w)
    widths[1] = width - fixed
    data = [[Paragraph(f"<b>{h}</b>", st["r"] if i >= 2 else st["n"]) for i, h in enumerate(head)]]
    for i, it in enumerate(sale["items"], 1):
        desc = _esc(it["product_name"])
        meta = " | ".join(x for x in (f"SKU {_esc(it['sku'])}" if it.get("sku") else "",
                                      f"HSN {_esc(it['hsn_code'])}" if it.get("hsn_code") else "")
                          if x)
        if meta:
            desc += f"<br/><font size=7 color='#6B7280'>{meta}</font>"
        if it["price_includes_tax"] and it["tax_rate"]:
            desc += "<br/><font size=7 color='#6B7280'>Rate incl. tax</font>"
        tax_txt = f"{m(it['tax_amount'])}<br/><font size=7 color='#6B7280'>" \
                  f"{fmt_qty(it['tax_rate'])}%</font>" if it["tax_rate"] else "-"
        row = [Paragraph(str(i), st["n"]), Paragraph(desc, st["n"]),
               Paragraph(f"{fmt_qty(it['quantity'])} {_esc(it['unit'])}", st["r"]),
               Paragraph(m(it["unit_price"]), st["r"]),
               Paragraph(m(it["discount_amount"] + it["bill_discount_share"]), st["r"]),
               Paragraph(m(it["taxable_amount"]), st["r"]), Paragraph(tax_txt, st["r"]),
               Paragraph(m(it["line_total"]), st["r"])]
        if not any_disc:
            row.pop(4)
        data.append(row)
    items = Table(data, colWidths=widths, repeatRows=1)
    items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [items, Spacer(1, 4 * mm)]

    # ---- totals ---------------------------------------------------------------------
    tot = [["Gross amount", m(sale["gross_total"])]]
    if sale["item_discount_total"]:
        tot.append(["Item discounts", "-" + m(sale["item_discount_total"])])
    if sale["bill_discount"]:
        tot.append(["Bill discount", "-" + m(sale["bill_discount"])])
    tot.append(["Taxable value", m(sale["taxable_total"])])
    if sale["tax_mode"] == TaxMode.INTER:
        tot.append(["IGST", m(sale["igst_total"])])
    else:
        tot.append(["CGST", m(sale["cgst_total"])])
        tot.append(["SGST", m(sale["sgst_total"])])
    if sale["round_off"]:
        tot.append(["Round off", m(sale["round_off"])])
    tot.append(["Grand total", f"{cur}{m(sale['grand_total'])}"])
    trows = [[Paragraph(a, st["n"]), Paragraph(b, st["r"])] for a, b in tot[:-1]]
    trows.append([Paragraph(tot[-1][0], st["b"]), Paragraph(tot[-1][1], st["rb"])])
    totals = Table(trows, colWidths=[40 * mm, 34 * mm])
    totals.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.8, INK),
                                ("TOPPADDING", (0, 0), (-1, -1), 2),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))

    # tax breakdown + payments on the left
    left_block = []
    breakdown = _tax_breakdown(sale)
    if any(r[0] for r in breakdown):
        inter = sale["tax_mode"] == TaxMode.INTER
        bh = ["Rate", "Taxable"] + (["IGST"] if inter else ["CGST", "SGST"])
        brows = [[Paragraph(f"<b>{h}</b>", st["m"]) for h in bh]]
        for rate, taxable, cg, sg, ig in breakdown:
            brows.append([Paragraph(f"{fmt_qty(rate)}%", st["m"]), Paragraph(m(taxable), st["m"])]
                         + ([Paragraph(m(ig), st["m"])] if inter
                            else [Paragraph(m(cg), st["m"]), Paragraph(m(sg), st["m"])]))
        bt = Table(brows, hAlign="LEFT")
        bt.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.4, LINE),
                                ("TOPPADDING", (0, 0), (-1, -1), 1),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
        left_block += [Paragraph("Tax summary", st["b"]), bt, Spacer(1, 3 * mm)]
    pays = [p for p in sale["payments"]]
    if pays:
        left_block.append(Paragraph("Payment", st["b"]))
        for p in pays:
            txt = f"{_esc(p['method'])}: {cur}{m(p['amount'])}"
            if p.get("description"):
                txt += f" ({_esc(p['description'])})"
            if p.get("reference"):
                txt += f" &nbsp;Ref: {_esc(p['reference'])}"
            left_block.append(Paragraph(txt, st["n"]))
    block = Table([[left_block, totals]], colWidths=[width - 76 * mm, 76 * mm])
    block.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(KeepTogether([block]))
    if (settings.get("currency_symbol") or "") in ("₹", "Rs", "Rs."):
        story += [Spacer(1, 3 * mm),
                  Paragraph(f"Amount in words: {amount_in_words(sale['grand_total'])}", st["n"])]
    if sale.get("returns"):
        story += [Spacer(1, 3 * mm), Paragraph(
            "Returns recorded against this invoice: " + ", ".join(
                f"{_esc(r['return_no'])} ({cur}{m(r['refund_total'])})" for r in sale["returns"]),
            st["m"])]
    story.append(Spacer(1, 8 * mm))
    if settings.get("invoice_footer"):
        story.append(Paragraph(_esc(settings["invoice_footer"]), st["c"]))
    story.append(Paragraph("This is a computer-generated invoice.", ParagraphStyle(
        "f", parent=st["m"], alignment=TA_CENTER)))
    doc.build(story)
    return out_path


def _build_receipt(sale: dict, settings: dict, out_path: Path) -> Path:
    st = _styles(8)
    cur = currency(settings.get("currency_symbol") or "")
    m = lambda v: fmt_money(v)  # noqa: E731
    width = 72 * mm
    story = [Paragraph(_esc(settings.get("business_name")), st["cb"])]
    story += [Paragraph(x, ParagraphStyle("cm", parent=st["m"], alignment=TA_CENTER))
              for x in _business_lines(settings)]
    story += [Spacer(1, 2 * mm),
              Paragraph(_esc(settings.get("invoice_title") or "Invoice"), ParagraphStyle(
                  "ct", parent=st["b"], alignment=TA_CENTER)),
              Paragraph(f"No: {_esc(sale['invoice_no'])}", st["n"]),
              Paragraph(f"Date: {fmt_dt(sale['created_at'])}", st["n"])]
    if sale["status"] == "VOIDED":
        story.append(Paragraph("<b>*** VOID ***</b>", st["c"]))
    if sale.get("customer_name"):
        story.append(Paragraph(f"Customer: {_esc(sale['customer_name'])}", st["n"]))
        if sale.get("customer_gstin"):
            story.append(Paragraph(f"GSTIN: {_esc(sale['customer_gstin'])}", st["n"]))
    rows = [[Paragraph("<b>Item</b>", st["n"]), Paragraph("<b>Qty</b>", st["r"]),
             Paragraph("<b>Amount</b>", st["r"])]]
    for it in sale["items"]:
        rows.append([Paragraph(f"{_esc(it['product_name'])}<br/><font size=6>@ "
                               f"{m(it['unit_price'])}"
                               + (f" | {fmt_qty(it['tax_rate'])}% tax" if it["tax_rate"] else "")
                               + "</font>", st["n"]),
                     Paragraph(fmt_qty(it["quantity"]), st["r"]),
                     Paragraph(m(it["line_total"]), st["r"])])
    t = Table(rows, colWidths=[46 * mm, 8 * mm, 18 * mm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.5, INK),
                           ("LINEBELOW", (0, -1), (-1, -1), 0.5, INK),
                           ("LEFTPADDING", (0, 0), (-1, -1), 1),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 1),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [Spacer(1, 2 * mm), t]
    tot = []
    if sale["item_discount_total"] or sale["bill_discount"]:
        tot.append(("Discount", "-" + m(sale["item_discount_total"] + sale["bill_discount"])))
    tot.append(("Taxable", m(sale["taxable_total"])))
    if sale["tax_mode"] == TaxMode.INTER:
        tot.append(("IGST", m(sale["igst_total"])))
    else:
        tot += [("CGST", m(sale["cgst_total"])), ("SGST", m(sale["sgst_total"]))]
    if sale["round_off"]:
        tot.append(("Round off", m(sale["round_off"])))
    trows = [[Paragraph(a, st["n"]), Paragraph(b, st["r"])] for a, b in tot]
    trows.append([Paragraph("<b>TOTAL</b>", st["b"]),
                  Paragraph(f"<b>{cur}{m(sale['grand_total'])}</b>", st["rb"])])
    tt = Table(trows, colWidths=[40 * mm, 32 * mm])
    tt.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 1),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 1)]))
    story.append(tt)
    for p in sale["payments"]:
        txt = f"{_esc(p['method'])}: {cur}{m(p['amount'])}"
        if p.get("reference"):
            txt += f" Ref {_esc(p['reference'])}"
        story.append(Paragraph(txt, st["n"]))
    if settings.get("invoice_footer"):
        story += [Spacer(1, 2 * mm), Paragraph(_esc(settings["invoice_footer"]), st["c"])]

    height = 10 * mm + sum(f.wrap(width, 10_000)[1] + 2 for f in story)
    doc = SimpleDocTemplate(str(out_path), pagesize=(80 * mm, max(height, 80 * mm)),
                            leftMargin=4 * mm, rightMargin=4 * mm, topMargin=4 * mm,
                            bottomMargin=4 * mm, title=f"Receipt {sale['invoice_no']}")
    doc.build(story)
    return out_path


def build_return_pdf(ret: dict, settings: dict, out_path: Path) -> Path:
    st = _styles(9)
    cur = currency(settings.get("currency_symbol") or "")
    m = lambda v: fmt_money(v)  # noqa: E731
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=14 * mm,
                            title=f"Return {ret['return_no']}")
    width = A4[0] - 28 * mm
    story = [Paragraph(_esc(settings.get("business_name")), st["title"])]
    story += [Paragraph(x, st["m"]) for x in _business_lines(settings)]
    story += [Spacer(1, 4 * mm), Paragraph("Return / Credit Note", st["h"]),
              Paragraph(f"Return No: <b>{_esc(ret['return_no'])}</b>", st["r"]),
              Paragraph(f"Against invoice: {_esc(ret['invoice_no'])}", st["r"]),
              Paragraph(f"Date: {fmt_dt(ret['created_at'])}", st["r"]), Spacer(1, 4 * mm)]
    if ret.get("customer_name"):
        story.append(Paragraph(f"Customer: {_esc(ret['customer_name'])}", st["n"]))
    rows = [[Paragraph(f"<b>{h}</b>", st["n"] if i == 0 else st["r"]) for i, h in
             enumerate(["Item", "Qty", "Taxable", "Tax", "Refund"])]]
    for it in ret["items"]:
        rows.append([Paragraph(_esc(it["product_name"]) + ("" if it["restocked"] else
                                                          " <font size=7>(not restocked)</font>"),
                               st["n"]),
                     Paragraph(fmt_qty(it["quantity"]), st["r"]),
                     Paragraph(m(it["taxable_amount"]), st["r"]),
                     Paragraph(m(it["tax_amount"]), st["r"]),
                     Paragraph(m(it["refund_amount"]), st["r"])])
    t = Table(rows, colWidths=[width - 100 * mm, 20 * mm, 26 * mm, 26 * mm, 28 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE)]))
    story += [Spacer(1, 3 * mm), t, Spacer(1, 3 * mm),
              Paragraph(f"<b>Total refund: {cur}{m(ret['refund_total'])}</b>", st["rb"]),
              Spacer(1, 2 * mm), Paragraph(f"Reason: {_esc(ret['reason'])}", st["n"])]
    for r in ret["refunds"]:
        txt = f"Refunded via {_esc(r['method'])}: {cur}{m(r['amount'])}"
        if r.get("reference"):
            txt += f" Ref {_esc(r['reference'])}"
        story.append(Paragraph(txt, st["n"]))
    doc.build(story)
    return out_path
