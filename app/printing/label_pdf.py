"""Barcode label sheets (PDF), printable on any Windows printer."""
from __future__ import annotations

from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.barcode.codes import is_valid_ean13
from app.printing.fonts import currency, fonts
from app.utils.money import fmt_money

# name -> (page size, columns, rows, label w, label h, left margin, top margin)
LABEL_LAYOUTS = {
    "A4 sheet - 3 x 8 (70 x 37 mm)": (A4, 3, 8, 70 * mm, 37 * mm, 0, 0.5 * mm),
    "A4 sheet - 4 x 10 (48.5 x 25.4 mm)": (A4, 4, 10, 48.5 * mm, 25.4 * mm, 8 * mm, 21.5 * mm),
    "Single label 50 x 25 mm (label printer)": ((50 * mm, 25 * mm), 1, 1, 50 * mm, 25 * mm, 0, 0),
    "Single label 38 x 25 mm (label printer)": ((38 * mm, 25 * mm), 1, 1, 38 * mm, 25 * mm, 0, 0),
}


def _barcode_drawing(value: str, width: float, height: float):
    kind = "EAN13" if is_valid_ean13(value) else "Code128"
    d = createBarcodeDrawing(kind, value=value, barHeight=height, humanReadable=False,
                             **({"barWidth": 0.9} if kind == "Code128" else {}))
    scale = min(width / d.width, 1.6)
    d.scale(scale, 1)
    d.width *= scale
    return d


def build_labels_pdf(items: list[dict], out_path: Path, layout: str, settings: dict,
                     show_price: bool = True, show_name: bool = True) -> Path:
    """items: [{'name','barcode','price','copies'}]"""
    page, cols, rows, lw, lh, left, top = LABEL_LAYOUTS[layout]
    reg, bold, _ = fonts()
    cur = currency(settings.get("currency_symbol") or "")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out_path), pagesize=page)
    c.setTitle("Barcode labels")
    labels = [it for it in items for _ in range(max(1, int(it.get("copies", 1))))]
    per_page = cols * rows
    for i, it in enumerate(labels):
        if i and i % per_page == 0:
            c.showPage()
        slot = i % per_page
        col, row = slot % cols, slot // cols
        x = left + col * lw
        y = page[1] - top - (row + 1) * lh
        pad = 2 * mm
        cy = y + lh - pad
        if show_name:
            size = 7 if lh < 30 * mm else 8
            c.setFont(bold, size)
            name = it["name"]
            while c.stringWidth(name, bold, size) > lw - 2 * pad and len(name) > 4:
                name = name[:-2]
            if name != it["name"]:
                name = name.rstrip() + "…"
            cy -= size
            c.drawCentredString(x + lw / 2, cy, name)
            cy -= 2
        if show_price and it.get("price") is not None:
            cy -= 8
            c.setFont(bold, 8)
            c.drawCentredString(x + lw / 2, cy, f"{cur}{fmt_money(it['price'])}")
            cy -= 2
        text_h = 7
        bottom = y + pad + text_h + 1
        bar_h = max(5 * mm, cy - bottom - 1)
        d = _barcode_drawing(it["barcode"], lw - 2 * pad, bar_h)
        renderPDF.draw(d, c, x + (lw - d.width) / 2, bottom)
        c.setFont(reg, 6.5)
        c.drawCentredString(x + lw / 2, y + pad, it["barcode"])
    c.save()
    return out_path
