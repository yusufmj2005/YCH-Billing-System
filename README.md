# BusinessPOS

A Windows desktop point-of-sale and business management application for a retail
shop selling yarn, crochet hooks, knitting needles, accessories, project kits and
handmade products.

End-user experience:

```
BusinessPOS-Setup.exe → Install → Launch → First-time setup → Use
```

End users do **not** need Python, pip, a terminal or any developer tools. The
database is created automatically on first launch.

**Setting up a shop?** Start with [docs/GO-LIVE-CHECKLIST.md](docs/GO-LIVE-CHECKLIST.md),
then run [docs/ACCEPTANCE-TEST.md](docs/ACCEPTANCE-TEST.md) on the shop PC.
Download the installer from the latest green **Test & build installer** run (or a
Release). See [CHANGELOG.md](CHANGELOG.md) for what changed.

---

## 1. Features

| Area | What is implemented |
|---|---|
| Login & security | Username/password sign-in, bcrypt password hashing, account lockout after 5 failed attempts, forced password change for admin-set passwords, optional auto sign-out after inactivity |
| First-time setup | Wizard for business details and logo, administrator account, invoice numbering, tax rates and payment methods. Nothing is pre-filled with business data |
| Dashboard | Sales, transactions, expenses, refunds, inventory value, active and low-stock products, recorded payments by method, 14-day sales chart, recent sales and purchases. Date filter. All figures come from the database and show zero when there is no data |
| POS / Billing | Search or scan (USB keyboard-wedge scanners), quantity edits, item and bill discounts (amount or %), CGST/SGST or IGST, optional round-off, walk-in or named customer, keyboard shortcuts |
| Payments | Cash, UPI, Debit Card, Credit Card, Bank Transfer, Other and custom methods. Optional transaction/reference ID. Split payments. Totals must equal the invoice total. Card-number-like references are rejected |
| Invoices | Unique, gap-free numbering with a configurable prefix and start number. A4 PDF and 80 mm receipt PDF. Printing through Windows printers. Reprint, save as PDF |
| Sales | Filters by date, customer, payment method and status. Details view. Controlled voiding (permission + reason; stock restored; payments marked void; number never reused) |
| Returns | Against the original invoice only. Quantity can't exceed what is still returnable. Pro-rata refund incl. tax, split refunds, optional "not restocked" for damaged items. Return note PDF |
| Products & categories | Bulk import from CSV/Excel (validated, all-or-nothing). Create, edit, search, filter, deactivate. SKU (unique, configurable), barcode (always unique), HSN/SAC, cost/selling price, tax rate, inclusive/exclusive pricing, unit, fractional quantities, minimum stock, optional product image |
| Barcodes | Manual entry, or generated on request (Code 128 or EAN-13 with in-store prefix 20–29). Label PDF sheets (A4 3×8, A4 4×10, single-label printers) |
| Inventory | Stock ledger for every change (PURCHASE, SALE, RETURN, ADJUSTMENT_IN/OUT, SALE_VOID, PURCHASE_CANCEL). Adjustments (add, remove, set to counted quantity) with a required reason. Low-stock alerts, valuation. Negative stock is blocked by default (configurable) |
| Purchases & suppliers | Draft, complete (adds stock) and cancel (reverses stock). Discounts, tax, optional cost-price update, supplier payments with paid/partial/unpaid status. Supplier purchase history and products purchased |
| Customers | Customer records and purchase history (net of refunds) |
| Expenses | Configurable categories, payment method, reference, voiding with reason |
| Reports | Daily, weekly and monthly sales; sales register; product, category and payment-method sales; tax summary; current stock; low stock; stock movement; valuation; purchase register; supplier-wise and product-wise purchases; expense register and by category; profit & loss; revenue/purchases/expenses by month; payment-method summary. CSV and PDF export |
| Staff | Employees, daily attendance, leave (configurable types, approve/reject), **Internal Payroll Management** (no statutory calculations) with optional posting to expenses |
| Users & permissions | Users; roles (Administrator, Manager, Cashier and Inventory Staff, editable); 37 granular permissions enforced in the service layer |
| Audit log | Login, logout, sales, voids, returns, purchases, stock adjustments, product/price changes, settings, users, permissions, backup and restore. Read-only (database triggers block edits and deletes) |
| Backup & restore | Manual backup (default or chosen folder), daily automatic backup, integrity validation, typed confirmation, automatic safety backup before every restore |

