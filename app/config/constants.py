"""Application-wide constants.

Nothing in this module is business data. It only defines the application's
own vocabulary: permission codes, default role templates, movement types and
the default lists the specification asks for (product categories, expense
categories, payment methods).
"""
from __future__ import annotations

APP_NAME = "BusinessPOS"
APP_VERSION = "1.0.0"
APP_ID = "BusinessPOS"  # used for data folder / mutex names
APP_MUTEX_NAME = "BusinessPOS_SingleInstance_Mutex"

# Database schema version. Increment when a migration is added.
SCHEMA_VERSION = 1
DB_FILENAME = "businesspos.db"
DB_IDENTIFIER = "BusinessPOS-database"

MIN_PASSWORD_LENGTH = 8
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 5


# --------------------------------------------------------------------------
# Permissions
# --------------------------------------------------------------------------
class Perm:
    VIEW_DASHBOARD = "VIEW_DASHBOARD"

    VIEW_PRODUCTS = "VIEW_PRODUCTS"
    EDIT_PRODUCTS = "EDIT_PRODUCTS"
    MANAGE_CATEGORIES = "MANAGE_CATEGORIES"
    MANAGE_BARCODES = "MANAGE_BARCODES"

    VIEW_INVENTORY = "VIEW_INVENTORY"
    ADJUST_INVENTORY = "ADJUST_INVENTORY"

    CREATE_SALE = "CREATE_SALE"
    VIEW_SALES = "VIEW_SALES"
    CANCEL_SALE = "CANCEL_SALE"
    PROCESS_RETURN = "PROCESS_RETURN"
    APPLY_DISCOUNT = "APPLY_DISCOUNT"
    OVERRIDE_DISCOUNT_LIMIT = "OVERRIDE_DISCOUNT_LIMIT"

    VIEW_PURCHASES = "VIEW_PURCHASES"
    CREATE_PURCHASE = "CREATE_PURCHASE"
    CANCEL_PURCHASE = "CANCEL_PURCHASE"

    VIEW_SUPPLIERS = "VIEW_SUPPLIERS"
    EDIT_SUPPLIERS = "EDIT_SUPPLIERS"

    VIEW_CUSTOMERS = "VIEW_CUSTOMERS"
    EDIT_CUSTOMERS = "EDIT_CUSTOMERS"

    VIEW_EXPENSES = "VIEW_EXPENSES"
    CREATE_EXPENSE = "CREATE_EXPENSE"
    VOID_EXPENSE = "VOID_EXPENSE"

    VIEW_REPORTS = "VIEW_REPORTS"
    VIEW_FINANCIAL_REPORTS = "VIEW_FINANCIAL_REPORTS"
    EXPORT_REPORTS = "EXPORT_REPORTS"

    MANAGE_EMPLOYEES = "MANAGE_EMPLOYEES"
    MANAGE_ATTENDANCE = "MANAGE_ATTENDANCE"
    MANAGE_LEAVE = "MANAGE_LEAVE"
    APPROVE_LEAVE = "APPROVE_LEAVE"
    MANAGE_PAYROLL = "MANAGE_PAYROLL"

    MANAGE_USERS = "MANAGE_USERS"
    MANAGE_ROLES = "MANAGE_ROLES"
    MANAGE_SETTINGS = "MANAGE_SETTINGS"

    BACKUP_DATABASE = "BACKUP_DATABASE"
    RESTORE_DATABASE = "RESTORE_DATABASE"
    VIEW_AUDIT_LOG = "VIEW_AUDIT_LOG"


