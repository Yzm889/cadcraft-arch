"""M-VERT 集成样板：一层平面同时落电梯 + 坡道 + 阳台，并接门窗/房间/尺寸/图框/PNG。

复现：
    python tools/build_integration.py
产物：
    samples/integration_mvert/integration_plan.dxf
    samples/integration_mvert/integration_plan.png
    samples/integration_mvert/integration_readback.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    annotate,
    audit,
    create_balcony,
    create_elevator,
    create_opening,
    create_ramp,
    create_room,
    create_sheet,
    create_wall,
    draw_table,
    export,
    normalize_all_walls,
    opening_data,
    room_data,
    sheet_window,
    wall_data,
)

OUT = ROOT / "samples" / "integration_mvert"
OUT.mkdir(parents=True, exist_ok=True)
path = OUT / "integration_plan.dxf"
if path.exists():
    path.unlink()

s = Session(path)
s.new_metric()

# 1) 批量落墙：先不逐面规整，最后 normalize_all_walls 一次合角。
#    一层外轮廓 12000×8000；内隔墙 x=7000；电梯井净空 2200×2200，中心 9600,1700。
create_wall(s, "W001", (0.0, 0.0), (12000.0, 0.0), thick=240.0,
            kind="EXTERNAL", normalize=False)
create_wall(s, "W002", (12000.0, 0.0), (12000.0, 8000.0), thick=240.0,
            kind="EXTERNAL", normalize=False)
create_wall(s, "W003", (12000.0, 8000.0), (0.0, 8000.0), thick=240.0,
            kind="EXTERNAL", normalize=False)
create_wall(s, "W004", (0.0, 8000.0), (0.0, 0.0), thick=240.0,
            kind="EXTERNAL", normalize=False)
create_wall(s, "W005", (7000.0, 0.0), (7000.0, 8000.0), thick=240.0,
            kind="INTERNAL", normalize=False)
create_wall(s, "W101", (8380.0, 480.0), (10820.0, 480.0), thick=240.0,
            kind="INTERNAL", normalize=False)
create_wall(s, "W102", (8380.0, 2920.0), (10820.0, 2920.0), thick=240.0,
            kind="INTERNAL", normalize=False)
create_wall(s, "W103", (8380.0, 480.0), (8380.0, 2920.0), thick=240.0,
            kind="INTERNAL", normalize=False)
create_wall(s, "W104", (10820.0, 480.0), (10820.0, 2920.0), thick=240.0,
            kind="INTERNAL", normalize=False)

normalize_all_walls(s)

# 2) 房间、门窗、阳台（依托已合角的墙网）
create_room(s, "R001", ["W001", "W002", "W003", "W004"], "门厅")
create_opening(s, "D001", "W001", "DOOR", width=1000.0, pos=1000.0, height=2100.0)
create_opening(s, "C001", "W003", "WINDOW", width=1800.0, pos=3000.0, height=1500.0)
create_balcony(s, "BA001", "W001", pos=9000.0, width=3000.0, depth=1200.0,
               rail=100.0, label="阳台")

# 3) 电梯 + 坡道
create_elevator(
    s, "EL001", (9600.0, 1700.0), shaft=(2200.0, 2200.0),
    car=(1600.0, 1400.0), door=1100.0, door_h=2100.0,
    door_side="S", cw_side="N",
    shaft_walls={"N": "W102", "E": "W104", "S": "W101", "W": "W103"},
)
create_ramp(s, "RP001", (-4200.0, 3000.0), (-120.0, 3000.0),
            width=1500.0, slope=12.0, rail=True, arrow="UP")

# 4) 尺寸 + 右侧附表 + A4 图框/标题栏（图签移到平面下方，避免压图）
dims = annotate(s)
draw_table(
    s, (14000.0, 5000.0), "门窗表",
    ["编号", "名称", "洞口尺寸", "数量"],
    [["D001", "门", "1000×2100", "1"],
     ["C001", "窗", "1800×1500", "1"],
     ["EL001-D", "电梯门", "1100×2100", "1"]],
    [1800.0, 1800.0, 2600.0, 1200.0],
)
draw_table(
    s, (14000.0, 1000.0), "房间面积表",
    ["编号", "名称", "净面积(m2)"],
    [["R001", "门厅", "91.34"], ["合计", "—", "91.34"]],
    [1800.0, 2600.0, 2600.0],
)
draw_table(
    s, (14000.0, 9000.0), "主要指标",
    ["项目", "数值"],
    [["层数", "1"], ["耐火等级", "二级"]],
    [3000.0, 3000.0],
)
sheet = create_sheet(
    s, "SH001", "A4", at=(-7000.0, -8000.0),
    project="M-VERT 集成样板", drawing="一层平面图",
    number="建-01", date="2026-11-24", design="", unit="mm",
)
png = OUT / "integration_plan.png"
exp = export(s, png, window=sheet_window(s, "SH001"))

report = {
    "dxf": str(path),
    "png": str(png),
    "png_bytes": exp["bytes"],
    "sheet": sheet,
    "dims": dims,
    "counts": {
        "walls": len(wall_data(s)),
        "openings": len(opening_data(s)),
        "rooms": len(room_data(s)),
    },
    "elevator": s.attributes("AA_ELEVATOR_EL001"),
    "ramp": s.attributes("AA_RAMP_RP001"),
    "balcony": s.attributes("AA_BALCONY_BA001"),
    "audit": audit(s),
}
(OUT / "integration_readback.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps({
    "dxf": str(path), "png": str(png), "png_bytes": exp["bytes"],
    "counts": report["counts"], "dims": dims, "audit": report["audit"],
}, ensure_ascii=False, indent=2))
