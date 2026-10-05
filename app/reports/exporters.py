"""CSV and PDF export of ReportResult tables."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.printing.fonts import fonts
from app.reports.base import ReportResult, format_value


def _safe_csv(value: str) -> str:
    # Prevent spreadsheet formula injection when the CSV is opened in Excel.
    if value and value[0] in "=+-@" and not value.lstrip("-").replace(".", "").replace(",", "").isdigit():
        return "'" + value
    return value


def export_csv(report: ReportResult, path: Path) -> Path:
    path = Path(path)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([report.title])
        if report.subtitle:
            w.writerow([report.subtitle])
        w.writerow([])
        w.writerow([c.label for c in report.columns])
        for r in report.rows:
            w.writerow([_safe_csv(format_value(r.get(c.key), c.kind).replace(",", ""))
                        if c.numeric else _safe_csv(format_value(r.get(c.key), c.kind))
                        for c in report.columns])
        if report.totals:
            w.writerow([format_value(report.totals.get(c.key), c.kind).replace(",", "")
                        if c.numeric else format_value(report.totals.get(c.key), c.kind)
                        for c in report.columns])
        for label, value in report.summary:
            w.writerow([label, format_value(value, "money") if not isinstance(value, str)
                        else value])
        for n in report.notes:
            w.writerow([n])
    return path


def export_pdf(report: ReportResult, path: Path, business_name: str = "") -> Path:
    reg, bold, _ = fonts()
    path = Path(path)
    wide = len(report.columns) > 6
    page = landscape(A4) if wide else A4
    doc = SimpleDocTemplate(str(path), pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, title=report.title)
    small = ParagraphStyle("s", fontName=reg, fontSize=7.5, leading=9.5)
    small_r = ParagraphStyle("sr", parent=small, alignment=2)
    small_b = ParagraphStyle("sb", parent=small, fontName=bold)
    small_br = ParagraphStyle("sbr", parent=small_b, alignment=2)
    story = []
    if business_name:
        story.append(Paragraph(business_name, ParagraphStyle("bn", fontName=bold, fontSize=11)))
    story.append(Paragraph(report.title, ParagraphStyle("t", fontName=bold, fontSize=15,
                                                         leading=19)))
    sub = report.subtitle + ("  •  " if report.subtitle else "") + \
        f"Generated {datetime.now():%d-%m-%Y %H:%M}"
    story += [Paragraph(sub, ParagraphStyle("st", fontName=reg, fontSize=8.5,
                                            textColor=colors.HexColor("#6B7280"))),
              Spacer(1, 5 * mm)]
    if report.summary:
        srows = [[Paragraph(label, small), Paragraph(
            value if isinstance(value, str) else format_value(value, "money"), small_r)]
            for label, value in report.summary]
        st = Table(srows, hAlign="LEFT", colWidths=[80 * mm, 40 * mm])
        story += [st, Spacer(1, 4 * mm)]
    head = [Paragraph(c.label, small_br if c.numeric else small_b) for c in report.columns]
    body = [[Paragraph(format_value(r.get(c.key), c.kind).replace("&", "&amp;")
                       .replace("<", "&lt;"), small_r if c.numeric else small)
             for c in report.columns] for r in report.rows]
    data = [head] + body
    if report.totals:
        data.append([Paragraph(format_value(report.totals.get(c.key), c.kind),
                               small_br if c.numeric else small_b) for c in report.columns])
    if not report.rows:
        data.append([Paragraph("No records for the selected filters.", small)]
                    + [""] * (len(report.columns) - 1))
    t = Table(data, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F4F7")),
             ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#D0D5DD")),
             ("VALIGN", (0, 0), (-1, -1), "TOP")]
    if report.totals:
        style.append(("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black))
    t.setStyle(TableStyle(style))
    story.append(t)
    if report.notes:
        story.append(Spacer(1, 5 * mm))
        for n in report.notes:
            story.append(Paragraph("• " + n, ParagraphStyle(
                "n", fontName=reg, fontSize=7.5, leading=10,
                textColor=colors.HexColor("#4B5563"))))
    doc.build(story)
    return path
