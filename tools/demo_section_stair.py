"""楼梯断面样例（v1.0.27）。

一栋 6000×3600 的两层房子，1-1 切在 X=1500，正好剖到室内那跑楼梯：
  12 级踏步、踏步 300 高 / 250 宽，一跑到二层（3600），再加一条梯段板斜线。
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
    set_drawing_scale,
)

OUT = ROOT / "samples"
SCALE = 100
FLOORS = [{"height": 3600.0, "plan": "建-01", "name": "一层平面"},
          {"height": 3300.0, "plan": "建-02", "name": "二层平面"}]


def main() -> int:
    OUT.mkdir(exist_ok=True)
    path = OUT / "demo_section_stair.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, SCALE, rescale=False)

    create_axis_grid(s, "AX001", 3, 3000.0, 2, 3600.0, ext=annot_size(20.0, SCALE))
    for wid, p1, p2 in (
        ("W001", (0.0, 0.0), (6000.0, 0.0)),
        ("W002", (6000.0, 0.0), (6000.0, 3600.0)),
        ("W003", (6000.0, 3600.0), (0.0, 3600.0)),
        ("W004", (0.0, 3600.0), (0.0, 0.0)),
    ):
        create_wall(s, wid, p1, p2, thick=240.0, kind="EXTERNAL")
    create_opening(s, "M001", "W001", "DOOR", width=900.0, pos=1500.0,
                   height=2100.0, no="M0921")

    create_section_mark(s, "SM1", (1500.0, -1200.0), (1500.0, 4800.0),
                        direction="left", no="1", scale=SCALE)

    create_section(
        s, "P1", (0.0, -9000.0), 5520.0, FLOORS,
        openings=[{"floor": 1, "h": 2100.0, "sill": 0.0, "kind": "DOOR", "side": "LEFT"}],
        side="BOTH", slab=100.0, roof="FLAT", parapet=900.0, wall=240.0,
        beams=[{"floor": 2, "x0": 240.0, "x1": 5280.0, "h": 500.0}],
        stairs=[{"floor": 1, "x0": 240.0, "x1": 3240.0, "treads": 12}],
    )
    create_title_mark(s, "T01", (3000.0, -1200.0), "一层平面图", SCALE)
    create_title_mark(s, "T02", (2760.0, -11700.0), "1-1 剖面图", SCALE)

    e = drawing_extent(s, pad=0.0)
    print("extent: %r" % (e,))
    export(s, OUT / "demo_section_stair.png",
           window=(-1800.0, -10600.0, 7800.0, 5000.0))
    export(s, OUT / "demo_section_stair_sect.png",
           window=(-400.0, -7800.0, 5000.0, -6000.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
