"""Invoice / return document actions shared by POS, Sales and Returns."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from app.printing.invoice_pdf import build_invoice_pdf, build_return_pdf
from app.printing.printer import print_pdf
from app.ui.context import AppContext
from app.ui.widgets.common import show_error


def invoice_pdf(ctx: AppContext, sale_id: int, paper: str | None = None) -> Path:
    sale = ctx.services.sales.get_sale(ctx.user, sale_id)
    settings = ctx.services.settings.get_all()
    suffix = "-receipt" if (paper or settings.get("invoice_paper")) == "RECEIPT_80MM" else ""
    out = ctx.export_path("invoices", f"{sale['invoice_no']}{suffix}.pdf")
    return build_invoice_pdf(sale, settings, out, logo=ctx.services.settings.logo_file(),
                             paper=paper)


def open_invoice(ctx: AppContext, parent, sale_id: int, paper: str | None = None) -> None:
    path = invoice_pdf(ctx, sale_id, paper)
    if not ctx.open_file(path):
        show_error(parent, f"No PDF viewer is available. The invoice was saved as {path.name} "
                           "in the exports folder.")


def print_invoice(ctx: AppContext, parent, sale_id: int, ask: bool = True) -> bool:
    return print_pdf(parent, invoice_pdf(ctx, sale_id), ask=ask, title="Print invoice")


def save_invoice_as(ctx: AppContext, parent, sale_id: int) -> None:
    path = invoice_pdf(ctx, sale_id)
    target, _ = QFileDialog.getSaveFileName(parent, "Save invoice as PDF",
                                            str(Path.home() / "Documents" / path.name),
                                            "PDF files (*.pdf)")
    if target:
        shutil.copyfile(path, target)
        ctx.toast(f"Saved {Path(target).name}")


def return_pdf(ctx: AppContext, return_id: int) -> Path:
    ret = ctx.services.returns.get_return(ctx.user, return_id)
    out = ctx.export_path("returns", f"{ret['return_no']}.pdf")
    return build_return_pdf(ret, ctx.services.settings.get_all(), out)
