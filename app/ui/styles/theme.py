"""Visual theme: one restrained palette, Segoe UI, consistent spacing."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

C = {
    "bg": "#F5F6F8",
    "surface": "#FFFFFF",
    "surface_alt": "#F9FAFB",
    "border": "#E2E5EA",
    "border_strong": "#CDD2DA",
    "text": "#1C2230",
    "muted": "#667085",
    "faint": "#98A2B3",
    "primary": "#2F6FEB",
    "primary_hover": "#255FD0",
    "primary_soft": "#EAF1FE",
    "success": "#1E8E5A",
    "success_soft": "#E7F6EE",
    "warning": "#B25E09",
    "warning_soft": "#FEF4E6",
    "danger": "#C8372D",
    "danger_soft": "#FDECEA",
    "sidebar": "#161B26",
    "sidebar_hover": "#222938",
    "sidebar_active": "#2A3245",
    "sidebar_text": "#AEB6C6",
    "sidebar_heading": "#6B7487",
}

QSS = f"""
* {{ font-family: "Segoe UI"; font-size: 10pt; color: {C['text']}; }}
QMainWindow, QDialog, QWizard {{ background: {C['bg']}; }}
QWidget#Page {{ background: {C['bg']}; }}
QToolTip {{ background: {C['text']}; color: white; border: none; padding: 4px 6px; }}

/* ---- sidebar ---- */
QFrame#Sidebar {{ background: {C['sidebar']}; }}
QFrame#Sidebar QLabel#Brand {{ color: white; font-size: 13pt; font-weight: 600; }}
QFrame#Sidebar QLabel#BrandSub {{ color: {C['sidebar_heading']}; font-size: 8.5pt; }}
QFrame#Sidebar QLabel#NavHeading {{ color: {C['sidebar_heading']}; font-size: 8pt;
    font-weight: 600; letter-spacing: 1px; padding: 10px 18px 4px 18px; }}
QPushButton#NavButton {{ color: {C['sidebar_text']}; background: transparent; border: none;
    text-align: left; padding: 7px 18px; border-radius: 0; font-size: 10pt;
    border-left: 3px solid transparent; }}
QPushButton#NavButton:hover {{ background: {C['sidebar_hover']}; color: white; }}
QPushButton#NavButton:checked {{ background: {C['sidebar_active']}; color: white;
    border-left: 3px solid {C['primary']}; font-weight: 600; }}
QScrollArea#SidebarScroll {{ background: {C['sidebar']}; border: none; }}
QScrollArea#SidebarScroll > QWidget > QWidget {{ background: {C['sidebar']}; }}

/* ---- top bar ---- */
QFrame#TopBar {{ background: {C['surface']}; border-bottom: 1px solid {C['border']}; }}
QLabel#PageTitle {{ font-size: 15pt; font-weight: 600; }}
QLabel#Muted, QLabel[muted="true"] {{ color: {C['muted']}; }}
QLabel#Faint {{ color: {C['faint']}; font-size: 9pt; }}
QLabel#SectionTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#Notice {{ background: {C['primary_soft']}; color: #1D4FAF; border-radius: 6px;
    padding: 8px 10px; }}
QLabel#Warning {{ background: {C['warning_soft']}; color: {C['warning']}; border-radius: 6px;
    padding: 8px 10px; }}
QLabel#ErrorText {{ color: {C['danger']}; }}

/* ---- cards ---- */
QFrame#Card {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 10px; }}
QLabel#StatValue {{ font-size: 18pt; font-weight: 600; }}
QLabel#StatLabel {{ color: {C['muted']}; font-size: 9pt; }}
QLabel#BigTotal {{ font-size: 22pt; font-weight: 700; color: {C['text']}; }}

/* ---- buttons ---- */
QPushButton {{ background: {C['surface']}; border: 1px solid {C['border_strong']};
    border-radius: 6px; padding: 6px 14px; min-height: 20px; }}
QPushButton:hover {{ background: {C['surface_alt']}; border-color: {C['faint']}; }}
QPushButton:pressed {{ background: {C['border']}; }}
QPushButton:disabled {{ color: {C['faint']}; background: {C['surface_alt']};
    border-color: {C['border']}; }}
QPushButton[variant="primary"] {{ background: {C['primary']}; color: white;
    border: 1px solid {C['primary']}; font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {C['primary_hover']}; }}
QPushButton[variant="primary"]:disabled {{ background: #9DBBF5; border-color: #9DBBF5;
    color: white; }}
