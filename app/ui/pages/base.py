from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.ui.context import AppContext


class Page(QWidget):
    """Base for all navigation pages."""
    description = ""

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("Page")
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 18, 24, 18)
        self.root.setSpacing(12)

    def on_show(self) -> None:
        """Called every time the page becomes visible; refresh data here."""