# (code, human readable name, group)
PERMISSION_CATALOG: list[tuple[str, str, str]] = [
    (Perm.VIEW_DASHBOARD, "View dashboard", "General"),
    (Perm.VIEW_PRODUCTS, "View products", "Products"),
    (Perm.EDIT_PRODUCTS, "Create / edit products", "Products"),
    (Perm.MANAGE_CATEGORIES, "Manage categories", "Products"),
    (Perm.MANAGE_BARCODES, "Generate barcodes & print labels", "Products"),
    (Perm.VIEW_INVENTORY, "View inventory", "Inventory"),
    (Perm.ADJUST_INVENTORY, "Adjust stock", "Inventory"),
    (Perm.CREATE_SALE, "Use POS / create sales", "Sales"),
    (Perm.VIEW_SALES, "View sales & invoices", "Sales"),
    (Perm.CANCEL_SALE, "Void / cancel sales", "Sales"),
    (Perm.PROCESS_RETURN, "Process returns & refunds", "Sales"),
    (Perm.APPLY_DISCOUNT, "Apply discounts", "Sales"),
    (Perm.OVERRIDE_DISCOUNT_LIMIT, "Exceed maximum discount limit", "Sales"),
    (Perm.VIEW_PURCHASES, "View purchases", "Purchases"),
    (Perm.CREATE_PURCHASE, "Create / complete purchases", "Purchases"),
    (Perm.CANCEL_PURCHASE, "Cancel purchases", "Purchases"),
    (Perm.VIEW_SUPPLIERS, "View suppliers", "Purchases"),
    (Perm.EDIT_SUPPLIERS, "Create / edit suppliers", "Purchases"),
    (Perm.VIEW_CUSTOMERS, "View customers", "Customers"),
    (Perm.EDIT_CUSTOMERS, "Create / edit customers", "Customers"),
    (Perm.VIEW_EXPENSES, "View expenses", "Expenses"),
    (Perm.CREATE_EXPENSE, "Record expenses", "Expenses"),
    (Perm.VOID_EXPENSE, "Void expenses / manage categories", "Expenses"),
    (Perm.VIEW_REPORTS, "View sales / inventory / purchase reports", "Reports"),
    (Perm.VIEW_FINANCIAL_REPORTS, "View financial reports (profit/loss)", "Reports"),
    (Perm.EXPORT_REPORTS, "Export reports (PDF/CSV)", "Reports"),
    (Perm.MANAGE_EMPLOYEES, "Manage employees", "Staff"),
    (Perm.MANAGE_ATTENDANCE, "Manage attendance", "Staff"),
    (Perm.MANAGE_LEAVE, "Record leave", "Staff"),
    (Perm.APPROVE_LEAVE, "Approve / reject leave", "Staff"),
    (Perm.MANAGE_PAYROLL, "Manage payroll", "Staff"),
    (Perm.MANAGE_USERS, "Manage users", "Administration"),
    (Perm.MANAGE_ROLES, "Manage roles & permissions", "Administration"),
    (Perm.MANAGE_SETTINGS, "Manage settings", "Administration"),
    (Perm.BACKUP_DATABASE, "Back up database", "Administration"),
    (Perm.RESTORE_DATABASE, "Restore database", "Administration"),
    (Perm.VIEW_AUDIT_LOG, "View audit log", "Administration"),
]
ALL_PERMISSIONS = frozenset(code for code, _, _ in PERMISSION_CATALOG)

ADMIN_ROLE_NAME = "Administrator"

# Default role templates created on first launch. Administrators can edit
# Manager / Cashier / Inventory Staff afterwards. Administrator always has
# every permission.
DEFAULT_ROLES: dict[str, tuple[str, frozenset[str]]] = {
    ADMIN_ROLE_NAME: ("Full access", ALL_PERMISSIONS),
    "Manager": (
        "Business operations and reports",
        ALL_PERMISSIONS
        - {Perm.MANAGE_USERS, Perm.MANAGE_ROLES, Perm.MANAGE_SETTINGS, Perm.RESTORE_DATABASE},
    ),
    "Cashier": (
        "POS and sales",
        frozenset({
            Perm.CREATE_SALE, Perm.VIEW_SALES, Perm.VIEW_PRODUCTS, Perm.APPLY_DISCOUNT,
            Perm.VIEW_CUSTOMERS, Perm.EDIT_CUSTOMERS,
        }),
    ),
    "Inventory Staff": (
        "Products, inventory and purchases",
        frozenset({
            Perm.VIEW_PRODUCTS, Perm.EDIT_PRODUCTS, Perm.MANAGE_CATEGORIES, Perm.MANAGE_BARCODES,
            Perm.VIEW_INVENTORY, Perm.ADJUST_INVENTORY, Perm.VIEW_PURCHASES, Perm.CREATE_PURCHASE,
            Perm.VIEW_SUPPLIERS, Perm.EDIT_SUPPLIERS,
        }),
    ),
}

