"""Register a Unicode TrueType font (for the rupee sign) from Windows.

Falls back to Helvetica (and the text "Rs.") when no suitable font exists.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

log = logging.getLogger(__name__)

_CANDIDATES = [("segoeui.ttf", "segoeuib.ttf"), ("arial.ttf", "arialbd.ttf"),
               ("calibri.ttf", "calibrib.ttf")]
_state: dict = {}


def fonts() -> tuple[str, str, bool]:
    """Return (regular, bold, unicode_ok)."""
    if _state:
        return _state["regular"], _state["bold"], _state["unicode"]
    font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for reg, bold in _CANDIDATES:
        r, b = font_dir / reg, font_dir / bold
        if r.is_file() and b.is_file():
            try:
                pdfmetrics.registerFont(TTFont("BPOS-Regular", str(r)))
                pdfmetrics.registerFont(TTFont("BPOS-Bold", str(b)))
                # lets <b> inside Paragraphs switch to the bold face
                for fam in ("BPOS-Regular", "BPOS-Bold"):
                    pdfmetrics.registerFontFamily(fam, normal="BPOS-Regular", bold="BPOS-Bold",
                                                  italic="BPOS-Regular", boldItalic="BPOS-Bold")
                _state.update(regular="BPOS-Regular", bold="BPOS-Bold", unicode=True)
                return "BPOS-Regular", "BPOS-Bold", True
            except Exception:  # pragma: no cover - corrupt font file
                log.warning("Could not register font %s", r, exc_info=True)
    _state.update(regular="Helvetica", bold="Helvetica-Bold", unicode=False)
    return "Helvetica", "Helvetica-Bold", False


def currency(symbol: str) -> str:
    _, _, uni = fonts()
    if not uni and symbol == "\u20b9":
        return "Rs. "
    return symbol