## 2. Architecture

```
BusinessPOS/
├── app/
│   ├── main.py               entry point (single instance, logging, startup flow)
│   ├── bootstrap.py          builds Database + all services (no Qt)
│   ├── selftest.py           packaged-build self test (--self-test)
│   ├── config/               constants (permissions, roles, enums), runtime paths
│   ├── database/             engine/session, scaled-decimal types, migrations, system seed
│   ├── models/               SQLAlchemy ORM models (one file per domain)
│   ├── security/             bcrypt hashing, CurrentUser + permission checks
│   ├── validators/           input normalisation/validation
│   ├── services/             business logic (all permission checks happen here)
│   ├── reports/              report container + CSV/PDF exporters
│   ├── printing/             invoice/return/label PDFs, Windows printing via QtPdf
│   ├── barcode/              barcode value generation (EAN-13 check digit, Code 128)
│   ├── backup/               backup / validate / restore
│   ├── ui/                   PySide6 UI: windows, pages, dialogs, widgets, theme
│   └── utils/                money/date helpers, logging, single-instance mutex
├── assets/icons/             app.ico (generated by tools/make_icon.py), UI assets
├── tests/                    pytest suite (services, PDFs, backup, migrations, UI smoke)
├── tools/                    icon generator, version info, demo seed + screenshots (dev only)
├── installer/installer.iss   Inno Setup script
├── build/                    build_app.bat, build_installer.bat, clean_build.bat
├── BusinessPOS.spec          PyInstaller definition
└── requirements.txt
```

**Layers.** The UI calls services. Each service runs its work in one database
transaction (`Database.session()`), checks permissions with `require(actor, Perm.X)`
and writes audit rows in the same transaction. Hiding a button is never the only
protection.

**Money.** All amounts are `Decimal`. SQLite has no fixed-point type, so money is
stored as integer paise and quantities as integer thousandths (`ScaledDecimal`).
There is no floating-point rounding.

**Transactions.** Each transaction starts with `BEGIN IMMEDIATE`. A sale validates
the cart and stock, computes totals with the same pricing engine the POS screen
uses, validates payments, takes the next invoice number, then inserts the sale,
its items, payments, stock reductions, ledger rows and audit entry, and commits.
Any error rolls everything back, including the invoice-number increment. A test
proves this. Purchases, returns, adjustments, voids and cancellations work the
same way.

**Integrity guards in the database.** These are SQLite triggers, and they also
stop direct SQL changes:
- Rows in sales, sale items, payments, returns, return items, inventory movements, expenses and the audit log can never be deleted.
- Sale items, return items, inventory movements, returns and audit log rows are read-only.
- Sale totals, invoice numbers, payment amounts and payment methods are immutable.
- Only draft purchases can be deleted or edited.
- Unique constraints cover barcodes, invoice numbers, return numbers, purchase numbers, usernames and similar keys.
- Check constraints reject non-positive quantities and payment amounts.

## 3. Development setup

Requirements on the **build/development** machine: Windows 10/11 x64, Python 3.12
(3.11+ works) and, for the installer, Inno Setup 6.