# --------------------------------------------------------------------------
# Default lists from the specification (editable by the business).
# --------------------------------------------------------------------------
DEFAULT_PRODUCT_CATEGORIES = [
    "Yarn",
    "Crochet Hooks",
    "Knitting Needles",
    "Accessories",
    "Ready-made Project Kits",
    "Custom/Own Project Kits",
    "Handmade Products",
]

DEFAULT_EXPENSE_CATEGORIES = [
    "Rent",
    "Salaries",
    "Electricity",
    "Internet",
    "Packaging",
    "Transport",
    "Marketing",
    "Other Expenses",
]

# Generic units of measure offered in the product form; editable in Settings.
DEFAULT_UNITS = ["pcs", "ball", "skein", "set", "pack", "kit", "pair", "m", "g"]


class PaymentKind:
    CASH = "CASH"
    UPI = "UPI"
    DEBIT_CARD = "DEBIT_CARD"
    CREDIT_CARD = "CREDIT_CARD"
    BANK_TRANSFER = "BANK_TRANSFER"
    OTHER = "OTHER"
    CUSTOM = "CUSTOM"


# (code, display name, allows reference id, requires description)
DEFAULT_PAYMENT_METHODS = [
    (PaymentKind.CASH, "Cash", False, False),
    (PaymentKind.UPI, "UPI", True, False),
    (PaymentKind.DEBIT_CARD, "Debit Card", True, False),
    (PaymentKind.CREDIT_CARD, "Credit Card", True, False),
    (PaymentKind.BANK_TRANSFER, "Bank Transfer", True, False),
    (PaymentKind.OTHER, "Other", True, True),
]


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------
class MovementType:
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    RETURN = "RETURN"
    ADJUSTMENT_IN = "ADJUSTMENT_IN"
    ADJUSTMENT_OUT = "ADJUSTMENT_OUT"
    # Reversals. Kept as distinct types so the stock ledger stays explicit.
    SALE_VOID = "SALE_VOID"
    PURCHASE_CANCEL = "PURCHASE_CANCEL"


MOVEMENT_TYPE_LABELS = {
    MovementType.PURCHASE: "Purchase",
    MovementType.SALE: "Sale",
    MovementType.RETURN: "Return",
    MovementType.ADJUSTMENT_IN: "Adjustment (in)",
    MovementType.ADJUSTMENT_OUT: "Adjustment (out)",
    MovementType.SALE_VOID: "Sale voided",
    MovementType.PURCHASE_CANCEL: "Purchase cancelled",
}


class SaleStatus:
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class PurchaseStatus:
    DRAFT = "DRAFT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus:
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    PAID = "PAID"


class PaymentDirection:
    IN = "IN"    # money received (sale)
    OUT = "OUT"  # money paid out (refund, supplier payment)


class TaxMode:
    INTRA = "INTRA"  # CGST + SGST
    INTER = "INTER"  # IGST


TAX_MODE_LABELS = {
    TaxMode.INTRA: "Intra-state (CGST + SGST)",
    TaxMode.INTER: "Inter-state (IGST)",
}


class LeaveStatus:
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


ATTENDANCE_STATUSES = ["Present", "Absent", "Half Day", "On Leave", "Holiday"]


class PayrollStatus:
    UNPAID = "UNPAID"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
