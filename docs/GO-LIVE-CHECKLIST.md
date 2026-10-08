# BusinessPOS – Go-live checklist

Work through this list in order before taking real sales. Tick each box. Plan for
half a day, plus the time needed to count your stock.

---

## 1. Get the correct installer

- [ ] Download **BusinessPOS-Setup.exe** from GitHub:
  - **Releases** page (for tagged versions), or
  - **Actions → "Test & build installer" → latest green run → Artifacts → BusinessPOS-Setup**.
- [ ] Check that the run is **green**. A green run means the installer passed all of these:
  - the automated tests
  - a build-and-self-test on Windows
  - an install → self-test → uninstall on a clean Windows machine
- [ ] Optional: check the file is intact. In PowerShell run
  `Get-FileHash BusinessPOS-Setup.exe` and compare it with the `.sha256` file
  that comes with it.
- [ ] Do **not** use any older `BusinessPOS-Setup.exe` (version 1.0.0). It contains
  bugs that were fixed in 1.0.1.

## 2. The shop computer

- [ ] Windows 10 or 11, 64-bit, with Windows Update done.
- [ ] Sign in to the Windows account that will run the shop. Data is stored per
  Windows user, in `%LOCALAPPDATA%\BusinessPOS`.
- [ ] Set the Windows date, time and time zone correctly. Invoices and reports use them.
- [ ] Plug in a UPS if you have one. The app writes every sale safely, but a UPS
  avoids interruptions.
- [ ] Run the installer and launch BusinessPOS. If Windows shows *"Windows protected your PC"*,
  right-click the installer → **Properties** → tick **Unblock** → **OK** and run it again
  (or click **More info → Run anyway**). See [CODE-SIGNING.md](CODE-SIGNING.md).

## 3. First-time setup wizard (decide before you start)

| Question | Advice |
|---|---|
| Business name, address, phone, GSTIN | These are printed on every invoice. Check spelling. Leave GSTIN blank if you are not registered. |
| Administrator account | Use your own name. Choose a strong password and write it somewhere safe. **It cannot be recovered** without another administrator. |
| Invoice prefix and starting number | Example: `YH-` starting at `1`. Invoice numbers can never go backwards or be reused, so choose carefully. If you are moving from another system, start after your last invoice number. |
| Tax rates | Add every GST rate you use (e.g. GST 5%, GST 12%, GST 18%). Confirm which rate applies to which product with your accountant. **Click "Add"** for each rate. |
| Default tax type | Intra-state (CGST + SGST) for normal shop sales. Inter-state (IGST) can be chosen per sale. |
| Prices include tax? | Tick if your shelf prices already include GST (usual for retail). |
| Payment methods | Untick any you don't accept. |

After setup, open **Settings** and review:

- [ ] **Billing:**
  - invoice paper (A4 or 80 mm receipt)
  - footer text (e.g. return policy)
  - **round-off** (rounds the bill to the nearest rupee)
  - maximum discount % for staff
- [ ] **Inventory:** low-stock threshold and units. Keep "allow negative stock" **off**.
- [ ] **Payments:** enter your shop's **UPI ID** so checkout can show a UPI QR code
  with the exact amount (test it with a ₹1 payment).
- [ ] **Security & backup:** see step 6.

## 4. Users and roles

- [ ] Create one user **per person**. Never share the administrator login. The audit
  log records who did what.
- [ ] Give each person the right role:
  - **Cashier:** POS and sales only.
  - **Inventory Staff:** products, stock, purchases.
  - **Manager:** everything except users, settings and restore.
- [ ] Optionally create a second administrator account and keep its password sealed.
  This is your recovery route if the main password is lost.
- [ ] Set "sign out after inactivity" if the counter PC is ever left unattended.

## 5. Products and opening stock

- [ ] Count your stock (the physical count is your opening stock).
- [ ] **Products → Import from CSV… → Save template**, fill it in Excel (one row per
  product), and save as **CSV UTF-8**.
- [ ] **Choose CSV file.** Fix every problem listed (the row numbers match Excel rows),
  then import. Nothing is saved until every row is valid.
- [ ] Spot-check 10 products: price, tax rate, "price includes tax", stock.
- [ ] For items without a manufacturer barcode: **Print labels** (Products page).
- [ ] Run **Reports → Inventory valuation** and keep a printed or exported copy as your
  opening position.

## 6. Backups (do not skip)

- [ ] **Settings → Security & backup:**
  - "automatic backup once a day" **on**
  - "back up when the application is closed" **on**
- [ ] Set a **Second copy folder** on a different device:
  - a USB drive kept plugged in, or
  - a **OneDrive / Google Drive** folder that syncs to the cloud.

  This protects you if the PC fails, is stolen, or is hit by ransomware.
- [ ] Recommended: **Set backup password…** so every backup (including the USB/cloud
  copy) is encrypted. Write the password down and keep it somewhere safe: without
  it, encrypted backups cannot be restored.
- [ ] Make a manual backup to a USB drive: **Backup & Restore → Back up to…**
- [ ] **Practise a restore** before go-live, on a spare PC or a second Windows user:
  install, restore that USB backup, sign in, and check the data is there.
  A backup you have never restored is not proven.

## 7. Hardware

- [ ] Barcode scanner: set it to **USB keyboard (HID)** mode. Scan in POS; the item
  should be added to the cart.
- [ ] Printer: print a test invoice and a return note. Check that the paper size and
  margins look right.
- [ ] Label printer, if used: print one label sheet and scan a printed label.

## 8. Acceptance test

- [ ] Work through **docs/ACCEPTANCE-TEST.md** on the shop PC with the real printer and
  scanner. Every step must give the expected result.
- [ ] Afterwards, delete the test transactions' effect:
  - Void the test sales and cancel test purchases (they stay in history, marked void),
    or
  - Do the acceptance test **before** step 5 on a throw-away install, then uninstall
    and choose to delete its data.

## 9. Go live

- [ ] Day 1: compare the **Daily sales** report and **Payment-method sales** with the
  cash in the drawer and your UPI/card statements at closing.
- [ ] First week: check **Low stock** and **Audit log** daily.
- [ ] Every month: export Profit & Loss and Tax summary for your accountant.
  Confirm the backup copies are being written to the second folder.

## Daily routine (once live)

| When | What |
|---|---|
| Opening | Start BusinessPOS. Read any backup warning. |
| During the day | Each person uses their own login. Returns only against the original invoice. |
| Closing | Run Daily sales and Payment-method sales and match them to cash and statements. Close BusinessPOS: a backup is made automatically. |
| Weekly | Check Low stock. Plug in or check the backup drive. |
| Monthly | Export reports for your accountant. Do a test restore every few months. |

## If something goes wrong

- **Forgotten password:** another administrator can reset it (Users & Permissions).
- **PC failed:** install BusinessPOS on a new PC, finish the setup wizard (any
  details; they will be replaced), then **Backup & Restore → Restore** your latest
  backup from the second copy folder.
- **Error message:** the details are in `%LOCALAPPDATA%\BusinessPOS\logs\businesspos.log`.
  No partial sale is ever saved; every transaction is all-or-nothing.
