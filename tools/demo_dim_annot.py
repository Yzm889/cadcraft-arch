"""三道尺寸 + 注字/引注样例（v1.0.41）：洞口/轴线/总尺寸三道不压线。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session, annotate, auto_rooms, create_leader, create_opening, create_text,
    create_wall, export, normalize_around, set_drawing_scale,
)


def main() -> int:
    s = Session(ROOT / "samples" / "demo_dim_annot.dxf")
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)

    walls = [("W001", (0.0, 0.0), (6000.0, 0.0)),
             ("W002", (6000.0, 0.0), (6000.0, 4800.0)),
             ("W003", (6000.0, 4800.0), (0.0, 4800.0)),
             ("W004", (0.0, 4800.0), (0.0, 0.0))]
    for wid, p1, p2 in walls:
        create_wall(s, wid, p1, p2, thick=240.0, kind="EXTERNAL")
        normalize_around(s, wid)
    create_opening(s, "D001", "W001", "DOOR", 1000.0, 1000.0, 2100.0)
    create_opening(s, "C001", "W002", "WINDOW", 1500.0, 2400.0, 1500.0)
    auto_rooms(s)

    res = annotate(s)
    print("dims=%d walls=%d openings=%d totals=%d"
          % (res["dims"], res["walls"], res["openings"], res["totals"]))
    create_text(s, "T1", (-2200.0, 5200.0), "外墙 240 厚", height=3.5)
    create_leader(s, "L1", (6000.0, 1500.0), "窗台 1500", to=(3000.0, 1300.0))

    export(s, ROOT / "samples" / "demo_dim_annot.png",
           window=(-3600.0, -2600.0, 8600.0, 7800.0))
    print("OK demo_dim_annot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