QPushButton[variant="danger"] {{ color: {C['danger']}; border-color: #F1B8B2; }}
QPushButton[variant="danger"]:hover {{ background: {C['danger_soft']}; }}
QPushButton[variant="success"] {{ background: {C['success']}; color: white;
    border: 1px solid {C['success']}; font-weight: 600; }}
QPushButton[variant="success"]:disabled {{ background: #9FD3B8; border-color: #9FD3B8; }}
QPushButton[variant="ghost"] {{ border: none; background: transparent; color: {C['primary']}; }}
QPushButton[variant="ghost"]:hover {{ background: {C['primary_soft']}; }}
QPushButton[variant="pay"] {{ padding: 10px 8px; font-weight: 600; }}
QPushButton[variant="pay"]:checked {{ background: {C['primary_soft']};
    border: 2px solid {C['primary']}; color: #1D4FAF; }}
QPushButton#Checkout {{ font-size: 13pt; padding: 12px; }}
QToolButton {{ border: 1px solid {C['border_strong']}; border-radius: 6px; padding: 5px 10px;
    background: {C['surface']}; }}
QToolButton:hover {{ background: {C['surface_alt']}; }}
QToolButton::menu-indicator {{ image: none; }}

/* ---- inputs ---- */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit,
QTimeEdit {{ background: {C['surface']}; border: 1px solid {C['border_strong']};
    border-radius: 6px; padding: 5px 8px; selection-background-color: {C['primary']};
    selection-color: white; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QDateEdit:focus, QTimeEdit:focus {{ border: 1px solid {C['primary']}; }}
QLineEdit:disabled, QComboBox:disabled {{ background: {C['surface_alt']}; color: {C['muted']}; }}
QLineEdit[invalid="true"] {{ border: 1px solid {C['danger']}; }}
QLineEdit#SearchBig {{ font-size: 13pt; padding: 9px 12px; border-radius: 8px; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 24px;
    subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url("{{CHEVRON}}"); width: 12px;
    height: 12px; }}
QComboBox {{ padding-right: 24px; min-width: 120px; }}
QTreeWidget::item {{ padding: 5px 2px; }}
QPushButton[variant="icon"] {{ border: none; background: transparent; color: {C['muted']};
    padding: 0; min-height: 0; font-size: 11pt; }}
QPushButton[variant="icon"]:hover {{ color: {C['danger']}; background: {C['danger_soft']};
    border-radius: 4px; }}
QComboBox QAbstractItemView {{ background: {C['surface']}; border: 1px solid {C['border']};
    selection-background-color: {C['primary_soft']}; selection-color: {C['text']}; }}
QCheckBox {{ spacing: 8px; }}

/* ---- tables ---- */
QTableView, QTreeWidget, QListWidget {{ background: {C['surface']}; border: 1px solid {C['border']};
    border-radius: 8px; gridline-color: {C['border']};
    alternate-background-color: {C['surface_alt']};
    selection-background-color: {C['primary_soft']}; selection-color: {C['text']}; }}
QTableView::item {{ padding: 4px 6px; border: none; }}
QHeaderView::section {{ background: {C['surface_alt']}; color: {C['muted']}; font-weight: 600;
    font-size: 9pt; border: none; border-bottom: 1px solid {C['border']}; padding: 7px 6px; }}
QTableCornerButton::section {{ background: {C['surface_alt']}; border: none; }}

/* ---- tabs / groups ---- */
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; color: {C['muted']};
    border-bottom: 2px solid transparent; margin-right: 4px; }}
QTabBar::tab:selected {{ color: {C['text']}; border-bottom: 2px solid {C['primary']};
    font-weight: 600; }}
QTabBar::tab:hover {{ color: {C['text']}; }}
QGroupBox {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 10px;
    margin-top: 14px; padding: 14px 12px 12px 12px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px;
    color: {C['text']}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {C['border_strong']}; border-radius: 4px;
    min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {C['border_strong']}; border-radius: 4px;
    min-width: 30px; }}
QStatusBar {{ background: {C['surface']}; border-top: 1px solid {C['border']};
    color: {C['muted']}; }}

QFrame#Toast {{ background: {C['text']}; border-radius: 8px; }}
QFrame#Toast QLabel {{ color: white; }}
QFrame#LoginCard {{ background: {C['surface']}; border: 1px solid {C['border']};
    border-radius: 14px; }}
QFrame#TotalsPanel {{ background: {C['surface']}; border: 1px solid {C['border']};
    border-radius: 10px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(C["bg"]))
    pal.setColor(QPalette.Base, QColor(C["surface"]))
    pal.setColor(QPalette.AlternateBase, QColor(C["surface_alt"]))
    pal.setColor(QPalette.Text, QColor(C["text"]))
    pal.setColor(QPalette.WindowText, QColor(C["text"]))
    pal.setColor(QPalette.ButtonText, QColor(C["text"]))
    pal.setColor(QPalette.Button, QColor(C["surface"]))
    pal.setColor(QPalette.Highlight, QColor(C["primary"]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.PlaceholderText, QColor(C["faint"]))
    app.setPalette(pal)
    from app.config.settings import asset_path
    chevron = asset_path("icons", "chevron-down.svg").as_posix()
    app.setStyleSheet(QSS.replace("{CHEVRON}", chevron))
