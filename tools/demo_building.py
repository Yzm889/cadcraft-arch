"""一栋小楼全套图：平面 + 屋顶 + 楼层表 + 立面 + 剖面 拼在一张 A2 图纸上。

用来验"图面是否自洽"：比例、标高、轴网、门窗、图名字高能不能对齐。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aa_lib import (
    Session,
    annot_size,
    create_axis_grid,
    create_elevation,
    create_floor_table,
    create_north_arrow,
    create_opening,
    create_roof,
    create_room,
    create_section,
    create_sheet,
    create_section_mark,
    create_title_mark,
    create_wall,
    drawing_extent,
    export,
    read_cut_openings,
    read_facade_openings,
    read_floors,
    set_drawing_scale,
    sheet_window,
)

OUT = Path(__file__).resolve().parent.parent / "samples"
SCALE = 100

FLOORS = [
    {"height": 3600.0, "plan": "建-01", "name": "一层平面"},
    {"height": 3300.0, "plan": "建-02", "name": "二层平面"},
    {"height": 3300.0, "plan": "建-03", "name": "三层平面"},
]


def main() -> int:
    OUT.mkdir(exist_ok=True)
    path = OUT / "demo_building.dxf"
    if path.exists():
        path.unlink()
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, SCALE, rescale=False)

    ext = annot_size(24.0, SCALE)
    create_axis_grid(s, "AX001", 3, 3600.0, 2, 4500.0, ext=ext)
    for wid, p1, p2 in (
        ("W001", (0.0, 0.0), (7200.0, 0.0)),
        ("W002", (7200.0, 0.0), (7200.0, 4500.0)),
        ("W003", (7200.0, 4500.0), (0.0, 4500.0)),
        ("W004", (0.0, 4500.0), (0.0, 0.0)),
    ):
        create_wall(s, wid, p1, p2, thick=240.0, snap_axis=True,
                    kind="EXTERNAL" if wid in ("W001", "W002", "W003", "W004") else "PARTITION")
    create_opening(s, "M001", "W001", "DOOR", width=900.0, pos=1500.0, no="M0921")
    create_opening(s, "C001", "W001", "WINDOW", width=1500.0, pos=5000.0,
                    height=1500.0, sill=900.0, no="C1215")
    create_opening(s, "C002", "W003", "WINDOW", width=1200.0, pos=5600.0,
                    height=1500.0, sill=900.0, no="C0915")
    create_room(s, "R001", ["W001", "W002", "W003", "W004"], name="客厅")
    # 1-1 剖切符号：切在 X=1500（正好穿过首层门中心，也切到北墙的 C0915），往左看
    create_section_mark(s, "SM1", (1500.0, -1200.0), (1500.0, 5700.0),
                        direction="left", no="1", scale=SCALE)

    # 屋顶平面（同建筑外轮廓 + 檐口外挑），并补轴网：证明与一层平面同轴
    create_roof(s, "RF1", (0.0, 9500.0), kind="GABLE", width=7200.0, depth=4500.0,
                overhang=600.0, ridge="X")
    create_axis_grid(s, "AX002", 3, 3600.0, 2, 4500.0,
                     xstart=0.0, ystart=9500.0, ext=annot_size(14.0, SCALE))

    # 楼层表放平面右侧
    create_floor_table(s, "FT1", (8500.0, 1500.0), FLOORS, scale=SCALE)

    # 立面 / 剖面 放下方
    # 一层门窗不再手填坐标：直接读平面 W001 上的 AA_OPENING（左边距 = 中心 - 半宽）
    plan_ops = read_facade_openings(s, "W001")
    want = [(1050.0, 900.0, 2100.0, 0.0), (4250.0, 1500.0, 1500.0, 900.0)]
    got = [(o["x"], o["w"], o["h"], o["sill"]) for o in plan_ops]
    assert got == want, "平面门窗与立面口径对不上：%r != %r" % (got, want)

    elev_ops = plan_ops + [
        {"floor": 2, "x": 1050.0, "w": 1500.0, "h": 1500.0, "sill": 900.0},
        {"floor": 2, "x": 4250.0, "w": 1500.0, "h": 1500.0, "sill": 900.0},
        {"floor": 3, "x": 1050.0, "w": 1500.0, "h": 1500.0, "sill": 900.0},
        {"floor": 3, "x": 4250.0, "w": 1500.0, "h": 1500.0, "sill": 900.0},
    ]
    create_elevation(
        s, "E1", (0.0, -16000.0), 7200.0, FLOORS,
        openings=elev_ops,
        roof="EAVE", parapet=0.0, rise=1800.0, overhang=600.0)
    # 剖面门窗不再手填：沿 1-1 剖切线（X=1500）反取被切到的洞口——
    # 南墙首层门中心正好在 X=1500 → LEFT；北墙 C0915 跨 1000..2200，也切到 → RIGHT。
    cut_ops = read_cut_openings(s, (1500.0, -1200.0), (1500.0, 5700.0))
    assert [(o["side"], o["kind"], o["h"], o["sill"]) for o in cut_ops] == \
        [("LEFT", "DOOR", 2100.0, 0.0),
         ("RIGHT", "WINDOW", 1500.0, 900.0)], "剖面取数与剖切位置对不上：%r" % (cut_ops,)

    create_section(
        s, "P1", (9000.0, -16000.0), 4500.0, FLOORS,
        openings=cut_ops,
        side="BOTH", slab=100.0, roof="GABLE", parapet=0.0, rise=1800.0,
        wall=240.0)

    for tid, (x, y), label in (
        ("T01", (3600.0, -1200.0), "一层平面图"),
        ("T02", (3600.0, 8300.0), "屋顶平面图"),
        ("T03", (3600.0, -17800.0), "1-3 立面图"),
        ("T04", (11250.0, -17800.0), "1-1 剖面图"),
    ):
        create_title_mark(s, tid, (x, y), label, SCALE)

    e = drawing_extent(s, pad=0.0)
    sheet = create_sheet(
        s, "S001", size="A2", scale=SCALE,
        project="CADCraft 演示工程", drawing="全套建筑施工图（平面 / 屋顶 / 立面 / 剖面）",
        number="建-01", date="2026-11-20", design="严", drawn="严", check="",
        unit="CADCraft",
    )
    create_north_arrow(
        s, "N001",
        (sheet["at"][0] + sheet["inner"][0] - annot_size(30.0, SCALE),
         sheet["at"][1] + sheet["inner"][1] - annot_size(30.0, SCALE)))

    png = OUT / "demo_building.png"
    export(s, png, sheet_window(s, "S001"))
    print("floors:", read_floors(s, "FT1"))
    print("extent:", e)
    print("sheet:", sheet["size"], sheet["at"], sheet["inner"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
