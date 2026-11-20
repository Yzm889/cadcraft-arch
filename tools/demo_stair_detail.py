"""楼梯间大样样例（v1.0.37）：平面楼梯 + 1:20 大样。

直跑/双跑各一张大样；平面上放索引符号，大样下带图名。
产出：demo_stair_detail.png（平面+大样总览）、demo_stair_detail_big.png（大样放大）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    create_detail_mark,
    create_stair,
    create_stair_detail,
    export,
    set_drawing_scale,
)

OUT = ROOT / "samples" / "demo_stair_detail.dxf"


def main() -> int:
    s = Session(OUT)
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)

    create_stair(s, "ST1", (0.0, 0.0), kind="DOGLEG", width=1200, steps=10,
                 tread=280, well=120, landing=1200, angle=0, level="MIDDLE", side="LEFT")
    create_detail_mark(s, "DM1", (-1800.0, -900.0), "1", "2")

    create_stair_detail(s, "SD1", (0.0, -27000.0), "ST1", ratio=20)

    export(s, ROOT / "samples" / "demo_stair_detail_plan.png",
           window=(-3800.0, -4200.0, 6200.0, 5200.0))
    export(s, ROOT / "samples" / "demo_stair_detail_big.png",
           window=(-3500.0, -30500.0, 16500.0, -2500.0))
    print("OK demo_stair_detail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
