"""DEVELOPMENT ONLY - generate the glass-card panels shown in README.md.

GitHub READMEs cannot use custom CSS, so the panels are self-contained SVG
images (no external fonts or files). Edit the text in PANELS below and run:

    python tools/readme_cards.py

Output: docs/images/readme-about.svg, docs/images/readme-highlights.svg
"""
from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "images"

W = 1200            # SVG width (scales to the README width)
PAD = 44            # panel padding
GAP = 24            # gap between cards
COLS = 3
CARD_PAD = 26
ICON = 48
BODY_SIZE = 15
LINE_H = 23
CHARS_PER_LINE = 38  # conservative for 15px sans-serif in a 357px-wide card

FONT = "'Segoe UI', -apple-system, BlinkMacSystemFont, Inter, Roboto, Helvetica, Arial, sans-serif"

# Icon tile gradients (top-left -> bottom-right) and their glow colours.
TINTS = {
    "teal": ("#5eead4", "#0f9488"),
    "blue": ("#60a5fa", "#1d4ed8"),
    "purple": ("#c084fc", "#6d28d9"),
}

# Line icons on a 24x24 grid (Lucide-style strokes).
ICONS = {
    "bag": '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/>'
           '<path d="M16 10a4 4 0 0 1-8 0"/>',
    "receipt": '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/>'
               '<path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><path d="M12 17.5v-11"/>',
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/>'
              '<circle cx="12" cy="12" r="2"/>',
    "scan": '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
            '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/>'
            '<path d="M8 7v10"/><path d="M12 7v10"/><path d="M17 7v10"/>',
    "package": '<path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 '
               '4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/>'
               '<path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
    "sheet": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
             '<path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M8 13h2"/><path d="M14 13h2"/>'
             '<path d="M8 17h2"/><path d="M14 17h2"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5 5.5 5.5 0 0 1-5.5 '
            '5.5H11"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 '
              '1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 '
              '1z"/><path d="m9 12 2 2 4-4"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/>'
                '<path d="M3 12a9 3 0 0 0 18 0"/>',
}

PANELS = {
    "readme-about.svg": {
        "eyebrow": "OVERVIEW",
        "title": "About",
        "cards": [
            ("teal", "bag", "Built for",
             "Retail shops in India. Made for a yarn and crochet store: yarn, hooks, needles, "
             "kits and handmade goods."),
            ("blue", "receipt", "Focus",
             "Fast GST billing, accurate stock, returns that add up and reports that agree. "
             "Fully offline on one PC."),
            ("purple", "target", "Currently",
             "v1.2.0 is out: Razorpay payments confirmed automatically, UPI QR, GSTR-1 "
             "reports and encrypted backups."),
        ],
    },
    "readme-highlights.svg": {
        "eyebrow": "FEATURES",
        "title": "Highlights",
        "cards": [
            ("teal", "scan", "Fast billing",
             "Scan or search, discounts, split payments, UPI QR and Razorpay (UPI, cards) "
             "confirmed automatically."),
            ("blue", "receipt", "GST-ready invoices",
             "CGST + SGST or IGST, HSN codes, A4 and 80 mm receipts, plus GSTR-1 reports "
             "for your accountant."),
            ("purple", "package", "Accurate stock",
             "A ledger entry for every change. Negative stock blocked, low-stock alerts, "
             "valuation."),
            ("teal", "sheet", "Quick set-up",
             "Import products and opening stock from Excel. Every row is checked before "
             "anything is saved."),
            ("blue", "undo", "Correct returns",
             "Linked to the original invoice, found by product or customer if the receipt "
             "is lost."),
            ("purple", "chart", "Reports that agree",
             "Sales, tax, stock, purchases, expenses and P&L. PDF and CSV export, all "
             "cross-checked."),
            ("teal", "users", "Staff & permissions",
             "Admin, Manager, Cashier and Inventory roles with 37 permissions. Attendance "
             "and payroll."),
            ("blue", "shield", "Safe by design",
             "All-or-nothing transactions, read-only audit log, undeletable records, account "
             "lockout."),
            ("purple", "database", "Automatic backups",
             "On start-up and close, a second copy on USB or cloud, optional password "
             "encryption."),
        ],
    },
}


def wrap(text: str, width: int = CHARS_PER_LINE) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return lines


