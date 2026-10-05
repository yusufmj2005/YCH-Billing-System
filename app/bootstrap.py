"""Application wiring: open/upgrade the database and build all services.

Kept free of Qt so tests and tools can use it directly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.backup.backup_service import BackupService
from app.config.settings import AppPaths
from app.database.database import Database
from app.database.migrations import initialize_schema
from app.database.seed import ensure_default_settings, seed_initial_data, sync_permissions
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.catalog_service import CatalogService
from app.services.dashboard_service import DashboardService
from app.services.expense_service import ExpenseService
from app.services.inventory_service import InventoryService
from app.services.partner_service import PartnerService
from app.services.payment_method_service import PaymentMethodService
from app.services.purchase_service import PurchaseService
from app.services.report_service import ReportService
from app.services.return_service import ReturnService
from app.services.sales_service import SalesService
from app.services.settings_service import SettingsService
from app.services.staff_service import StaffService
from app.services.user_service import UserService

log = logging.getLogger(__name__)


def prepare_database(db: Database, paths: AppPaths | None = None) -> bool:
    """Create or upgrade the schema and make sure system data exists.
    Returns True when a brand-new database was created."""

    def _backup_before_upgrade(old_version: int) -> None:
        if paths is None:
            return
        BackupService(db, paths).create_backup(None, kind=f"pre-upgrade-v{old_version}")

    created = initialize_schema(db, before_upgrade=_backup_before_upgrade)
    with db.session() as s:
        if created:
            seed_initial_data(s)
        else:
            sync_permissions(s)
            ensure_default_settings(s)
    return created


@dataclass
class Services:
    db: Database
    paths: AppPaths
    settings: SettingsService
    auth: AuthService
    users: UserService
    audit: AuditService
    catalog: CatalogService
    partners: PartnerService
    payment_methods: PaymentMethodService
    inventory: InventoryService
    sales: SalesService
    returns: ReturnService
    purchases: PurchaseService
    expenses: ExpenseService
    staff: StaffService
    reports: ReportService
    dashboard: DashboardService
    backup: BackupService


def build_services(paths: AppPaths, db: Database | None = None) -> Services:
    db = db or Database(paths.database_file)
    prepare_database(db, paths)
    settings = SettingsService(db, paths.attachments_dir)
    return Services(
        db=db, paths=paths, settings=settings, auth=AuthService(db, settings),
        users=UserService(db), audit=AuditService(db),
        catalog=CatalogService(db, paths.attachments_dir),
        partners=PartnerService(db), payment_methods=PaymentMethodService(db),
        inventory=InventoryService(db), sales=SalesService(db), returns=ReturnService(db),
        purchases=PurchaseService(db), expenses=ExpenseService(db), staff=StaffService(db),
        reports=ReportService(db), dashboard=DashboardService(db),
        backup=BackupService(db, paths, reinitialize=lambda d: prepare_database(d, paths)),
    )