```bat
cd BusinessPOS
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

### Running locally

Use a separate data folder during development so a production database is never
touched:

```bat
set BUSINESSPOS_DATA_DIR=%CD%\.devdata
.venv\Scripts\python -m app.main
```

Optional demo data, for development only. Every record is labelled "DEMO", and the
script refuses to run against the production folder:

```bat
set BUSINESSPOS_DATA_DIR=%CD%\.devdata
.venv\Scripts\python tools\demo_seed.py
```

## 4. Database

- SQLite file `businesspos.db`, created automatically on first launch.
- Schema version is stored in `app_meta.schema_version`
  (`app/database/migrations/__init__.py`).
  - **New database:** the current schema is created, triggers are installed and the version is stamped.
  - **Older database (after an update):** an automatic `pre-upgrade` backup is made first, then each numbered migration runs in its own transaction.
  - **Newer database:** the app refuses to open it, so an old version can't damage newer data.
- To change the schema later: edit the models, add a migration function, register it in `MIGRATIONS` and bump `SCHEMA_VERSION`.

## 5. Testing

```bat
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check .
```

`pytest.ini` turns leaked database handles into test failures. Every push is tested
automatically (see section 7).

The suite covers:
- products (create, edit, search, duplicate SKU and barcode)
- pricing (tax inclusive/exclusive, IGST, discounts, allocation, round-off)
- inventory (purchase, sale, return, adjustment, insufficient stock, negative-stock setting, fractional quantities, low stock)
- every payment method with reference IDs, split payments and invalid totals
- invoice numbering (unique, sequential, never reused after a failed sale, can't go backwards)
- PDF invoices (A4 and receipt), return notes and labels
- returns (valid, excess blocked, partial returns add up exactly, damaged items)
- permissions (cashier restrictions, discount limit, last-admin protection)
- transaction rollback and the delete/update triggers
- backup, restore and safety backup; reopening an existing database; the migration runner; refusing a newer database
- reports and profit & loss figures, staff and expenses
- offscreen UI smoke tests (every page loads, POS cart and scanner flow, cashier navigation)
- a full business day reconciled across every report, the dashboard and the stock ledger (`tests/test_reconciliation.py`)
- the setup wizard and sign-in screens: validation, lockout, forced password change
- refunds on rounded invoices, upgrade of a real v1 database, backups to paths with special characters, second backup copy
- CSV product import (Excel encodings, every error reported, all-or-nothing)
- business rules for payment methods, customers/suppliers, expenses, payroll, attendance, leave, roles and purchases

## 6. Building the executable

```bat
build\build_app.bat
```

The script runs these steps in order:
1. Clean the previous build.
2. Create or check `.venv` and install the exact pinned versions from `requirements-lock.txt`.
3. Run the tests.
4. Write the Windows version info.
5. Run PyInstaller.
6. Validate the output and run `BusinessPOS.exe --self-test`.

The self-test uses a temporary folder. It checks the database, sign-in, a sale, the
PDF and barcode generation, a backup and QtPdf rendering. Its result is written to
`%TEMP%\BusinessPOS-selftest.log`.

Output: `dist\BusinessPOS\BusinessPOS.exe` plus its `_internal` folder. This is a
one-folder build, chosen for fast start-up and fewer antivirus false positives.
The installer packages the whole folder.

## 7. Building the installer

**Recommended: the automated build.** Every push runs
`.github/workflows/build.yml`:
1. Lint and the full test suite on Linux.
2. On Windows: `build_installer.bat`, which runs the tests, PyInstaller, the
   packaged self-test and Inno Setup.
3. A silent **install** of the produced installer on a clean Windows machine, a
   self-test of the installed program, and a silent **uninstall**.
4. The installer and its SHA-256 checksum are uploaded as the
   **BusinessPOS-Setup** artifact.

Pushing a tag such as `v1.0.1` also publishes a GitHub Release with the
installer attached. Installers are never committed to the repository.

To build locally instead:

```bat
build\build_installer.bat
```

This runs `build_app.bat`, then compiles `installer\installer.iss` with Inno Setup 6
(ISCC is found automatically).

**Installer output:** `installer_output\BusinessPOS-Setup.exe`, the only file to
give to users.

The installer:
- Shows the name, version and publisher. Override the publisher with `ISCC /DMyAppPublisher="…"`; the default is "BusinessPOS".
- Uses the application icon and lets the user choose the install folder.
- Installs for all users (admin) or only the current user.
- Creates a Start Menu shortcut and offers a desktop shortcut.
- Registers an uninstaller and offers to launch the app at the end.
- Detects a running BusinessPOS (shared mutex) and asks for it to be closed.

## 8. Where data is stored

```
%LOCALAPPDATA%\BusinessPOS\
    database\businesspos.db
    backups\        automatic, manual, pre-restore and pre-upgrade backups
    logs\           businesspos.log (rotating; no passwords or payment credentials)
    attachments\    logo, product images
    exports\        generated invoices, return notes, labels, reports
