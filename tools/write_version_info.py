"""Write build/version_info.txt (Windows file properties for BusinessPOS.exe)
and print the version so build scripts can pass it to Inno Setup."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config.constants import APP_NAME, APP_VERSION  # noqa: E402

parts = [int(p) for p in APP_VERSION.split(".")] + [0] * 4
v = tuple(parts[:4])
TEMPLATE = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', '{APP_NAME} - Point of Sale & Business Management'),
      StringStruct('FileVersion', '{APP_VERSION}'),
      StringStruct('InternalName', '{APP_NAME}'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 yusufmj2005. All rights reserved.'),
      StringStruct('OriginalFilename', '{APP_NAME}.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{APP_VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

if __name__ == "__main__":
    out = ROOT / "build" / "version_info.txt"
    out.write_text(TEMPLATE, encoding="utf-8")
    print(APP_VERSION)
