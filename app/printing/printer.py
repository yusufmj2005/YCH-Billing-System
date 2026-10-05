"""Print a generated PDF through the Windows printing system (via Qt).

The PDF is rasterised page by page with QtPdf and painted onto a QPrinter,
so no external PDF viewer is required. When no printer is installed the PDF
is still available and the user is told where it is.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, QSize
from PySide6.QtGui import QPainter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PySide6.QtWidgets import QDialog, QMessageBox

log = logging.getLogger(__name__)

MAX_DPI = 300


def load_pdf(pdf_path: Path) -> tuple[QPdfDocument, QBuffer]:
    """Load a PDF from memory. Loading by file name keeps the file locked on
    Windows, which would block regenerating the same invoice later."""
    buf = QBuffer()
    buf.setData(QByteArray(Path(pdf_path).read_bytes()))
    buf.open(QIODevice.ReadOnly)
    doc = QPdfDocument()
    doc.load(buf)
    return doc, buf


def printers_available() -> bool:
    return bool(QPrinterInfo.availablePrinters())


def print_pdf(parent, pdf_path: Path, *, ask: bool = True, title: str = "Print") -> bool:
    pdf_path = Path(pdf_path)
    if not printers_available():
        QMessageBox.information(
            parent, "No printer found",
            "No printer is installed on this computer, so the document could not be printed.\n\n"
            f"The PDF was saved and can be opened or printed later:\n{pdf_path.name}")
        return False
    printer = QPrinter(QPrinter.HighResolution)
    printer.setDocName(pdf_path.stem)
    if ask:
        dlg = QPrintDialog(printer, parent)
        dlg.setWindowTitle(title)
        if dlg.exec() != QDialog.Accepted:
            return False
    else:
        default = QPrinterInfo.defaultPrinter()
        if default.isNull():
            return print_pdf(parent, pdf_path, ask=True, title=title)
        printer.setPrinterName(default.printerName())

    doc, _buf = load_pdf(pdf_path)
    err = doc.error()
    if err != QPdfDocument.Error.None_ or doc.pageCount() == 0:
        log.error("Could not load PDF for printing: %s (%s)", pdf_path, err)
        QMessageBox.warning(parent, "Print failed", "The document could not be prepared for "
                                                   "printing. The PDF file is still available.")
        return False
    painter = QPainter()
    try:
        if not painter.begin(printer):
            raise RuntimeError("printer.begin failed")
        dpi = min(printer.resolution(), MAX_DPI)
        target = printer.pageRect(QPrinter.DevicePixel)
        for i in range(doc.pageCount()):
            if i:
                printer.newPage()
            pts = doc.pagePointSize(i)
            img = doc.render(i, QSize(int(pts.width() / 72 * dpi), int(pts.height() / 72 * dpi)))
            narrow = pts.width() < 300  # receipt rolls: fit to width
            sx = target.width() / img.width()
            sy = target.height() / img.height()
            scale = sx if narrow else min(sx, sy)
            dest = QRectF(QPointF(0, 0), QSize(int(img.width() * scale),
                                               int(img.height() * scale)).toSizeF())
            painter.drawImage(dest, img)
        return True
    except Exception:
        log.exception("Printing failed")
        QMessageBox.warning(parent, "Print failed",
                            "The printer reported an error. The PDF file is still available "
                            "and can be printed later.")
        return False
    finally:
        if painter.isActive():
            painter.end()
        doc.close()
