# BusinessPOS – Acceptance test (run on the shop PC)

The automated tests run on every build. They check calculations, stock, reports,
permissions, backups and the installer on a clean Windows machine. What they
**cannot** check is your real hardware and your real way of working. This script
covers that.

**How to run it**

- Do it on the shop PC, with the real printer and scanner, **before** importing
  your real products.
- Use a throw-away install: when you're done, uninstall and answer **Yes** to
  deleting the data.
- Tick each step only if the result is exactly as written. If any step fails, stop
  and report it with a screenshot and the log file
  (`%LOCALAPPDATA%\BusinessPOS\logs\businesspos.log`).

| | |
|---|---|
| Tester | |
| Date | |
| BusinessPOS version (shown on the sign-in screen) | 1.0.2 |
| PC / printer / scanner | |

---

## A. Install and setup

| # | Do this | Expected result | ✔ |
|---|---|---|---|
| A1 | Run `BusinessPOS-Setup.exe` | Installs without errors. A Start-menu shortcut appears. BusinessPOS opens. | |
| A2 | Setup wizard: business name "UAT Shop"; admin `owner` / `Owner-Pass-123`; prefix `UAT-`; on the Tax page type **GST 5%** / `5` and click **Add**, then type **GST 12%** / `12` and click **Next** *without* clicking Add | Both rates are kept. The wizard does not drop the second one. | |
| A3 | Finish setup | The main window opens, signed in as owner. The dashboard shows all zeros. | |
| A4 | Settings → Billing: tick **Round off** and save | "Settings saved" | |

## B. Products, scanner and labels

| # | Do this | Expected result | ✔ |
|---|---|---|---|
| B1 | Products → Import from CSV… → Save template. In Excel add two rows: **UAT Yarn**, sku `UAT-Y`, barcode `UATYARN1`, unit `ball`, purchase 150, selling **249.50**, tax_rate `GST 12%`, price_includes_tax `yes`, opening_stock 10; and **UAT Hook**, sku `UAT-H`, barcode `UATHOOK1`, unit `pcs`, purchase 40, selling **85.25**, tax_rate `GST 5%`, price_includes_tax `no`, opening_stock 5. Save as CSV UTF-8 and choose the file | "Ready to import 2 product(s)" | |
| B2 | Change one selling price in the file to `abc` and choose it again | The row number and the problem are listed. Import stays disabled. | |
| B3 | Fix the file and import | 2 products listed. Stock: 10 and 5. | |
| B4 | Select UAT Yarn → Print labels → print one sheet | The labels print aligned with the label paper. | |
| B5 | POS: scan the printed label with the scanner | UAT Yarn is added to the cart. | |

## C. Sales, payments and invoices

| # | Do this | Expected result | ✔ |
|---|---|---|---|
| C1 | POS: add UAT Yarn ×2 and UAT Hook ×1 | Total **₹589.00** (round-off +0.49). | |
| C2 | Checkout: Cash 300 + UPI 289 with reference `UPI-REF-1` | The sale completes. Invoice **UAT-000001**. | |
| C3 | Print the invoice (A4 and/or receipt) | Business details are shown; CGST 28.86 + SGST 28.86; total 589.00; both payments listed. The layout fits the paper. | |
| C4 | New sale: UAT Yarn ×1. In checkout choose Debit Card and type the reference `4111 1111 1111 1111` | Rejected: "This looks like a card number…" | |
| C5 | Same sale: apply a 10 % bill discount, then pay Cash | Total **₹225.00**. Invoice **UAT-000002**. | |
| C6 | Add UAT Hook and press + until past 5 | "Insufficient stock." is shown and the quantity stays at 5 (the stock). | |

## D. Returns and voids

| # | Do this | Expected result | ✔ |
|---|---|---|---|
| D1 | Returns: invoice UAT-000001, return 1 × UAT Yarn | Refund **₹249.50**. A return note prints. | |
| D2 | Return the rest of UAT-000001 (1 Yarn + 1 Hook) | Refund **₹339.50**, including the invoice round-off 0.49. **Total refunded = 589.00 = amount paid.** | |
| D3 | Try another return on UAT-000001 | Blocked: the quantity exceeds what is available to return (0). | |
| D4 | Sales: try to void UAT-000001 | Blocked (it has returns). Voiding UAT-000002 with a reason works and its stock comes back. | |

## E. Purchases and stock

| # | Do this | Expected result | ✔ |
|---|---|---|---|
| E1 | Suppliers: add "UAT Supplier". Purchases: 20 × UAT Hook at 38.50, GST 5 %. Complete it | UAT Hook stock rises by 20. | |
| E2 | Record a payment of 100 against it | Payment status: Partial. | |
| E3 | Inventory: adjust UAT Yarn with **Set** to the counted quantity 8, reason "count" | Stock 8. A movement with the reason appears in Stock history. | |

## F. Reports (closing routine)

| # | Do this | Expected result | ✔ |
|---|---|---|---|
| F1 | Reports → Daily sales (today) | 1 invoice (UAT-000002 was voided and is excluded); sales 589.00, refunds 589.00, net 0.00. | |
| F2 | Dashboard (today) | Sales 589.00 and refunds 589.00, matching the Daily sales report. | |
| F3 | Payment-method sales | Receipts per method match what you entered. Refunds are shown separately. | |
| F4 | Export Profit & Loss to PDF and CSV | The files open in a PDF viewer and in Excel. | |

## G. Users and security

| # | Do this | Expected result | ✔ |
|---|---|---|---|
| G1 | Users: create `cashier1` with role Cashier | Created; must change password at first sign-in. | |
| G2 | Sign out → sign in as cashier1 and change the password | Only POS, Sales, Products and Customers are available. No Reports, Settings or Users. | |
| G3 | As owner set Settings → Billing → maximum discount **5**. As cashier, give a 10 % discount at checkout | Blocked: a manager must approve. | |
| G4 | Sign out → enter a wrong password 5 times for cashier1 | The account is locked for 5 minutes. | |
| G5 | Audit log (as owner) | Shows the sign-ins, sales, returns, void, purchase and adjustment with user names. | |

## H. Backup and restore

| # | Do this | Expected result | ✔ |
|---|---|---|---|
| H1 | Settings → Security & backup: set the Second copy folder to a USB drive (or OneDrive folder). Save | Saved | |
| H2 | Close BusinessPOS | A file `BusinessPOS-auto-….db` appears in the USB folder. | |
| H3 | Unplug the USB drive and start BusinessPOS; then close it | A warning about the unavailable backup folder is shown both times. The app still works and the local backup is still made. | |
| H4 | Backup & Restore → Back up to… the USB drive | A verified backup is created. | |
| H5 | Make one more sale, then Restore the H4 backup (type RESTORE) | Everyone is signed out. After signing in, that last sale is gone and everything before it is intact. | |

## I. Update and uninstall

| # | Do this | Expected result | ✔ |
|---|---|---|---|
| I1 | Run the same (or a newer) installer again | "An existing installation was found…". The data is kept. | |
| I2 | Apps & features → BusinessPOS → Uninstall; answer **No** to deleting data | Program removed. `%LOCALAPPDATA%\BusinessPOS` still exists. | |

---

**Result:** ☐ All steps passed — approved for go-live   ☐ Failed (see notes)

Signed: ______________________  Date: ____________
