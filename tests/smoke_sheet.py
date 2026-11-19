"""图框 / 标题栏 / 出图 冒烟测试：A3@1:100 手工定位。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from aa_lib import Session, create_sheet, export, sheet_layout, sheet_window, set_sheet  # noqa: E402

p = Path(__file__).resolve().parent.parent / "samples" / "scratch_sheet.dxf"
if p.exists():
    p.unlink()
s = Session(p)
s.new_metric()
r = create_sheet(s, "S001", size="A3", scale=100, at=(0, 0),
                 project="演示工程", drawing="一层平面图", number="建-01",
                 date="2026-11-19", design="严", unit="某设计院")
print(r)
lay = sheet_layout("A3", 100)
print(lay["outer"])
pdf = export(s, p.with_suffix(".pdf"), window=sheet_window(s, "S001"))
print(pdf)