```

Program files go to `Program Files\BusinessPOS`. Nothing mutable is stored there.
Data is per Windows user account.

## 9. Backup and restore

- **Backup** (Backup & Restore page): uses SQLite's online backup API, so it's safe while the app is running. Each backup is verified with an integrity check before it is kept. You can save it to the default folder or to any folder (USB drive, network share). Automatic backups run once a day at start-up and every time the app is closed (both on by default). The last 30 are kept; the number is configurable. Set a **second copy folder** (USB drive or OneDrive/Google Drive folder) in Settings › Security & backup so that every automatic backup is also copied off this disk. You are warned if that folder is unavailable.
- **Restore:** the file is validated (integrity, BusinessPOS identity, schema version) and a summary of its contents is shown. You must type `RESTORE` to confirm. A safety backup of the current data is created first. If the restore fails, the previous data is put back automatically. Afterwards everyone is signed out.

## 10. Updating

1. Build a new installer with a higher `APP_VERSION` (`app/config/constants.py`). Keep the `AppId` in `installer.iss` unchanged.
2. The user runs the new `BusinessPOS-Setup.exe`. It replaces the program files only; the installer shows a reminder that data is kept.
3. On first start the app detects an older schema, makes a `pre-upgrade` backup and migrates in place.
4. Sales, purchases, inventory, customers, suppliers, employees, settings and audit logs are preserved. An update never ships a database.

## 11. Uninstalling

"Apps & features → BusinessPOS → Uninstall" removes program files, shortcuts and the
uninstall registration. Business data is **kept** unless the user answers Yes to
two separate confirmation prompts, both of which default to No. When uninstalling as
an administrator, the data folder offered for deletion is the one belonging to the
account running the uninstaller.

## 12. Accounting methodology (profit & loss)

- **Net sales** = taxable value of completed sales (excluding tax) − taxable value of returns + invoice round-off.
- **COGS** = cost price snapshotted on each sale line − cost of returned items that went back into stock.
- **Gross profit** = Net sales − COGS.
- **Operating expenses** = non-void expenses dated in the period, including salary expenses posted from payroll.
- **Net profit** = Gross profit − Operating expenses.
- **Purchases** are shown for information. They become cost through COGS when the goods are sold, so they are not subtracted twice.
- **Tax collected** is a liability, not revenue.
- **Inventory valuation** = current stock × current cost price (the last purchase cost when purchases update cost prices).
- **Payment summaries** are *recorded* amounts, not bank or cash-drawer balances.

BusinessPOS supports business accounting. It is not a statutory accounting
package and does not make tax-compliance claims.

## 13. Known limitations

- **Not implemented yet:**
  - credit or partial-payment sales (every sale must be fully paid when completed)
  - customer store credit
  - returns to suppliers (a completed purchase can only be cancelled as a whole)
  - returns without the original invoice
- **No payment processing:** UPI, card and bank methods only record how the customer paid. BusinessPOS doesn't talk to payment gateways or terminals.
- **Tax compliance:** no GST e-invoicing (IRN/QR), e-way bills or return-filing exports. Rates are whatever the business configures.
- **Payroll** is internal record-keeping only. There are no PF, ESI, professional tax or TDS calculations.
- **Valuation:** inventory uses the current cost price, not FIFO or weighted average.
- **Single computer:** SQLite on one PC, one user session at a time. There is no multi-terminal network mode or cloud sync. Data is per Windows user account.
- **Backups are not encrypted.** Store copies securely.
- **No password recovery** if every administrator forgets their password. Keep a second administrator account or a recent backup with a known password.
- **Unsigned installer:** the installer and exe are not code-signed, so Windows SmartScreen may warn on first run. Sign them with a code-signing certificate before wide distribution.
- **Hardware:** barcode scanners must work in keyboard (HID) mode. Printing goes through standard Windows printer drivers. Specific thermal printer or scanner models have not been tested.
- **Clean-machine testing:** see the final build notes. The packaged self-test proves the exe runs without the developer's Python environment, but a fresh Windows VM test should still be done before release.