def render(spec: dict) -> str:
    cards = spec["cards"]
    rows = (len(cards) + COLS - 1) // COLS
    card_w = (W - 2 * PAD - (COLS - 1) * GAP) / COLS
    max_lines = max(len(wrap(c[3])) for c in cards)
    card_h = CARD_PAD + ICON + 22 + max_lines * LINE_H + CARD_PAD - 6
    top = 132
    h = int(top + rows * card_h + (rows - 1) * GAP + PAD)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" '
        f'viewBox="0 0 {W} {h}" role="img" aria-label="{escape(spec["title"])}">',
        f"<title>{escape(spec['title'])}</title>",
        "<defs>",
        '<radialGradient id="gTeal" cx="0.08" cy="0.95" r="0.55">'
        '<stop offset="0" stop-color="#14b8a6" stop-opacity="0.55"/>'
        '<stop offset="1" stop-color="#14b8a6" stop-opacity="0"/></radialGradient>',
        '<radialGradient id="gIndigo" cx="0.52" cy="0.0" r="0.55">'
        '<stop offset="0" stop-color="#6366f1" stop-opacity="0.75"/>'
        '<stop offset="1" stop-color="#6366f1" stop-opacity="0"/></radialGradient>',
        '<radialGradient id="gPurple" cx="0.95" cy="0.95" r="0.5">'
        '<stop offset="0" stop-color="#a855f7" stop-opacity="0.55"/>'
        '<stop offset="1" stop-color="#a855f7" stop-opacity="0"/></radialGradient>',
        '<linearGradient id="glass" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#ffffff" stop-opacity="0.13"/>'
        '<stop offset="1" stop-color="#ffffff" stop-opacity="0.05"/></linearGradient>',
        '<linearGradient id="edge" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#ffffff" stop-opacity="0.32"/>'
        '<stop offset="1" stop-color="#ffffff" stop-opacity="0.08"/></linearGradient>',
        '<linearGradient id="rule" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="#2dd4bf"/><stop offset="1" stop-color="#818cf8"/>'
        '</linearGradient>',
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="150%">'
        '<feDropShadow dx="0" dy="8" stdDeviation="10" flood-color="#000" flood-opacity="0.35"/>'
        '</filter>',
        f'<clipPath id="panel"><rect width="{W}" height="{h}" rx="26"/></clipPath>',
    ]
    for name, (c1, c2) in TINTS.items():
        out.append(f'<linearGradient id="t_{name}" x1="0" y1="0" x2="1" y2="1">'
                   f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
                   f'</linearGradient>')
        out.append(f'<filter id="glow_{name}" x="-50%" y="-50%" width="200%" height="200%">'
                   f'<feDropShadow dx="0" dy="4" stdDeviation="6" flood-color="{c2}" '
                   f'flood-opacity="0.55"/></filter>')
    out.append("</defs>")

    # panel background + soft colour glows
    out += [
        '<g clip-path="url(#panel)">',
        f'<rect width="{W}" height="{h}" fill="#0b0d1a"/>',
        f'<rect width="{W}" height="{h}" fill="url(#gIndigo)"/>',
        f'<rect width="{W}" height="{h}" fill="url(#gTeal)"/>',
        f'<rect width="{W}" height="{h}" fill="url(#gPurple)"/>',
        "</g>",
        f'<rect x="0.5" y="0.5" width="{W - 1}" height="{h - 1}" rx="26" fill="none" '
        f'stroke="#ffffff" stroke-opacity="0.08"/>',
        # heading
        f'<text x="{PAD}" y="58" font-family="{FONT}" font-size="14" font-weight="700" '
        f'letter-spacing="3" fill="#2dd4bf">{escape(spec["eyebrow"])}</text>',
        f'<text x="{PAD}" y="96" font-family="{FONT}" font-size="34" font-weight="700" '
        f'fill="#ffffff">{escape(spec["title"])}</text>',
        f'<rect x="{PAD}" y="108" width="44" height="3" rx="1.5" fill="url(#rule)"/>',
    ]

    for i, (tint, icon, title, body) in enumerate(cards):
        r, c = divmod(i, COLS)
        x = PAD + c * (card_w + GAP)
        y = top + r * (card_h + GAP)
        ix, iy = x + CARD_PAD, y + CARD_PAD
        out += [
            f'<g filter="url(#shadow)"><rect x="{x:.1f}" y="{y:.1f}" width="{card_w:.1f}" '
            f'height="{card_h}" rx="18" fill="url(#glass)"/></g>',
            f'<rect x="{x + 0.5:.1f}" y="{y + 0.5:.1f}" width="{card_w - 1:.1f}" '
            f'height="{card_h - 1}" rx="18" fill="none" stroke="url(#edge)"/>',
            # icon tile
            f'<g filter="url(#glow_{tint})"><rect x="{ix:.1f}" y="{iy}" width="{ICON}" '
            f'height="{ICON}" rx="12" fill="url(#t_{tint})"/></g>',
            f'<rect x="{ix + 1:.1f}" y="{iy + 1}" width="{ICON - 2}" height="{ICON / 2 - 1}" '
            f'rx="11" fill="#ffffff" fill-opacity="0.16"/>',
            f'<g transform="translate({ix + 12:.1f} {iy + 12}) scale(1)" fill="none" '
            f'stroke="#ffffff" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round">{ICONS[icon]}</g>',
            f'<text x="{ix + ICON + 16:.1f}" y="{iy + ICON / 2 + 7}" font-family="{FONT}" '
            f'font-size="20" font-weight="700" fill="#ffffff">{escape(title)}</text>',
        ]
        ty = iy + ICON + 34
        out.append(f'<text font-family="{FONT}" font-size="{BODY_SIZE}" fill="#cbd5e1" '
                   f'fill-opacity="0.92">')
        for n, line in enumerate(wrap(body)):
            out.append(f'<tspan x="{ix:.1f}" y="{ty + n * LINE_H}">{escape(line)}</tspan>')
        out.append("</text>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, spec in PANELS.items():
        (OUT / name).write_text(render(spec), encoding="utf-8")
        print(f"wrote {OUT / name}")


if __name__ == "__main__":
    main()
