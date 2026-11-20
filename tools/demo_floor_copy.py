"""标准层复制样例（v1.0.34）：一层平面整层复制成二层，门窗/房间跟随，层号自动改写。

输出 samples/demo_floor_copy.dxf 与 _1f.png / _2f.png（两个窗口对比，图形应完全一致、
只是 y 平移了 9000、层号从 1 变 2）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    copy_floor,
    create_opening,
    create_room,
    create_title_mark,
    create_wall,
    export,
    set_drawing_scale,
)

OUT = ROOT / "samples"
SCALE = 100


def main() -> int:
    path = OUT / "demo_floor_copy.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, SCALE, rescale=False)

    for i, (a, b) in enumerate((
        ((0.0, 0.0), (7200.0, 0.0)),
        ((7200.0, 0.0), (7200.0, 4500.0)),
        ((7200.0, 4500.0), (0.0, 4500.0)),
        ((0.0, 4500.0), (0.0, 0.0)),
    ), 1):
        create_wall(s, "W%03d" % i, a, b, thick=240.0, kind="EXTERNAL", floor=1)
    create_opening(s, "M001", "W001", "DOOR", width=900.0, pos=1500.0,
                   height=2100.0, no="M0921")
    create_opening(s, "C001", "W001", "WINDOW", width=1500.0, pos=5000.0,
                   height=1500.0, sill=900.0, no="C1515")
    create_room(s, "R001", ["W001", "W002", "W003", "W004"], name="教室")
    create_title_mark(s, "T01", (3600.0, -2500.0), "一层平面图", SCALE)

    res = copy_floor(s, 1, 2, offset=(0.0, 9000.0), prefix="2")
    create_title_mark(s, "T02", (3600.0, 14600.0), "二层平面图", SCALE)

    export(s, OUT / "demo_floor_copy_1f.png", window=(-2600.0, -3200.0, 9650.0, 5100.0))
    export(s, OUT / "demo_floor_copy_2f.png", window=(-2000.0, 8600.0, 9250.0, 16100.0))
    print("复制结果:", res["counts"], "墙", res["walls"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
