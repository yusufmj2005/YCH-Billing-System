# Changelog

## 1.2.0

Razorpay payments. No database changes; installing over 1.1.x or 1.0.x keeps all data.

### Added
- **Razorpay at checkout** (optional; Settings › Payments › Razorpay). The **Razorpay**
  button shows a Razorpay UPI QR for the amount due, or a **payment link** (UPI, cards,
  net banking, wallets) as a QR code and optionally by SMS. BusinessPOS checks with
  Razorpay every few seconds and records the payment, with its `pay_…` ID, only once
  Razorpay confirms it is captured for the exact amount. Split payments work.
- Safe by design: cancelling closes the QR or link at Razorpay, and a payment made at that
  last moment is still recorded. A Razorpay payment can't be recorded without a confirmed
  ID, and one payment can't pay for two invoices. Leaving checkout or removing a received
  Razorpay payment asks first. Internet drops while waiting are retried.
- **Already paid? Enter payment ID**: recover a payment whose window was closed. It is
  checked with Razorpay (captured, exact amount, not used before).
- **Check Razorpay payments** (Sales, and Settings › Payments): a day's Razorpay payments
  next to the invoices that recorded them. Unrecorded money and unknown IDs are flagged.
- Test mode (`rzp_test_` keys) is clearly marked at checkout.
- Returns: choosing Razorpay as the refund method reminds you to refund in the Razorpay
  Dashboard and record the `rfnd_…` ID.
- Guide: docs/RAZORPAY.md; acceptance test section K.

### Security
- The Key Secret is verified with Razorpay before saving and stored encrypted with Windows
  DPAPI (this Windows user on this PC only). It is never shown, logged or exported, and
  only *Manage settings* users can connect or disconnect Razorpay.

### Changed
- New dependency: `certifi` (Mozilla's CA certificates) so HTTPS to Razorpay works even on
  a freshly installed Windows. Listed in THIRD-PARTY-NOTICES.md. The packaged self-test now
  also checks secret protection, the HTTPS certificates and the Razorpay service.

## 1.1.1

Faster UPI at checkout. No database changes; installing over 1.1.0 or 1.0.x keeps all data.

### Changed
- **Choosing UPI at checkout opens the QR code straight away** for the amount
  due; no extra click. *Payment received* records it, then Enter completes the
  sale. *Show UPI QR* is still there to show it again.
- **First-time set-up from checkout.** If no UPI ID has been saved yet, an
  administrator is asked for it once (saved to Settings › Payments) and the QR
  opens. *Not now* skips it until the program is restarted. Cashiers see a note
  to ask an administrator. UPI payments can always be recorded by hand.

## 1.1.0

New features for everyday billing, tax filing and data safety. No database
changes; installing over 1.0.x keeps all data.

### Added
- **UPI QR at checkout.** Set your UPI ID in Settings › Payments. With UPI
  selected at checkout, *Show UPI QR* displays a code for the exact amount that
  any UPI app can scan, with no gateway and no fees. *Payment received* records it
  (split payments work too).
- **GSTR-1 working reports** (Reports › GST returns): B2B invoices, B2C summary,
  credit notes for registered customers, HSN summary (B2B/B2C) and documents
  issued. Built from the tax recorded on each invoice line, they reconcile exactly
  with the tax summary. Export to CSV or PDF for your accountant.
- **Backup password** (Settings › Security & backup). Every backup, including
  the second copy on USB or cloud, is encrypted with AES-256. Restoring on another
  computer asks for the password; a wrong password or a damaged file is
  rejected. Restoring an older backup keeps this computer's password setting.
- **Find the original invoice when the receipt is lost** (Returns › Find
  invoice). Search recent invoices by product name, SKU, barcode, customer name
  or phone. The return stays linked to the invoice, as GST credit notes require.

### Changed
- New dependency: `cryptography` 50.0.2 (with `cffi` and `pycparser`), listed
  in THIRD-PARTY-NOTICES.md. The installed program's self-test now also checks
  an encrypted backup and UPI QR generation.

## 1.0.2

Publisher and signing update. No database changes; installing over 1.0.1 keeps all data.

### Added
- **Automatic code signing for releases.** Once SSL.com eSigner secrets are added
  to the repository, release builds sign the program, the installer and the
  uninstaller, and refuse to publish unless every signature is valid. This
  removes the "Windows protected your PC" warning. See `docs/CODE-SIGNING.md`.

### Changed
- The build's GitHub actions moved to Node 24 versions.
- The licence's copyright holder is now **Mohammed Yusuf J**.
- The installer's publisher (shown in Windows *Apps & features*) is now **Mohammed Yusuf J**. The program's file properties (company and copyright) show the same name.

## 1.0.1

Bug-fix and go-live release. Existing databases are upgraded automatically on
first start, after an automatic `pre-upgrade-v1` backup (schema v1 → v2).

### Fixed
- **Refunds on rounded invoices.** A full return refunded the line totals and
  ignored the invoice round-off. For example, a ₹100.40 sale charged ₹100 refunded
  ₹100.40. The return that completes an invoice now includes the round-off, so
  total refunds always equal the amount paid. Profit & Loss, the return note and
  the return screen show it.
- **Backups to folders whose names contain `#`, `?` or `%`** failed (e.g.
  `D:\Backups #2`, or a Windows user folder with `#`). Restoring from such a folder
  failed too.
- **A non-administrator with "Manage users" could deactivate an Administrator.**
- **Setup wizard:** a tax rate typed but not added was silently dropped when
  pressing Next.
- **Invoice prefixes containing `_` or `%`** were treated as wildcards when
  checking earlier invoice numbers.
- **Invalid numbers sent to the services** (non-numeric discount %, huge amounts)
  now give a clear message instead of a technical error.
- **A refused or failed database open** no longer leaves the file open.

### Added
- **Bulk product import from CSV/Excel** (Products → Import from CSV…). It is
  all-or-nothing and lists every problem with its row number.
- **Backup when the application closes** (on by default), in addition to the daily
  start-up backup.
- **Second backup copy folder** (USB drive or cloud-synced folder). Every automatic
  backup is copied there and verified. You are warned at start-up and at closing if
  the folder is unavailable.
- **Automated Windows build (GitHub Actions)**: tests, build, packaged self-test and
  a real install → self-test → uninstall of the produced installer on a clean
  machine. Releases are built from pinned dependency versions.
- **Tests:** 87 → 162. They now include end-to-end reconciliation of every report,
  the setup wizard and sign-in screens, and the business rules for every module.
- **Documentation:** `docs/GO-LIVE-CHECKLIST.md` and `docs/ACCEPTANCE-TEST.md`.
- **Licence:** BusinessPOS is now distributed under a proprietary licence (`LICENSE`), shown and accepted during installation. Third-party open-source components are listed in `THIRD-PARTY-NOTICES.md`, which is installed alongside the program.
- **README** rewritten for shop owners and developers, with screenshots.

### Removed
- The committed `installer_output/BusinessPOS-Setup.exe`. It was the 1.0.0 build
  with the bugs above. Installers now come only from the automated build.

## 1.0.0
- First release.
