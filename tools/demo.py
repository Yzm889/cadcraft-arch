"""生成演示平面图：轴网 + 外墙 + 隔墙 + 门窗 + 两个房间，并导出 PNG 供目视检查。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    annot_size,
    annotate,
    auto_axis,
    create_axis_grid,
    create_opening,
    create_room,
    create_sheet,
    create_title_mark,
    create_north_arrow,
    create_column,
    create_step,
    create_apron,
    create_elevation_mark,
    create_index_mark,
    create_section_mark,
    audit,
    rescale_annotations,
    create_wall,
    drawing_extent,
    export,
    normalize_around,
    openings_report,
    rooms_report,
    set_drawing_scale,
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

    # 构造柱（240×240，落在四个外墙转角，天正常见做法）
    for cid, at in (("GZ1", (0.0, 0.0)), ("GZ2", (10800.0, 0.0)),
                    ("GZ3", (10800.0, 4800.0)), ("GZ4", (0.0, 4800.0))):
        create_column(s, cid, at, 240.0, 240.0)

    # 轴网：按墙自动推断（竖墙 0/6000/10800 -> 1/2/3，横墙 0/4800 -> A/B）
    grid = auto_axis(s, "AX001", tol=50.0, ext=2400.0)

    # 门窗
    create_opening(s, "D001", "W001", "DOOR", width=1000.0, pos=1000.0)
    create_opening(s, "D002", "W004", "DOOR", width=900.0, pos=2400.0)
    create_opening(s, "C001", "W002", "WINDOW", width=1800.0, pos=2400.0)
    create_opening(s, "C002", "W005", "WINDOW", width=1800.0, pos=3000.0, label_side="leader")

    # 室外台阶（M1021 门口，向南出挑）+ 东外墙散水
    create_step(s, "ST1", (1000.0, -ext / 2.0), 1500.0, 2, 300.0, 270.0)
    create_apron(s, "SW1", (10800.0 + ext / 2.0, 2400.0), 4800.0, 600.0, 0.0)

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
    # B1 图面符号：室内标高、门窗索引、横贯两室的剖切符号
    create_elevation_mark(sf, "E001", (3000.0, 1200.0), 0.0)
    create_index_mark(sf, "I001", (9100.0, 3800.0), "1")
    create_section_mark(sf, "S001", (-1400.0, 2400.0), (12000.0, 2400.0),
                        direction="down", no="1")
    chk = audit(sf)
    print("audit demo_full:", chk["count"], chk["by_kind"])
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

    # 正常流程演示：开图先定 1:50，再画所有构件（对比 demo_scale_50 的"画完再改比例"）
    pre = OUT / "demo_scale_pre.dxf"
    if pre.exists():
        pre.unlink()
    sp = Session(pre)
    sp.new_metric()
    set_drawing_scale(sp, 50, rescale=False)
    create_axis_grid(sp, "AX001", 3, 3600.0, 2, 4500.0, ext=annot_size(24.0, 50))
    for wid, p1, p2 in (
        ("W001", (0.0, 0.0), (7200.0, 0.0)),
        ("W002", (0.0, 0.0), (0.0, 4500.0)),
        ("W003", (7200.0, 0.0), (7200.0, 4500.0)),
        ("W004", (0.0, 4500.0), (7200.0, 4500.0)),
    ):
        create_wall(sp, wid, p1, p2, thick=240.0, snap_axis=True)
    create_opening(sp, "M001", "W001", "DOOR", width=900.0, pos=1200.0, no="M0921")
    create_opening(sp, "C001", "W001", "WINDOW", width=1500.0, pos=4200.0, no="C1215")
    create_room(sp, "R001", ["W001", "W002", "W003", "W004"], name="客厅")
    annotate(sp)
    ext_sp = drawing_extent(sp, pad=0.0)
    create_title_mark(
        sp, "T001",
        ((ext_sp[0] + ext_sp[2]) / 2.0 - annot_size(30.0, 50),
         ext_sp[1] - annot_size(20.0, 50)),
        "一层平面图", None)
    sheet_pre = create_sheet(
        sp, "S001", size="AUTO",
        project="CADCraft 演示工程", drawing="一层平面图", number="建-01",
        date="2026-11-20", design="严", drawn="严", check="", unit="CADCraft",
    )
    # 指北针放在内框右上角（跟着图幅走，不跟模型坐标）
    create_north_arrow(
        sp, "N001",
        (sheet_pre["at"][0] + sheet_pre["inner"][0] - annot_size(30.0, 50),
         sheet_pre["at"][1] + sheet_pre["inner"][1] - annot_size(30.0, 50)))
    export(sp, OUT / "demo_scale_pre.png", sheet_window(sp, "S001"))

    print("rooms: 客厅 %.0f mm²  卧室 %.0f mm²" % (r1["area"], r2["area"]))
    print("png:", png, png.exists())
    print("grid: %s  ver=%s hor=%s" % (grid["xpos"], grid["ver"], grid["hor"]))
    print("components:", len(s.components("AA_")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
