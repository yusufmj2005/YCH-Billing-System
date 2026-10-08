# Third-party notices

BusinessPOS is proprietary software (see [LICENSE](LICENSE)). The installer
also contains the open-source components below. Each one is licensed to you
under its own licence, and nothing in the BusinessPOS licence restricts the
rights those licences grant.

| Component | Version in 1.0.2 | Licence | Project |
|---|---|---|---|
| Python runtime | 3.12 | Python Software Foundation License | https://www.python.org |
| Qt for Python (PySide6, shiboken6) and the Qt libraries | 6.11.2 | GNU LGPL v3 | https://www.qt.io/qt-for-python |
| SQLAlchemy | 2.0.54 | MIT | https://www.sqlalchemy.org |
| greenlet | 3.5.6 | MIT / PSF | https://github.com/python-greenlet/greenlet |
| bcrypt | 5.0.0 | Apache License 2.0 | https://github.com/pyca/bcrypt |
| ReportLab (open-source toolkit) | 4.5.1 | BSD-style (ReportLab Open Source License) | https://www.reportlab.com |
| Pillow | 12.3.0 | MIT-CMU (HPND) | https://python-pillow.org |
| charset-normalizer | 3.5.2 | MIT | https://github.com/jawah/charset_normalizer |
| typing_extensions | 4.16.0 | PSF License | https://github.com/python/typing_extensions |
| PyInstaller bootloader | 6.22.3 | GPL v2 with the bootloader exception (allows use in programs under any licence) | https://pyinstaller.org |
| SQLite (bundled with Python) | — | Public domain | https://sqlite.org |

## Qt / PySide6 (LGPL v3)

BusinessPOS uses the Qt and PySide6 libraries without modifying them. They are
installed as separate files in the `_internal` folder of the program directory.
As the LGPL v3 allows, you may replace those files with your own compatible
builds of the same libraries. The full licence text is at
https://www.gnu.org/licenses/lgpl-3.0.html. The source code for these libraries
is available from https://code.qt.io and https://download.qt.io/official_releases/QtForPython/.

## Licence texts

The complete licence text of each component is included in its distribution
(in the `_internal` folder of the installed program, under each package's
`*.dist-info` folder where provided) and at the project addresses above.

Build-only tools (pytest, PyInstaller itself, Inno Setup) are used to produce
the installer and are not part of the installed program, except for the
PyInstaller bootloader noted above.
