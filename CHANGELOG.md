# Changelog

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
