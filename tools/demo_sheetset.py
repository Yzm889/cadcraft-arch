"""多图幅套图样例（v1.0.33）：一张模型图里排四张图幅 + 图纸目录，按图纸集批量出图。

图纸集：建施-00 图纸目录（A4）/ 建施-01 一层平面（A3）/ 建施-02 屋顶平面（A3）/
建施-03 立面（A3）/ 建施-04 剖面（A3）。每张图的内容画在各自图幅范围内（模型空间排图），
出图按 `sheet_window` 逐张裁切，文件名 = 图号_图名.png。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    create_axis_grid,
    create_elevation,
    create_north_arrow,
    create_opening,
    create_roof,
    create_room,
    create_section,
    create_section_mark,
    create_sheet,
    create_sheet_index,
    create_sheet_set,
    create_title_mark,
    create_wall,
    export_sheet_set,
    read_facade_openings,
    set_drawing_scale,
    Session,
)

OUT = ROOT / "samples"
SCALE = 100
FLOORS = [
    {"height": 3600.0, "plan": "建施-01", "name": "一层平面"},
    {"height": 3300.0, "plan": "建施-02", "name": "二层平面"},
    {"height": 3300.0, "plan": "建施-03", "name": "三层平面"},
]


def main() -> int:
    OUT.mkdir(exist_ok=True)
    path = OUT / "demo_sheetset.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, SCALE, rescale=False)

    # ---------- 建施-01 一层平面（0,0 起） ----------
    create_axis_grid(s, "AX001", 3, 3600.0, 2, 4500.0, ext=2400.0)
    for wid, p1, p2 in (
        ("W001", (0.0, 0.0), (7200.0, 0.0)),
        ("W002", (7200.0, 0.0), (7200.0, 4500.0)),
        ("W003", (7200.0, 4500.0), (0.0, 4500.0)),
        ("W004", (0.0, 4500.0), (0.0, 0.0)),
    ):
        create_wall(s, wid, p1, p2, thick=240.0, kind="EXTERNAL", snap_axis=True)
    create_opening(s, "M001", "W001", "DOOR", width=900.0, pos=1500.0, no="M0921")
    create_opening(s, "C001", "W001", "WINDOW", width=1500.0, pos=5000.0,
                   height=1500.0, sill=900.0, no="C1515")
    create_opening(s, "C002", "W003", "WINDOW", width=1200.0, pos=5600.0,
                   height=1500.0, sill=900.0, no="C1215")
    create_room(s, "R001", ["W001", "W002", "W003", "W004"], name="普通教室")
    create_section_mark(s, "SM1", (1500.0, -1200.0), (1500.0, 5700.0),
                        direction="left", no="1", scale=SCALE)
    create_title_mark(s, "T01", (3600.0, -3300.0), "一层平面图", SCALE)

    # ---------- 建施-02 屋顶平面（40000, 0 起） ----------
    rx = 70000.0
    create_roof(s, "RF1", (rx + 0.0, 0.0), kind="GABLE", width=7200.0, depth=4500.0,
                overhang=600.0, ridge="X")
    create_axis_grid(s, "AX002", 3, 3600.0, 2, 4500.0, xstart=rx, ystart=0.0, ext=2400.0)
    create_title_mark(s, "T02", (rx + 3600.0, -3300.0), "屋顶平面图", SCALE)

    # ---------- 建施-03 立面（80000,-16000 起） ----------
    ex = 140000.0
    plan_ops = read_facade_openings(s, "W001")
    elev_ops = plan_ops + [
        {"floor": 2, "x": o["x"], "w": o["w"], "h": o["h"], "sill": o["sill"],
         "kind": o["kind"]}
        for o in plan_ops
    ] + [
        {"floor": 3, "x": o["x"], "w": o["w"], "h": o["h"], "sill": o["sill"],
         "kind": o["kind"]}
        for o in plan_ops
    ]
    create_elevation(s, "E1", (ex + 0.0, -16000.0), 7200.0, FLOORS,
                     openings=elev_ops, roof="EAVE", rise=1800.0, eave=200.0,
                     axes=[{"x": 0.0, "label": "1"}, {"x": 3600.0, "label": "2"},
                           {"x": 7200.0, "label": "3"}])
    create_title_mark(s, "T03", (ex + 3600.0, -19300.0), "1-3 立面图", SCALE)

    # ---------- 建施-04 剖面（120000,-16000 起） ----------
    px = 210000.0
    create_section(s, "P1", (px + 0.0, -16000.0), 4500.0, FLOORS,
                   openings=[{"floor": 1, "h": 2100.0, "sill": 0.0, "kind": "DOOR",
                              "side": "LEFT"},
                             {"floor": 1, "h": 1500.0, "sill": 900.0, "kind": "WINDOW",
                              "side": "RIGHT"}],
                   side="BOTH", slab=100.0, roof="GABLE", parapet=0.0,
                   rise=1800.0, wall=240.0)
    create_title_mark(s, "T04", (px + 2250.0, -19300.0), "1-1 剖面图", SCALE)

    # ---------- 图幅：按各图内容中心居中，图幅之间留足间距（A3@1:100 = 42000×29700） ----------
    from aa_lib import sheet_layout

    def frame_at(size: str, cx: float, cy: float) -> tuple[float, float]:
        lay = sheet_layout(size, SCALE)
        return (cx - lay["inner_w"] / 2.0, cy - lay["inner_h"] / 2.0)

    sheets = {}
    for sid, size, center, drawing, number in (
        ("S000", "A4", (293000.0, 9000.0), "图纸目录", "建施-00"),
        ("S001", "A3", (8600.0, 2150.0), "一层平面图", "建施-01"),
        ("S002", "A3", (74600.0, 2250.0), "屋顶平面图", "建施-02"),
        ("S003", "A3", (148600.0, -10100.0), "1-3 立面图", "建施-03"),
        ("S004", "A3", (217250.0, -10000.0), "1-1 剖面图", "建施-04"),
    ):
        sheets[sid] = create_sheet(
            s, sid, size=size, scale=SCALE, at=frame_at(size, *center),
            project="CADCraft 套图样例", drawing=drawing, number=number,
            date="2026-11-21", design="严", drawn="严", check="", unit="CADCraft")

    p_lay = sheet_layout("A3", SCALE)
    p_at = frame_at("A3", 8600.0, 2150.0)
    create_north_arrow(s, "N001", (p_at[0] + p_lay["inner_w"] - 3000.0,
                                  p_at[1] + p_lay["inner_h"] - 3000.0))

    # ---------- 图纸集 + 图纸目录 ----------
    create_sheet_set(s, "SS1", [
        {"no": "建施-00", "name": "图纸目录", "sheet": "S000"},
        {"no": "建施-01", "name": "一层平面图", "sheet": "S001", "note": "1:100"},
        {"no": "建施-02", "name": "屋顶平面图", "sheet": "S002", "note": "1:100"},
        {"no": "建施-03", "name": "1-3 立面图", "sheet": "S003", "note": "1:100"},
        {"no": "建施-04", "name": "1-1 剖面图", "sheet": "S004", "note": "1:100"},
    ])
    i_lay = sheet_layout("A4", SCALE)
    i_at = frame_at("A4", 293000.0, 9000.0)
    create_sheet_index(s, "SS1", "ML1",
                       (i_at[0] + (i_lay["inner_w"] - 16600.0) / 2.0,
                        i_at[1] + i_lay["inner_h"] - 3000.0),
                       note="注：本图册共 5 张，比例除注明外均为 1:100。")

    outdir = OUT / "demo_sheetset_out"
    for f in outdir.glob("*"):
        f.unlink()
    res = export_sheet_set(s, "SS1", outdir, fmt="png")
    print("图纸集:", res["count"], "张 →", res["outdir"])
    for f in res["files"]:
        print("  %-28s %s bytes" % (Path(f["path"]).name, f["bytes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
