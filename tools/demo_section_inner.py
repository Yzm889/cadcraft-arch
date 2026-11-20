"""室内隔墙 + 梁 的剖面样例（v1.0.25）。

一套小房子：6000×3000，中间一道 120 厚横隔墙（W005），外墙上开一樘门一樘窗。
1-1 剖切线切在 X=900，穿过南墙的门、中间隔墙、北墙 → 剖面里能看到：
  · 两端外墙窄带 + 南墙门（LEFT）；
  · 中间 120 厚隔墙窄带（落在剖面中部，不是"看不到"的细线）；
  · 二层楼板下挂一根 500 高主梁。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    annot_size,
    create_axis_grid,
    create_opening,
    create_section,
    create_section_mark,
    create_title_mark,
    create_wall,
    drawing_extent,
    export,
    read_cut_openings,
    read_floors,
    set_drawing_scale,
)

OUT = ROOT / "samples"
SCALE = 100
FLOORS = [{"height": 3600.0, "plan": "建-01", "name": "一层平面"},
          {"height": 3300.0, "plan": "建-02", "name": "二层平面"}]


def main() -> int:
    OUT.mkdir(exist_ok=True)
    path = OUT / "demo_section_inner.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, SCALE, rescale=False)

    create_axis_grid(s, "AX001", 3, 3000.0, 2, 3000.0, ext=annot_size(20.0, SCALE))
    for wid, p1, p2, th in (
        ("W001", (0.0, 0.0), (6000.0, 0.0), 240.0),
        ("W002", (6000.0, 0.0), (6000.0, 3000.0), 240.0),
        ("W003", (6000.0, 3000.0), (0.0, 3000.0), 240.0),
        ("W004", (0.0, 3000.0), (0.0, 0.0), 240.0),
        ("W005", (0.0, 1500.0), (6000.0, 1500.0), 120.0),
    ):
        create_wall(s, wid, p1, p2, thick=th, kind="PARTITION" if wid == "W005" else "EXTERNAL")
    create_opening(s, "M001", "W001", "DOOR", width=900.0, pos=900.0,
                   height=2100.0, no="M0921")
    create_opening(s, "C001", "W002", "WINDOW", width=1500.0, pos=1200.0,
                   height=1500.0, sill=900.0, no="C1215")
    # 隔墙上的门就开在剖切线位置（X=900），剖面隔墙要按它断墙
    create_opening(s, "M002", "W005", "DOOR", width=800.0, pos=900.0,
                   height=2100.0, no="M0821")

    create_section_mark(s, "SM1", (900.0, -1200.0), (900.0, 4200.0),
                        direction="left", no="1", scale=SCALE)

    cut_all = read_cut_openings(s, (900.0, -1200.0), (900.0, 4200.0))
    assert [(o["wall"], o["side"]) for o in cut_all] == [("W001", "LEFT"), ("W005", "LEFT")], cut_all
    cut_ops = read_cut_openings(s, (900.0, -1200.0), (900.0, 4200.0), walls=["W001"])
    assert [(o["side"], o["kind"]) for o in cut_ops] == [("LEFT", "DOOR")], cut_ops

    create_section(
        s, "P1", (0.0, -9000.0), 2760.0, FLOORS,
        openings=cut_ops, side="BOTH", slab=100.0, roof="FLAT", parapet=900.0,
        wall=240.0,
        inner_walls=[{"x": 1380.0, "thick": 120.0,
                      "openings": [{"floor": 1, "h": 2100.0, "sill": 0.0,
                                   "kind": "DOOR"}]}],
        beams=[{"floor": 2, "x0": 240.0, "x1": 2520.0, "h": 500.0}],
    )
    create_title_mark(s, "T01", (3000.0, -1200.0), "一层平面图", SCALE)
    create_title_mark(s, "T02", (1380.0, -11700.0), "1-1 剖面图", SCALE)

    e = drawing_extent(s, pad=0.0)
    print("extent: %r" % (e,))
    export(s, OUT / "demo_section_inner.png", window=(-1800.0, -10600.0, 7600.0, 4400.0))
    export(s, OUT / "demo_section_inner_low.png",
           window=(-300.0, -9400.0, 3300.0, -6970.0))
    export(s, OUT / "demo_section_inner_high.png",
           window=(-300.0, -6970.0, 3300.0, -4540.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
