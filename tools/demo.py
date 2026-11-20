"""生成演示平面图：轴网 + 外墙 + 隔墙 + 门窗 + 两个房间，并导出 PNG 供目视检查。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    annotate,
    auto_axis,
    create_opening,
    create_room,
    create_sheet,
    create_title_mark,
    create_north_arrow,
    rescale_annotations,
    create_wall,
    drawing_extent,
    export,
    normalize_around,
    openings_report,
    rooms_report,
    sheet_window,
)

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)


def main() -> int:
    path = OUT / "demo_floorplan.dxf"
    if path.exists():
        path.unlink()

    s = Session(path)
    s.new_metric()

    ext = 240.0
    # 外墙（按房间分段的实际墙段）
    create_wall(s, "W001", (0.0, 0.0), (6000.0, 0.0), thick=ext, kind="EXTERNAL", ax1="1", ax2="2")
    create_wall(s, "W002", (6000.0, 0.0), (10800.0, 0.0), thick=ext, kind="EXTERNAL", ax1="2", ax2="3")
    create_wall(s, "W003", (10800.0, 0.0), (10800.0, 4800.0), thick=ext, kind="EXTERNAL")
    create_wall(s, "W004", (10800.0, 4800.0), (6000.0, 4800.0), thick=ext, kind="EXTERNAL")
    create_wall(s, "W005", (6000.0, 4800.0), (0.0, 4800.0), thick=ext, kind="EXTERNAL")
    create_wall(s, "W006", (0.0, 4800.0), (0.0, 0.0), thick=ext, kind="EXTERNAL")
    # 中间隔墙
    create_wall(s, "W007", (6000.0, 0.0), (6000.0, 4800.0), thick=ext, kind="PARTITION")

    # 墙画完先规整一遍：转角合角 + 相交处墙线裁剪
    for wid in ("W001", "W002", "W003", "W004", "W005", "W006", "W007"):
        normalize_around(s, wid)

    # 轴网：按墙自动推断（竖墙 0/6000/10800 -> 1/2/3，横墙 0/4800 -> A/B）
    grid = auto_axis(s, "AX001", tol=50.0, ext=2400.0)

    # 门窗
    create_opening(s, "D001", "W001", "DOOR", width=1000.0, pos=1000.0)
    create_opening(s, "D002", "W004", "DOOR", width=900.0, pos=2400.0)
    create_opening(s, "C001", "W002", "WINDOW", width=1800.0, pos=2400.0)
    create_opening(s, "C002", "W005", "WINDOW", width=1800.0, pos=3000.0)

    # 房间（墙环闭合校验 + 内偏移面积）
    r1 = create_room(s, "R001", ["W001", "W007", "W005", "W006"], name="客厅")
    r2 = create_room(s, "R002", ["W002", "W003", "W004", "W007"], name="卧室")

    png = OUT / "demo_floorplan.png"
    export(s, png, drawing_extent(s, pad=1500.0))

    # 全套交付图：加尺寸标注 + 房间表 + 门窗表
    full = OUT / "demo_full.dxf"
    if full.exists():
        full.unlink()
    full.write_bytes(path.read_bytes())
    sf = Session(full)
    annotate(sf)
    rooms_report(sf, OUT / "demo_rooms.csv", (0.0, -3400.0), "房间面积表")
    openings_report(sf, OUT / "demo_openings.csv", (9900.0, -3400.0), "门窗表")
    # 图面符号：图名（表下方）+ 指北针（平面右上角）
    create_title_mark(sf, "T001", (0.0, -6600.0), "一层平面图", 100)
    create_north_arrow(sf, "N001", (15500.0, 4300.0))
    win_full = drawing_extent(sf, pad=1500.0)
    export(sf, OUT / "demo_full.png", win_full)

    # 出图交付：A3@1:100 图框 + 标题栏，导出 PNG / PDF
    sheet = OUT / "demo_sheet.dxf"
    if sheet.exists():
        sheet.unlink()
    sheet.write_bytes(full.read_bytes())
    ss = Session(sheet)
    create_sheet(
        ss, "S001", size="A3", scale=100,
        project="CADCraft 演示工程", drawing="一层平面图", number="建-01",
        date="2026-11-19", design="严", drawn="严", check="", unit="CADCraft",
    )
    win = sheet_window(ss, "S001")
    export(ss, OUT / "demo_sheet.png", win)
    export(ss, OUT / "demo_sheet.pdf", win)

    # 比例联动演示：同一张图改成 1:50 出图（A2 图幅），注记字号在纸上不变
    s50 = OUT / "demo_scale_50.dxf"
    if s50.exists():
        s50.unlink()
    s50.write_bytes(full.read_bytes())
    sf50 = Session(s50)
    rescale_annotations(sf50, 50)
    create_sheet(
        sf50, "S001", size="A2", scale=50,
        project="CADCraft 演示工程", drawing="一层平面图", number="建-01",
        date="2026-11-20", design="严", drawn="严", check="", unit="CADCraft",
    )
    export(sf50, OUT / "demo_scale_50.png", sheet_window(sf50, "S001"))

    print("rooms: 客厅 %.0f mm²  卧室 %.0f mm²" % (r1["area"], r2["area"]))
    print("png:", png, png.exists())
    print("grid: %s  ver=%s hor=%s" % (grid["xpos"], grid["ver"], grid["hor"]))
    print("components:", len(s.components("AA_")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
