"""Business settings (key/value) + document sequences."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.constants import Perm, TaxMode
from app.database.database import Database
from app.database.seed import DEFAULT_SETTINGS
from app.models import Sale, Sequence, Setting
from app.security.auth import CurrentUser, require
from app.services import audit_service
from app.services.errors import ValidationError
from app.validators import common as v

_PREFIX_RE = re.compile(r"^[A-Za-z0-9/_\-]{0,12}$")


def format_doc_no(prefix: str, number: int, padding: int) -> str:
    return f"{prefix}{number:0{int(padding)}d}"


def get_settings(session: Session) -> dict:
    data = dict(DEFAULT_SETTINGS)
    for row in session.scalars(select(Setting)):
        try:
            data[row.key] = json.loads(row.value)
        except ValueError:
            data[row.key] = row.value
    return data


def next_sequence(session: Session, name: str) -> int:
    """Return the next value for ``name`` and advance it (call inside a txn)."""
    seq = session.get(Sequence, name)
    if seq is None:
        seq = Sequence(name=name, next_value=1)
        session.add(seq)
        session.flush()
    value = seq.next_value
    seq.next_value = value + 1
    session.flush()
    return value


def peek_sequence(session: Session, name: str) -> int:
    seq = session.get(Sequence, name)
    return seq.next_value if seq else 1


class SettingsService:
    def __init__(self, db: Database, attachments_dir: Path | None = None):
        self.db = db
        self.attachments_dir = attachments_dir

    # ---- reads (any logged-in user; also used before login for branding) --
    def get_all(self) -> dict:
        with self.db.session() as s:
            data = get_settings(s)
            data["next_invoice_number"] = peek_sequence(s, "invoice")
            return data

    def get(self, key: str):
        return self.get_all().get(key, DEFAULT_SETTINGS.get(key))

    def is_setup_completed(self) -> bool:
        return bool(self.get("setup_completed"))

    # ---- validation ---------------------------------------------------------
    def _clean(self, s: Session, changes: dict) -> dict:
        out: dict = {}
        for key, value in changes.items():
            if key == "next_invoice_number":
                continue
            if key not in DEFAULT_SETTINGS:
                raise ValidationError(f"Unknown setting: {key}")
            if key == "business_name":
                value = v.text(value, "Business name", required=True, max_len=150) or ""
            elif key in ("business_address", "invoice_footer"):
                value = v.text(value, "Text", max_len=1000) or ""
            elif key == "business_phone":
                value = v.phone(value) or ""
            elif key == "business_email":
                value = v.email(value) or ""
            elif key == "business_gstin":
                value = v.gstin(value) or ""
            elif key in ("business_state", "invoice_title", "currency_symbol"):
                value = v.text(value, key.replace("_", " ").title(), max_len=60) or ""
            elif key in ("invoice_prefix", "return_prefix", "purchase_prefix", "barcode_prefix"):
                value = (value or "").strip()
                if not _PREFIX_RE.match(value):
                    raise ValidationError(
                        "Prefixes may contain up to 12 letters, digits, '/', '-' or '_'.")
            elif key == "invoice_padding":
                value = int(v.decimal(value, "Invoice number digits", min_value=1, max_value=10))
            elif key == "invoice_paper":
                if value not in ("A4", "RECEIPT_80MM"):
                    raise ValidationError("Invalid invoice paper format.")
            elif key == "default_tax_mode":
                if value not in (TaxMode.INTRA, TaxMode.INTER):
                    raise ValidationError("Invalid tax mode.")
            elif key in ("auto_print_invoice", "round_off_total", "default_price_includes_tax",
                         "allow_negative_stock", "sku_unique", "auto_backup_on_start",
                         "setup_completed"):
                value = bool(value)
            elif key == "low_stock_threshold":
                value = str(v.decimal(value, "Low-stock threshold", min_value=0, places=3))
            elif key == "max_discount_percent":
                pct = v.percent(value, "Maximum discount %", required=False)
                value = "" if pct is None else str(pct)
            elif key == "idle_logout_minutes":
                value = int(v.decimal(value, "Auto logout minutes", min_value=0, max_value=480))
            elif key == "backup_keep_count":
                value = int(v.decimal(value, "Backups to keep", min_value=1, max_value=1000))
            elif key == "units":
                units = [u.strip() for u in value if str(u).strip()]
                if not units:
                    raise ValidationError("At least one unit is required.")
                if any(len(u) > 16 for u in units):
                    raise ValidationError("Units must be at most 16 characters.")
                value = list(dict.fromkeys(units))
            elif key == "barcode_symbology":
                if value not in ("CODE128", "EAN13"):
                    raise ValidationError("Invalid barcode type.")
            elif key == "logo_path":
                value = value or ""
            out[key] = value
        return out

    def _validate_invoice_numbering(self, s: Session, prefix: str, padding: int,
                                    next_no: int) -> None:
        if next_no < 1:
            raise ValidationError("Next invoice number must be at least 1.")
        candidate = format_doc_no(prefix, next_no, padding)
        if s.scalar(select(Sale.id).where(Sale.invoice_no == candidate)):
            raise ValidationError(f"Invoice number {candidate} has already been used.")
        used_higher = s.scalar(select(Sale.id).where(
            Sale.invoice_no.startswith(prefix, autoescape=True),
            Sale.invoice_number >= next_no).limit(1))
        if used_higher:
            raise ValidationError(
                "The next invoice number must be higher than every invoice already issued "
                "with this prefix.")

    def _apply(self, s: Session, actor: CurrentUser | None, changes: dict) -> list[str]:
        current = get_settings(s)
        cleaned = self._clean(s, changes)
        if "next_invoice_number" in changes or "invoice_prefix" in cleaned \
                or "invoice_padding" in cleaned:
            seq = s.get(Sequence, "invoice")
            next_no = int(changes.get("next_invoice_number", seq.next_value))
            prefix = cleaned.get("invoice_prefix", current["invoice_prefix"])
            padding = cleaned.get("invoice_padding", current["invoice_padding"])
            if (next_no != seq.next_value or prefix != current["invoice_prefix"]
                    or padding != current["invoice_padding"]):
                self._validate_invoice_numbering(s, prefix, padding, next_no)
            seq.next_value = next_no
        changed = []
        for key, value in cleaned.items():
            if current.get(key) == value:
                continue
            row = s.get(Setting, key)
            if row is None:
                s.add(Setting(key=key, value=json.dumps(value),
                              updated_by=actor.id if actor else None))
            else:
                row.value = json.dumps(value)
                row.updated_by = actor.id if actor else None
            changed.append(key)
        return changed

    def update(self, actor: CurrentUser, changes: dict) -> None:
        require(actor, Perm.MANAGE_SETTINGS)
        with self.db.session() as s:
            if "setup_completed" in changes:
                raise ValidationError("Setup state cannot be changed here.")
            before = peek_sequence(s, "invoice")
            changed = self._apply(s, actor, changes)
            if peek_sequence(s, "invoice") != before:
                changed.append("next_invoice_number")
            if changed:
                audit_service.record(s, actor, "SETTINGS_CHANGED", "settings", None,
                                     {"keys": changed})

    def store_logo(self, actor: CurrentUser | None, source: str | Path) -> str:
        """Copy a logo image into the data folder; returns stored path."""
        if actor is not None:
            require(actor, Perm.MANAGE_SETTINGS)
        src = Path(source)
        if src.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            raise ValidationError("Logo must be a PNG or JPG image.")
        if not src.is_file() or src.stat().st_size > 5_000_000:
            raise ValidationError("Logo file is missing or larger than 5 MB.")
        assert self.attachments_dir is not None
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        dest = self.attachments_dir / f"logo{src.suffix.lower()}"
        for old in self.attachments_dir.glob("logo.*"):
            old.unlink(missing_ok=True)
        shutil.copyfile(src, dest)
        return dest.name  # stored relative to the attachments folder

    def logo_file(self) -> Path | None:
        name = self.get("logo_path")
        if not name or self.attachments_dir is None:
            return None
        p = self.attachments_dir / Path(name).name
        return p if p.is_file() else None
